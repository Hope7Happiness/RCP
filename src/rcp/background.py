from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol, cast, get_args

from rcp.agents import AgentEvent, AgentProcessControl
from rcp.agents.failure_kinds import classify_agent_failure
from rcp.agents.git_access import ProviderGitAccess
from rcp.agents.provider_accounts import account_login_refusal, record_provider_failure
from rcp.agents.provider_environment import ProviderCredentialStore
from rcp.agents.write_scope import ProjectWriteScope
from rcp.artifacts import AgentArtifactDescriptor
from rcp.config import load_manifest
from rcp.core.authority import require_dispatch
from rcp.core.models import AuthorizedHuman, GraphState
from rcp.core.transition_models import GraphTargetRef
from rcp.limits import (
    AGENT_TRANSPORT_RETRY_BACKOFF_SECONDS,
    AGENT_TRANSPORT_RETRY_LIMIT,
    BACKGROUND_TASKS_SHUTDOWN_TIMEOUT_SECONDS,
    CHAT_ARTIFACT_MAX_COUNT,
    GRAPH_UPDATE_HISTORY_MAX_COUNT,
    REMOTE_RESULT_RECONCILIATION_INTERVAL_SECONDS,
)
from rcp.machine_sleep import seconds_until_automatic_launch
from rcp.providers import classify_terminal_error, profile_for, require_runtime_id
from rcp.runs.auto_research import (
    AutoResearchRunRequest,
    AutoResearchWakeAdmission,
    PendingAutoResearchMail,
)
from rcp.runs.auto_research_admission import (
    auto_research_admission_exhausted,
    auto_research_for_request,
    ensure_auto_research_wake_spawned,
    preflight_auto_research_task_resume,
    proven_committed_auto_research_dispatches,
    proven_reserved_auto_research_roots,
    retry_auto_research_task,
)
from rcp.runs.auto_research_mail import auto_research_mail_claim_prefix
from rcp.runs.auto_research_recovery import (
    AutoResearchOrchestratorTerminalFailure,
    record_structural_failure,
)
from rcp.runs.branch_merge_request import BranchMergeRunRequest
from rcp.runs.episodes.report import restart_interrupted_episode_reports
from rcp.runs.experiment_recovery import (
    experiment_rerun_continuation,
    preflight_experiment_episode_recovery,
    record_bound_experiment_session_limit,
    restart_stopping_experiment_recoveries,
    retry_experiment_loop,
)
from rcp.runs.provider_login import ProviderSignedOut, provider_login_host
from rcp.runs.provider_process import require_remote_provider_quiescence
from rcp.runs.recorded_turn import RecordedProviderTurn
from rcp.runs.task_policy import (
    AgentTaskContinuation,
    AgentTaskRequest,
    DispatchAuthorityResolver,
    load_stored_request,
    resolved_dispatch_authority,
    skill_update,
    task_graph_capable,
)
from rcp.runs.tasks.episode_report import EpisodeReportRunRequest
from rcp.server_ops.maintenance import MaintenanceAdmissionClosed
from rcp.service import (
    CoachRequest,
    GraphUpdateResult,
    ProjectService,
    RunRequest,
    resolve_dispatch_authority,
)
from rcp.skill_registry import SkillSelection
from rcp.storage import (
    AgentFailureKind,
    AgentTaskKind,
    AgentTaskRecord,
    AppStore,
    EpisodeInvocationCeilingReached,
    EpisodeRecord,
)
from rcp.storage.models import AgentTaskAlreadyContinued
from rcp.transport import RemoteRunStage, StateMissing, StateUnavailable, StateUnreachable

logger = logging.getLogger(__name__)


_AGENT_TASK_CONTINUATIONS = frozenset(get_args(AgentTaskContinuation))

# A watcher wake reuses a native session without being task Resume: it is a new
# task at the next invocation, so it must never inherit Resume's same-invocation
# parent/child recovery semantics.
_NATIVE_CHECKPOINT_CONTINUATIONS = frozenset(
    {
        "resume",
        "retry",
        "graph_repair",
        "watcher_wake",
        "graph_condition_wake",
        "message_wake",
        "lifecycle_wake",
        "auto_research_continuation",
        "episode_report",
    }
)


class StartupEffectBlocked(RuntimeError):
    """A candidate tried to cross the closed startup-effect boundary."""


class StartupEffectFence:
    """One shared gate for startup verification and later update cutover.

    The fence is deliberately an in-process object rather than an environment
    flag. Callers hold the exact object that records an attempted effect, and
    releasing it changes the same gate consulted by the background engine.
    Candidate rehearsal never releases it.
    """

    def __init__(self, reason: str) -> None:
        if not reason or reason != reason.strip():
            raise ValueError("startup-effect fence reason must be one nonempty line")
        self.reason = reason
        self._active = True
        self._attempts: list[str] = []
        self._release_callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def attempted_effects(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._attempts)

    def require_open(self, effect: str) -> None:
        if not effect or effect != effect.strip():
            raise ValueError("startup effect name must be one nonempty line")
        with self._lock:
            if not self._active:
                return
            self._attempts.append(effect)
        raise StartupEffectBlocked(
            f"Startup effects are closed for {self.reason}; blocked {effect}."
        )

    def release(self) -> None:
        with self._lock:
            if self._attempts:
                raise StartupEffectBlocked(
                    "Startup effects cannot open after a blocked effect was attempted."
                )
            if not self._active:
                return
            self._active = False
            callbacks = tuple(self._release_callbacks)
            self._release_callbacks.clear()
        for callback in callbacks:
            callback()

    def on_release(self, callback: Callable[[], None]) -> None:
        """Run one callback when this exact fence opens, including late registration."""

        with self._lock:
            if self._active:
                self._release_callbacks.append(callback)
                return
        callback()


class RuntimeAdmissionGate(Protocol):
    """The installed-service owner may close new launches during maintenance."""

    def require_open(self, effect: str) -> None: ...


@dataclass(frozen=True)
class StartupRecoveryPlan:
    """Read-only inventory of work ordinary startup would reconcile."""

    active_operation_ids: tuple[str, ...]
    stopping_experiment_operation_ids: tuple[str, ...]
    report_episode_ids: tuple[str, ...]
    auto_research_recovery_operation_ids: tuple[str, ...]
    active_watcher_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, tuple[str, ...]]:
        return {
            "active_operation_ids": self.active_operation_ids,
            "stopping_experiment_operation_ids": self.stopping_experiment_operation_ids,
            "report_episode_ids": self.report_episode_ids,
            "auto_research_recovery_operation_ids": (self.auto_research_recovery_operation_ids),
            "active_watcher_ids": self.active_watcher_ids,
        }


@dataclass
class AgentTaskExecution:
    operation_id: str
    store: AppStore
    control: AgentProcessControl
    runtime_id: str = ""
    git_access: ProviderGitAccess | None = None
    login_generation: int = 0
    stage_host: str | None = None
    stage_root: str | None = None
    write_scope_fingerprint: str | None = None
    continuation: AgentTaskContinuation = "fresh"
    retry_feedback: tuple[str, ...] = ()
    applied_revision: int | None = None
    applied_graph_state: GraphState | None = None
    armed_graph_watchers: bool = False
    compatible_related_write_scope_fingerprints: frozenset[str] = frozenset()
    #: Set when a stage read or host probe during this run failed because the
    #: host could not be reached, rather than because a deliverable was bad or a
    #: setting refused. Only the read that failed knows which happened, and by
    #: the time settlement has turned it into a failure the difference is gone.
    #: Before the provider starts it is also the only witness classification
    #: has, since no process exists to leave an exit code. In memory because it
    #: describes this attempt, not the task.
    stage_unreachable: bool = False

    @property
    def reuses_native_checkpoint(self) -> bool:
        return self.continuation in _NATIVE_CHECKPOINT_CONTINUATIONS

    def checkpoint_stage(self, host: str, root: str) -> None:
        if host:
            require_remote_provider_quiescence(self.store, host, root)
        self.stage_host = host or None
        self.stage_root = root
        self.store.checkpoint_agent_task(
            self.operation_id,
            stage_host=host or None,
            stage_root=root,
        )
        self.store.record_agent_task_receipt(
            self.operation_id,
            "stage_checkpoint",
            {"remote": bool(host), "stage_available": bool(root)},
            tier="diagnostic",
        )

    def bind_write_scope(self, scope: ProjectWriteScope, *, resumes_native_session: bool) -> None:
        if self.stage_root is None:
            raise ValueError(
                "agent task must checkpoint its exact stage before write-scope binding"
            )
        legacy_inputs = str(PurePosixPath(scope.stage_root) / "inputs")
        compatible_previous_fingerprint = None
        if (
            scope.workspace_root == scope.stage_root
            and legacy_inputs in scope.protected_write_paths
        ):
            # A legacy local stage used its root as cwd and bound this otherwise-
            # identical scope before inputs had an explicit deny.
            compatible_previous_fingerprint = ProjectWriteScope.create(
                project_id=scope.project_id,
                execution_machine=scope.execution_machine,
                execution_host=scope.execution_host,
                capability=scope.capability,
                stage_root=scope.stage_root,
                workspace_root=scope.workspace_root,
                repositories=scope.repositories,
                git_metadata_roots=scope.git_metadata_roots,
                protected_write_paths=[
                    path for path in scope.protected_write_paths if path != legacy_inputs
                ],
            ).fingerprint
        self.store.bind_agent_task_write_scope(
            self.operation_id,
            project_id=scope.project_id,
            stage_host=self.stage_host or "",
            stage_root=scope.stage_root,
            fingerprint=scope.fingerprint,
            # A continuation is a launch that carries an existing provider
            # session into this turn, whichever label admission gave it: the
            # session is what would gain authority it did not start with. A
            # launch that brings no session establishes the stage binding
            # instead, which is how a run scope legitimately changes.
            continuation_binding=self.reuses_native_checkpoint or resumes_native_session,
            scope_repositories=[item.alias for item in scope.repositories],
            compatible_previous_fingerprint=compatible_previous_fingerprint,
            compatible_related_fingerprints=self.compatible_related_write_scope_fingerprints,
        )
        self.write_scope_fingerprint = scope.fingerprint


AgentTaskStream = Callable[
    [str, AgentTaskKind, AgentTaskRequest, AgentTaskExecution], AsyncIterator[str]
]
RecordedAgentTaskStream = Callable[
    [str, AgentTaskKind, AgentTaskRequest, AgentTaskExecution, RecordedProviderTurn],
    AsyncIterator[str],
]
AgentTaskStreamClosedHook = Callable[
    [str, AgentTaskKind, AgentTaskRequest, AgentTaskExecution], None
]
AgentTaskSettledHook = Callable[[str, AgentTaskKind, AgentTaskRequest, AgentTaskExecution], None]
AutoResearchAdmissionExhaustedHook = Callable[[EpisodeRecord], None]


@dataclass(frozen=True)
class AgentTaskOutcome:
    applied_revision: int | None
    messages: list[str]
    artifacts: list[AgentArtifactDescriptor]
    graph_update: GraphUpdateResult | None = None
    graph_updates: list[GraphUpdateResult] = field(default_factory=list)


class TaskPaused(RuntimeError):
    def __init__(
        self,
        message: str,
        messages: list[str] | None = None,
        artifacts: list[AgentArtifactDescriptor] | None = None,
    ) -> None:
        self.messages = list(messages or [])
        self.artifacts = list(artifacts or [])
        super().__init__(message)


class TaskFailed(RuntimeError):
    """A task that failed after producing output worth keeping.

    A chat turn can answer the human and only then have its graph change rejected.
    The answer is already written and already useful, so it travels with the
    failure instead of being dropped with the stream.
    """

    def __init__(
        self,
        message: str,
        messages: list[str],
        artifacts: list[AgentArtifactDescriptor],
    ) -> None:
        super().__init__(message)
        self.messages = messages
        self.artifacts = artifacts


class TaskAwaitingRemoteResult(RuntimeError):
    """The host owns this turn now; the original task remains unsettled."""


def _require_recoverable_machine(
    previous: AgentTaskRecord,
    original: AgentTaskRequest,
    run_on: str | None,
) -> None:
    """Refuse the one recovery rebinding an episode cannot survive.

    Provider, model, and reasoning are one niche a human may change on any
    recovery. The execution machine is different only where an episode is bound
    to it: its watchers, stage, and children live on that machine and moving the
    turn would orphan them. A standalone turn owns nothing there, so it may move
    to a reachable one.
    """

    if run_on is not None and run_on != original.run_on and previous.episode_id is not None:
        raise ValueError("Recovery cannot change its pinned execution machine.")


class BackgroundAgentTasks:
    def __init__(
        self,
        store: AppStore,
        stream: AgentTaskStream,
        on_stream_closed: AgentTaskStreamClosedHook | None = None,
        on_task_settled: AgentTaskSettledHook | None = None,
        on_auto_research_admission_exhausted: AutoResearchAdmissionExhaustedHook | None = None,
        dispatch_authority_resolver: DispatchAuthorityResolver | None = None,
        startup_effect_fence: StartupEffectFence | None = None,
        runtime_admission_gate: RuntimeAdmissionGate | None = None,
        recorded_stream: RecordedAgentTaskStream | None = None,
    ) -> None:
        self.store = store
        self.stream = stream
        self.on_stream_closed = on_stream_closed
        self.on_task_settled = on_task_settled
        self.on_auto_research_admission_exhausted = on_auto_research_admission_exhausted
        self.dispatch_authority_resolver = dispatch_authority_resolver or resolve_dispatch_authority
        self.startup_effect_fence = startup_effect_fence
        self.runtime_admission_gate = runtime_admission_gate
        self.recorded_stream = recorded_stream
        self._controls: dict[str, AgentProcessControl] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._controls_lock = threading.Lock()
        self._shutdown_requested = False
        self._transport_retry_timers: list[threading.Timer] = []
        # An automatic reattempt that has passed its shutdown check is admitting
        # a child. Shutdown waits for it under this condition before it fences
        # spawns, so the child it admits gets a worker instead of being left
        # queued for a startup that would only interrupt it.
        self._transport_retry_admissions = 0
        self._transport_retry_closed = False
        self._transport_retry_fence = threading.Condition(self._controls_lock)
        self._remote_reconciliation_timer: threading.Timer | None = None
        self._remote_reconciliation_worker: threading.Thread | None = None
        self._remote_reconciliation_requested = False
        self._remote_result_lock = threading.Lock()
        self._watcher_delivery_lock = threading.Lock()
        self._accepting_watcher_deliveries = not (
            startup_effect_fence is not None and startup_effect_fence.active
        )

    def admit_provider_task(
        self, project_id: str, request: AgentTaskRequest, *, execution_host: str | None = None
    ) -> None:
        """Refuse an ineligible execution account before durable allocation or debit."""

        if request.provider is None:
            raise ValueError("Provider task admission requires a resolved provider.")
        host = execution_host
        if host is None:
            if request.run_on in {None, "local"}:
                host = ""
            else:
                project = self.store.project(project_id)
                if project is None:
                    raise KeyError(project_id)
                host = provider_login_host(load_manifest(project.locator), request.run_on)
        if reason := account_login_refusal(
            self.store,
            ProviderCredentialStore.for_data_dir(self.store.path.parent),
            request.provider,
            host,
        ):
            raise ProviderSignedOut(reason)

    def plan_startup_recovery(self) -> StartupRecoveryPlan:
        """Describe recovery work without changing a row or resolving a stage."""

        projects = self.store.projects()
        tasks = [
            task
            for project in projects
            for task in self.store.all_project_agent_tasks(project.project_id)
        ]
        watchers = [
            watcher
            for project in projects
            for watcher in self.store.active_graph_watchers(project.project_id)
        ]
        return StartupRecoveryPlan(
            active_operation_ids=tuple(sorted(task.operation_id for task in tasks if task.active)),
            stopping_experiment_operation_ids=tuple(
                sorted(
                    task.operation_id
                    for task in self.store.stopping_experiment_recovery_candidates()
                )
            ),
            report_episode_ids=tuple(
                sorted(episode.episode_id for episode in self.store.episodes_awaiting_report())
            ),
            auto_research_recovery_operation_ids=tuple(
                sorted(task.operation_id for task in self.store.auto_research_recovery_candidates())
            ),
            active_watcher_ids=tuple(sorted(watcher.watcher_id for watcher in watchers)),
        )

    def _require_startup_effects_open(self, effect: str) -> None:
        if self.startup_effect_fence is not None:
            self.startup_effect_fence.require_open(effect)
        if self.runtime_admission_gate is not None:
            self.runtime_admission_gate.require_open(effect)

    def recover_at_startup(self) -> None:
        """Reconcile work a previous process left behind. Called once, by the lifespan.

        This ran in ``__init__`` until constructing the engine stopped writing to
        the store.  It stays on this class as a waypoint: when the job-specific
        owners move out it becomes startup orchestration that calls each owner,
        and the wrong-way calls below leave with them.

        Errors are deliberately not caught.  A constructor exception used to fail
        ``create_app``; this must still fail startup rather than open the app over
        state nobody reconciled.
        """

        self._require_startup_effects_open("startup recovery")
        self._reconcile_herdr_bindings()
        with self._controls_lock:
            self._shutdown_requested = False
            self._transport_retry_closed = False
            self._transport_retry_admissions = 0
        preserved_dispatches = proven_committed_auto_research_dispatches(self)
        reserved_roots = proven_reserved_auto_research_roots(self)
        self.store.interrupt_active_agent_tasks(
            preserve_operation_ids={
                *[item.operation_id for item in preserved_dispatches],
                *[task.operation_id for _episode, task, _request in reserved_roots],
            }
        )
        restart_stopping_experiment_recoveries(self)
        self.store.settle_ready_experiment_loop_stops()
        restart_interrupted_episode_reports(self)
        self._rearm_owed_transport_retries()
        self._schedule_remote_reconciliation(delay=0)

    def _reconcile_herdr_bindings(self) -> None:
        """Stop exact previously owned native panes before interrupting tasks."""

        bindings = self.store.unresolved_herdr_bindings()
        if not bindings:
            return

        async def reconcile(operation_id: str, binding: dict[str, object]) -> None:
            from rcp.agents.herdr_bridge import (
                HerdrBridgeError,
                HerdrNativeAdapter,
                HerdrNativeAgent,
                cleanup_isolated_codex_home,
            )

            pane_id = binding.get("pane_id")
            provider = binding.get("provider")
            name = binding.get("agent_name")
            session_id = binding.get("native_session_id")
            group_id = binding.get("process_group_id")
            if not all(isinstance(value, str) and value for value in (pane_id, provider, name)):
                raise ValueError("An unfinished Herdr binding has malformed identity.")
            if session_id is not None and (not isinstance(session_id, str) or not session_id):
                raise ValueError("An unfinished Herdr binding has malformed session identity.")
            if provider not in {"codex", "claude"} or not isinstance(group_id, int):
                raise ValueError("An unfinished Herdr binding has malformed process identity.")
            adapter = HerdrNativeAdapter()
            agent = HerdrNativeAgent(pane_id, provider, name)
            try:
                observation = await adapter.get(agent)
            except HerdrBridgeError:
                if await adapter.pane_present(pane_id):
                    raise ValueError(
                        "An unfinished Herdr pane still exists but its agent identity changed."
                    ) from None
            else:
                if session_id is not None and observation.session_id not in (None, session_id):
                    raise ValueError("An unfinished Herdr pane changed native session.")
                identity = await adapter.process_info(agent)
                if identity.foreground_process_group_id != group_id:
                    raise ValueError("An unfinished Herdr pane changed provider process.")
                await adapter.close(agent)
            codex_home = binding.get("codex_home")
            if codex_home is not None:
                if provider != "codex" or not isinstance(codex_home, str):
                    raise ValueError("An unfinished Herdr binding has malformed Codex home.")
                cleanup_isolated_codex_home(codex_home)
            self.store.finish_herdr_binding(operation_id, binding)

        def run() -> None:
            async def all_bindings() -> None:
                for operation_id, binding in bindings:
                    await reconcile(operation_id, binding)

            asyncio.run(all_bindings())

        # Startup runs inside the app lifespan event loop. The socket client is
        # async, so reconcile in one worker thread and fail startup on ambiguity.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(run).result()

    def start(
        self,
        project_id: str,
        kind: AgentTaskKind,
        request: AgentTaskRequest,
        *,
        operation_id: str | None = None,
        authorized_by: AuthorizedHuman | None = None,
        stage_host: str | None = None,
        stage_root: str | None = None,
        graph_target: GraphTargetRef | None = None,
    ) -> AgentTaskRecord:
        self._require_startup_effects_open("provider task dispatch")
        if kind == "auto_research":
            raise ValueError(
                "Use start_auto_research so its episode and root are created atomically."
            )
        if kind == "branch_merge":
            raise ValueError(
                "Use start_branch_merge so its ended episode and exact branch are checked "
                "atomically."
            )
        if kind == "episode_report":
            raise ValueError(
                "Use start_episode_report so the existing hidden allocation is preserved."
            )
        experiment_root = (
            isinstance(request, RunRequest)
            and request.patch_kind == "experiment_loop"
            and request.trigger == "experiment_run"
        )
        if (
            isinstance(request, RunRequest)
            and request.patch_kind == "experiment_loop"
            and not experiment_root
        ):
            raise ValueError(
                "An Experiment watcher wake or recovery must use its dedicated admission path."
            )
        if kind in {"seed", "refresh"} and request.session_id:
            raise ValueError(
                "Seed and refresh sessions can only be resumed from an RCP background "
                "task checkpoint."
            )
        result_view_revision = (
            isinstance(request, RunRequest)
            and request.result_view is not None
            and request.result_view.action == "revise"
        )
        if result_view_revision and (not request.session_id or not stage_root):
            raise ValueError(
                "A result-view revision requires its saved native session and exact stage."
            )
        if not result_view_revision and (stage_host is not None or stage_root is not None):
            raise ValueError("Only a result-view revision may inherit a saved stage on start.")
        self._validate_request_type(kind, request)
        request_data = request.model_dump(mode="json")
        estimate, samples = self.store.agent_task_estimate(project_id, kind, request_data)
        return self._create_and_spawn(
            project_id,
            kind,
            request,
            estimate_seconds=estimate,
            estimate_samples=samples,
            operation_id=operation_id,
            authorized_by=authorized_by,
            stage_host=stage_host,
            stage_root=stage_root,
            graph_target=graph_target,
        )

    def resume(
        self,
        operation_id: str,
        *,
        skills: SkillSelection | None = None,
        authorized_by: AuthorizedHuman | None = None,
    ) -> AgentTaskRecord:
        self._require_startup_effects_open("provider task resume")
        previous = self._require_operation(operation_id)
        if previous.kind == "episode_report":
            raise ValueError("Episode report recovery is automatic and has no Resume control.")
        if not previous.can_resume or not previous.native_session_id:
            raise ValueError(
                "This task has no resumable native agent checkpoint. Retry it instead."
            )
        if not self._session_is_rcp_owned(previous):
            raise ValueError(
                "This task's native session was not checkpointed or validated by RCP. "
                "Retry it instead."
            )
        original = self._request_from_record(previous)
        if isinstance(original, AutoResearchRunRequest):
            preflight_auto_research_task_resume(self, previous)
        preflight_experiment_episode_recovery(self, previous, request=original)
        request = original.model_copy(
            update={"session_id": previous.native_session_id, **skill_update(skills)}
        )
        continuation: AgentTaskContinuation = (
            "graph_repair"
            if self.store.agent_task_continuation_cause(previous.operation_id) == "graph_repair"
            else "resume"
        )
        return self._create_and_spawn(
            previous.project_id,
            previous.kind,
            request,
            parent=previous,
            continuation=continuation,
            estimate_seconds=previous.estimate_seconds,
            estimate_samples=previous.estimate_samples,
            stage_host=previous.stage_host,
            stage_root=previous.stage_root,
            authorized_by=authorized_by,
        )

    def retry(
        self,
        operation_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        reasoning: str | None = None,
        run_on: str | None = None,
        skills: SkillSelection | None = None,
        authorized_by: AuthorizedHuman | None = None,
    ) -> AgentTaskRecord:
        self._require_startup_effects_open("provider task retry")
        previous = self._require_operation(operation_id)
        if previous.kind == "episode_report":
            raise ValueError("Episode report recovery is automatic and has no Retry control.")
        if not previous.can_retry:
            raise ValueError("Only a paused, interrupted, or failed task can be retried.")
        original = self._request_from_record(previous)
        _require_recoverable_machine(previous, original, run_on)
        if isinstance(original, AutoResearchRunRequest):
            return retry_auto_research_task(
                self,
                previous,
                original,
                provider=provider,
                model=model,
                reasoning=reasoning,
                run_on=run_on,
                skills=skills,
            )
        preflight_experiment_episode_recovery(self, previous, request=original)
        graph_repair = (
            self.store.agent_task_continuation_cause(previous.operation_id) == "graph_repair"
        )
        if isinstance(original, RunRequest) and original.patch_kind == "experiment_loop":
            if run_on is not None:
                raise ValueError(
                    "Experiment-loop recovery cannot change its pinned execution machine."
                )
            if not graph_repair:
                return retry_experiment_loop(
                    self,
                    previous,
                    original,
                    provider=provider,
                    model=model,
                    reasoning=reasoning,
                    skills=skills,
                    authorized_by=authorized_by,
                )
        updates = {
            key: value
            for key, value in {
                "provider": provider,
                "model": model,
                "reasoning": reasoning,
                "run_on": run_on,
            }.items()
            if value is not None
        }
        request = type(original).model_validate(
            {
                **original.model_dump(mode="json"),
                **updates,
                **skill_update(skills, mode="json"),
                "session_id": None,
            }
        )
        same_provider = request.provider == original.provider
        same_model = request.model == original.model
        same_reasoning = request.reasoning == original.reasoning
        same_execution_host = request.run_on == original.run_on
        session_limit = self._failure_is_session_limit(previous)
        # Resuming a session the provider has dropped fails the same way every
        # time; a fresh session is the only attempt that can succeed.
        stale_session = self._failure_is_stale_session(previous)
        continuation_context_unavailable = self._continuation_context_is_unavailable(previous)
        owned_checkpoint = (
            bool(previous.native_session_id)
            and bool(previous.stage_root)
            and self._session_is_rcp_owned(previous)
        )
        result_view_revision = bool(
            isinstance(original, RunRequest)
            and original.result_view is not None
            and original.result_view.action == "revise"
        )
        must_reuse_saved_session = graph_repair or result_view_revision
        if must_reuse_saved_session:
            problem = None
            stage_available: bool | None = True
            if owned_checkpoint and previous.stage_host:
                stage_available = RemoteRunStage(previous.stage_host).directory_exists(
                    previous.stage_root or ""
                )
            elif owned_checkpoint and previous.stage_root:
                stage = Path(previous.stage_root)
                stage_available = stage.is_dir() and not stage.is_symlink()
            if session_limit:
                problem = "the native provider session reached its limit"
            elif stale_session:
                problem = "the provider no longer has the saved session"
            elif continuation_context_unavailable:
                problem = "the saved continuation context is unavailable"
            elif result_view_revision and (
                not same_provider or not same_model or not same_reasoning or not same_execution_host
            ):
                problem = "the pinned provider, model, reasoning, or execution machine changed"
            elif not same_provider or not same_execution_host:
                problem = "the pinned provider or execution machine changed"
            elif not owned_checkpoint:
                problem = "the prior task has no complete RCP-owned session and stage"
            elif stage_available is not True:
                problem = "the saved provider workspace is unavailable"
            if problem is not None:
                detail = (
                    "This result-view revision cannot start a fresh provider session because "
                    f"{problem}. The existing view was not redrawn; start a new result view "
                    "instead."
                    if result_view_revision
                    else "This patch-only graph repair cannot start a full Work turn because "
                    f"{problem}. Start a new Work turn instead."
                )
                raise ValueError(detail)
            assert previous.native_session_id is not None
            request = request.model_copy(update={"session_id": previous.native_session_id})
            return self._create_and_spawn(
                previous.project_id,
                previous.kind,
                request,
                parent=previous,
                continuation="graph_repair" if graph_repair else "retry",
                estimate_seconds=previous.estimate_seconds,
                estimate_samples=previous.estimate_samples,
                stage_host=previous.stage_host,
                stage_root=previous.stage_root,
                authorized_by=authorized_by,
            )
        retry_same_provider = (
            previous.status == "failed"
            and same_provider
            and same_execution_host
            and owned_checkpoint
            and not session_limit
            and not stale_session
            and not continuation_context_unavailable
        )
        if retry_same_provider:
            request = request.model_copy(update={"session_id": previous.native_session_id})
            return self._create_and_spawn(
                previous.project_id,
                previous.kind,
                request,
                parent=previous,
                continuation="retry",
                estimate_seconds=previous.estimate_seconds,
                estimate_samples=previous.estimate_samples,
                stage_host=previous.stage_host,
                stage_root=previous.stage_root,
                authorized_by=authorized_by,
            )
        if (
            previous.native_session_id
            and self.store.codex_continuation(previous.native_session_id) is not None
        ):
            raise ValueError(
                "This imported Codex chat is bound to its original native session. "
                "Retry cannot start a fresh session; resolve the saved session and "
                "continue from its RCP chat."
            )
        estimate, samples = self.store.agent_task_estimate(
            previous.project_id,
            previous.kind,
            request.model_dump(mode="json"),
        )
        retried = self._create_and_spawn(
            previous.project_id,
            previous.kind,
            request,
            parent=previous,
            continuation="handoff",
            estimate_seconds=estimate,
            estimate_samples=samples,
            authorized_by=authorized_by,
        )
        if same_provider and (session_limit or stale_session):
            classification = "session_limit" if session_limit else "stale_session"
            self.store.record_agent_task_receipt(
                retried.operation_id,
                "native_resume_skipped",
                {"classification": classification},
                tier="diagnostic",
            )
            self.store.record_agent_task_event(
                retried.operation_id,
                "The provider session limit was exhausted; starting a clean retry."
                if session_limit
                else "The provider no longer has the saved session; starting a clean retry.",
                level="warning",
            )
        elif previous.status == "failed" and same_provider and not retry_same_provider:
            reason = (
                "execution host changed"
                if not same_execution_host
                else "the saved continuation context is unavailable"
                if continuation_context_unavailable
                else "the prior task has no complete RCP-owned native checkpoint and stage"
            )
            self.store.record_agent_task_receipt(
                retried.operation_id,
                "native_resume_unavailable",
                {"reason": reason},
                tier="diagnostic",
            )
            self.store.record_agent_task_event(
                retried.operation_id,
                f"Native resume is unavailable because {reason}; starting a clean retry.",
                level="warning",
            )
        return retried

    def repair_graph_update(
        self,
        operation_id: str,
        *,
        authorized_by: AuthorizedHuman | None = None,
    ) -> AgentTaskRecord:
        """Create one idempotent patch-only continuation for a rejected Work result."""

        self._require_startup_effects_open("provider graph-repair dispatch")
        previous = self._require_operation(operation_id)
        if previous.kind not in {"node_chat", "project_chat"}:
            raise ValueError("Only a conversation Work task can repair a graph update.")
        request = self._request_from_record(previous)
        if not isinstance(request, RunRequest) or request.mode != "work":
            raise ValueError("Only a Work turn can repair a graph update.")
        if (
            not previous.native_session_id
            or not previous.stage_root
            or not self._session_is_rcp_owned(previous)
        ):
            raise ValueError(
                "The rejected graph update has no retained RCP-owned session and stage. "
                "Start a new Work turn instead."
            )
        request = request.model_copy(
            update={"session_id": previous.native_session_id, "message": None}
        )
        return self._create_and_spawn(
            previous.project_id,
            previous.kind,
            request,
            parent=previous,
            continuation="graph_repair",
            claim_graph_repair_parent=True,
            estimate_seconds=previous.estimate_seconds,
            estimate_samples=previous.estimate_samples,
            stage_host=previous.stage_host,
            stage_root=previous.stage_root,
            authorized_by=authorized_by,
        )

    def retry_auto_research(
        self,
        operation_id: str,
        *,
        service: ProjectService,
        provider: str | None = None,
        model: str | None = None,
        reasoning: str | None = None,
        run_on: str | None = None,
        skills: SkillSelection | None = None,
    ) -> AgentTaskRecord:
        """Run the HTTP Retry path with target readiness owned by Auto-research."""

        self._require_startup_effects_open("provider task retry")
        previous = self._require_operation(operation_id)
        if not previous.can_retry:
            raise ValueError("Only a paused, interrupted, or failed task can be retried.")
        original = self._request_from_record(previous)
        if not isinstance(original, AutoResearchRunRequest):
            raise ValueError("This task is not an Auto-research task.")
        _require_recoverable_machine(previous, original, run_on)
        # Only a human reaches this entry point, and starting a turn is the
        # answer a stopped ladder was waiting for. The automatic path settles
        # its own row and must keep counting, so it is left alone. A turn that
        # is never admitted leaves the row `admitted` with nothing running,
        # which reads as the failed parent it still points at.
        released = self.store.release_settled_auto_research_recovery(previous.operation_id)
        try:
            return retry_auto_research_task(
                self,
                previous,
                original,
                provider=provider,
                model=model,
                reasoning=reasoning,
                run_on=run_on,
                skills=skills,
                service=service,
            )
        except BaseException:
            # A released row names no attempt, and a failed orchestrator whose
            # recovery names no attempt is never quiescent, so a Stop after this
            # refusal would wait forever on a turn that was never created. A
            # child that was already committed is a turn: startup or a later
            # sign-in can still launch it, and it owes its own failure a ladder.
            if (
                released is not None
                and self.store.auto_research_task_recovery_child(previous.operation_id) is None
            ):
                self.store.restore_settled_auto_research_recovery(previous.operation_id, released)
            raise

    def pause(self, operation_id: str) -> AgentTaskRecord:
        self._require_startup_effects_open("provider task pause")
        current = self._require_operation(operation_id)
        if current.kind == "episode_report":
            raise ValueError("Episode report generation has no manual Pause control.")
        if current.phase == "awaiting_remote_result":
            with self._remote_result_lock:
                current = self._require_operation(operation_id)
                if current.phase != "awaiting_remote_result":
                    raise ValueError("This task's recorded result is already being finalized.")
                return self._pause_waiting_remote_result(current)
        if current.phase == "finalizing_recorded_result":
            raise ValueError("This task's recorded result is already being finalized.")
        record = self.store.request_agent_task_pause(operation_id)
        self._signal_agent_task_pause(operation_id)
        return record

    def _pause_waiting_remote_result(self, record: AgentTaskRecord) -> AgentTaskRecord:
        """Stop a detached remote turn now, or leave it untouched if not provable."""

        host = record.stage_host or ""
        root = record.stage_root or ""
        passes = [
            pid_file
            for operation_id, pid_file in self.store.unresolved_remote_provider_passes(host, root)
            if operation_id == record.operation_id
        ]
        if not host or not root or not passes:
            raise ValueError("This task has no outstanding remote provider pass to stop.")
        pid_file = passes[-1]
        stopped, identity = AgentProcessControl.remote_process_state(host, pid_file)
        if stopped is None:
            raise ValueError(
                "The execution host is unreachable, so RCP left the remote turn running."
            )
        if stopped is True:
            raise ValueError(
                "The remote provider already stopped; RCP will reconcile its recorded result."
            )
        if stopped is False:
            if identity is None:
                raise ValueError(
                    "RCP could not prove the remote process identity, so it was not signalled."
                )
            if not AgentProcessControl.stop_remote_process(
                host,
                pid_file,
                expected_identity=identity,
            ):
                raise ValueError(
                    "RCP could not confirm that the remote provider stopped; no delayed stop was queued."
                )
        # The provider may have finished between the probe and the stop signal.
        # Preserve a completed or temporarily unreadable journal for its owner.
        from rcp.runs.remote_reconciliation import reconcile_remote_pass

        result = reconcile_remote_pass(self.store, record, stopped=lambda *_: True)
        if result.action != "fail":
            raise ValueError(
                "The remote provider stopped; RCP will reconcile its recorded result before Pause."
            )
        self.store.request_agent_task_pause(record.operation_id)
        self.store.finish_remote_provider_pass(record.operation_id, pid_file)
        self.store.pause_agent_task(
            record.operation_id,
            detail="Remote provider stopped at the human's request.",
        )
        return self._require_operation(record.operation_id)

    def request_member_removal_pause(self, operation_id: str) -> AgentTaskRecord:
        """Fence a task without terminating an already-running provider turn."""

        current = self._require_operation(operation_id)
        if not current.active:
            return current
        record = self.store.request_agent_task_pause(
            operation_id,
            requested_by="member_removal",
        )
        # A durably queued row normally owns a worker that will observe
        # ``pausing`` before provider dispatch. A crash fixture or recovered
        # admission may have no worker; terminalize only that unowned row.
        with self._controls_lock:
            worker = self._workers.get(operation_id)
        if worker is None or not worker.is_alive():
            self.store.pause_agent_task(
                operation_id,
                detail="Paused because the authorizing member was removed.",
            )
            settled = self.store.agent_task(operation_id)
            assert settled is not None
            return settled
        return record

    def live_control(self, operation_id: str) -> AgentProcessControl | None:
        """Return only the process control owned by this exact in-process attempt."""
        with self._controls_lock:
            return self._controls.get(operation_id)

    def _signal_agent_task_pause(self, operation_id: str) -> None:
        """Best-effort re-signal of a pause whose durable intent already exists."""

        with self._controls_lock:
            control = self._controls.get(operation_id)
        if control is not None:
            control.request_pause()

    def shutdown(self, *, timeout: float = BACKGROUND_TASKS_SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Pause live subprocesses before the web process exits."""
        with self._watcher_delivery_lock:
            self._accepting_watcher_deliveries = False
            with self._transport_retry_fence:
                # Closing the fence turns away reattempts that have not begun.
                # One that has already passed it is mid-admission; wait for it
                # before fencing spawns, so the child it admits gets a worker
                # and is paused with the rest rather than left queued for a
                # startup that would only interrupt it.
                self._transport_retry_closed = True
                deadline = time.monotonic() + timeout
                while self._transport_retry_admissions:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not self._transport_retry_fence.wait(remaining):
                        break
                self._shutdown_requested = True
                active = list(self._controls.items())
                workers = [self._workers.get(operation_id) for operation_id, _ in active]
                pending_retries = list(self._transport_retry_timers)
                self._transport_retry_timers.clear()
                reconciliation_timer = self._remote_reconciliation_timer
                self._remote_reconciliation_timer = None
                workers.append(self._remote_reconciliation_worker)
        for timer in pending_retries:
            timer.cancel()
        if reconciliation_timer is not None:
            reconciliation_timer.cancel()
        for operation_id, control in active:
            with suppress(ValueError):
                self.store.request_agent_task_pause(operation_id, requested_by="shutdown")
            control.request_pause()
        for worker in workers:
            if worker is None or worker is threading.current_thread():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(remaining)

    def accept_watcher_notifications(self) -> None:
        """Open automatic delivery admission for one app lifespan."""

        self._require_startup_effects_open("watcher delivery admission")
        with self._watcher_delivery_lock:
            self._accepting_watcher_deliveries = True

    def close_watcher_notifications(self) -> None:
        """Close automatic wake admission without stopping durable watchers."""

        with self._watcher_delivery_lock:
            self._accepting_watcher_deliveries = False

    def runtime_is_idle(self) -> bool:
        """Report whether provider workers and recorded finalization have settled."""

        with self._controls_lock:
            return (
                not self._workers
                and not self._controls
                and self._remote_reconciliation_worker is None
            )

    def _create_and_spawn(
        self,
        project_id: str,
        kind: AgentTaskKind,
        request: AgentTaskRequest,
        *,
        estimate_seconds: float,
        estimate_samples: int,
        parent: AgentTaskRecord | None = None,
        continuation: AgentTaskContinuation = "fresh",
        stage_host: str | None = None,
        stage_root: str | None = None,
        operation_id: str | None = None,
        authorized_by: AuthorizedHuman | None = None,
        auto_research_mail_delivery: PendingAutoResearchMail | None = None,
        auto_research_wake_admission: AutoResearchWakeAdmission | None = None,
        claim_graph_repair_parent: bool = False,
        graph_target: GraphTargetRef | None = None,
        continues_episode_id: str | None = None,
        continuation_request_id: str | None = None,
    ) -> AgentTaskRecord | None:
        """Insert one admitted task row and start it.

        Deliberately not split by surface.  It reads like four surfaces sharing
        one function, but 82% of it is universal row assembly, and no two owners
        have ever collided here — which is the failure a split would prevent.
        The Auto-research branch and its two parameters leave when Auto-research
        admission moves out and inserts its own row; that is a consequence of
        the move, not separate work.  Splitting the rest was measured and
        rejected.
        """

        self._require_startup_effects_open("provider task admission")
        self.admit_provider_task(
            project_id, request, execution_host=(stage_host or "") if stage_root else None
        )
        episode: EpisodeRecord | None = None
        task_graph_target = (
            parent.graph_target if parent is not None else graph_target or GraphTargetRef()
        )
        if parent is not None and graph_target is not None and parent.graph_target != graph_target:
            raise ValueError("A task continuation cannot change its graph target.")
        if isinstance(request, BranchMergeRunRequest):
            raise TypeError("BranchMergeRunRequest requires start_branch_merge.")
        if isinstance(request, AutoResearchRunRequest):
            if kind != "auto_research":
                raise TypeError("AutoResearchRunRequest requires auto_research task kind.")
            episode = auto_research_for_request(self, request.episode_id, request)
            authorized_by = episode.authorized_by
            task_graph_target = episode.graph_target
        elif isinstance(request, EpisodeReportRunRequest):
            raise TypeError("EpisodeReportRunRequest requires an existing hidden allocation.")
        elif isinstance(request, RunRequest) and request.patch_kind == "experiment_loop":
            stored_episode = self.store.episode(request.control_episode_id or "")
            if stored_episode is not None:
                if (
                    stored_episode.mode != "experiment_loop"
                    or stored_episode.project_id != project_id
                    or stored_episode.control_node_id != request.control_node_id
                ):
                    raise ValueError("The Experiment task changed its episode parent scope.")
                if stored_episode.authorized_by is None:
                    # The episode's own human is the authority for every turn in
                    # it, so a current human pressing Resume/Retry cannot stand in.
                    # Episodes created before that snapshot was recorded therefore
                    # have no recoverable authority; a fresh Run does.
                    raise ValueError(
                        "This Experiment-loop turn cannot be resumed or retried because its "
                        "episode predates the recorded human authorizer. Press Run on the "
                        "Experiment to start a fresh episode."
                    )
                authorized_by = stored_episode.authorized_by
                task_graph_target = stored_episode.graph_target
            elif parent is not None or request.trigger != "experiment_run":
                raise ValueError("The Experiment continuation lost its episode parent.")
        elif auto_research_mail_delivery is not None or auto_research_wake_admission is not None:
            raise ValueError("Only Auto-research may use Auto-research wake admission.")
        if task_graph_capable(kind, request) and authorized_by is None:
            raise ValueError("A patch-capable agent task requires a human authorizer snapshot.")
        if authorized_by is None:
            raise ValueError("An ordinary agent task requires a human authorizer snapshot.")
        if authorized_by is not None and not authorized_by.display_name.strip():
            raise ValueError("A human authorizer snapshot must include a nonblank display name.")
        if claim_graph_repair_parent and (parent is None or continuation != "graph_repair"):
            raise ValueError("Only an initial graph-repair admission can claim its parent.")
        if (continues_episode_id is None) != (continuation_request_id is None) or (
            continues_episode_id is not None
            and not (
                isinstance(request, RunRequest)
                and request.patch_kind == "experiment_loop"
                and request.trigger == "experiment_run"
                and parent is None
            )
        ):
            raise ValueError("Only an Experiment Run at invocation 1 can continue an episode.")
        operation_id = operation_id or str(uuid.uuid4())
        dispatch_authority = resolved_dispatch_authority(
            self.store,
            self.dispatch_authority_resolver,
            kind,
            request,
            project_id=project_id,
            parent=parent,
            operation_id=operation_id,
            continuation=continuation,
        )
        now = self.store.now()
        verb = (
            "repair its graph update"
            if continuation == "graph_repair"
            else "resume"
            if continuation == "resume"
            else "retry"
            if continuation in {"retry", "handoff"}
            else "start"
        )
        recovery = continuation in {"resume", "retry", "handoff", "graph_repair"}
        task_record = AgentTaskRecord(
            operation_id=operation_id,
            project_id=project_id,
            episode_id=(
                request.episode_id
                if isinstance(request, AutoResearchRunRequest)
                else request.control_episode_id
                if isinstance(request, RunRequest) and request.patch_kind == "experiment_loop"
                else None
            ),
            graph_target=task_graph_target,
            kind=kind,
            status="queued",
            request=request.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
            status_message=f"Waiting for the background worker to {verb}.",
            attempt=(parent.attempt + 1) if parent and recovery else 1,
            parent_operation_id=parent.operation_id if parent else None,
            native_session_id=request.session_id,
            stage_host=stage_host,
            stage_root=stage_root,
            estimate_seconds=estimate_seconds,
            estimate_samples=estimate_samples,
            phase="queued",
            last_activity_at=now,
            authorized_by=authorized_by,
            dispatch_authority=dispatch_authority,
        )
        if auto_research_mail_delivery is not None:
            selected_messages = auto_research_mail_claim_prefix(
                episode_id=auto_research_mail_delivery.episode_id,
                recipient_task_id=auto_research_mail_delivery.recipient_task_id,
                delivery_operation_id=task_record.operation_id,
                delivered_at=task_record.created_at,
                messages=auto_research_mail_delivery.messages,
            )
            if not selected_messages:
                return None
            auto_research_mail_delivery = auto_research_mail_delivery.model_copy(
                update={"messages": selected_messages}
            )
        if isinstance(request, AutoResearchRunRequest):
            assert episode is not None
            try:
                if continuation in {"resume", "retry"}:
                    record = self.store.create_auto_research_recovery_task(
                        task_record,
                        continuation_cause=continuation,
                    )
                elif auto_research_mail_delivery is not None:
                    record = self.store.create_auto_research_message_wake_task(
                        task_record,
                        role=request.role,
                        recipient_task_id=auto_research_mail_delivery.recipient_task_id,
                        message_ids=auto_research_mail_delivery.message_ids,
                    )
                elif auto_research_wake_admission is not None:
                    assert request.wake_cause is not None
                    record = auto_research_wake_admission(
                        task_record,
                        request.role,
                        request.wake_cause,
                    )
                else:
                    record = self.store.create_auto_research_agent_task(
                        task_record,
                        role=request.role,
                        continuation_cause=continuation,
                    )
            except EpisodeInvocationCeilingReached:
                auto_research_admission_exhausted(self, episode)
                raise
            if record is None:
                if auto_research_wake_admission is None and auto_research_mail_delivery is None:
                    raise RuntimeError(
                        "Auto-research admission returned no task outside a watcher or mail wake"
                    )
                return None
            if (
                record.operation_id != task_record.operation_id
                or record.project_id != episode.project_id
                or record.episode_id != episode.episode_id
            ):
                raise ValueError("Auto-research wake admission returned another task lineage.")
        elif isinstance(request, RunRequest) and request.patch_kind == "experiment_loop":
            if request.trigger == "experiment_run" and parent is None:
                record = self.store.create_experiment_episode_with_invocation(
                    task_record,
                    request.watcher_ids,
                    continues_episode_id=continues_episode_id,
                    continuation_request_id=continuation_request_id,
                )
            elif parent is not None and continuation in {
                "resume",
                "retry",
                "handoff",
                "graph_repair",
            }:
                if claim_graph_repair_parent:
                    record = self.store.create_experiment_graph_repair_task(
                        parent.operation_id,
                        task_record,
                    )
                else:
                    record = self.store.create_experiment_recovery_task(
                        task_record,
                        continuation_cause=continuation,
                    )
            else:
                raise ValueError("An Experiment watcher wake must use start_watcher_notification.")
        else:
            if claim_graph_repair_parent:
                assert parent is not None
                record = self.store.create_agent_task_graph_repair(
                    parent.operation_id,
                    task_record,
                )
            else:
                record = self.store.create_agent_task(
                    task_record,
                    continuation_cause=continuation,
                )
        # Only a fresh wake admission (watcher, lifecycle, or mail) takes the
        # exact-wake launcher.  A retry or resume keeps its parent's wake_cause for
        # the turn's input but reuses the paid allocation, which the wake validator
        # rejects by design.
        try:
            if auto_research_wake_admission is not None or auto_research_mail_delivery is not None:
                assert isinstance(request, AutoResearchRunRequest)
                return ensure_auto_research_wake_spawned(
                    self,
                    request.episode_id,
                    operation_id=record.operation_id,
                )
            return self.launch_admitted(record.operation_id)
        except Exception as exc:
            # This call committed the row, so it alone can say why no worker
            # started; a queued row with no dispatch receipt is otherwise mute.
            logger.warning(
                "Admitted task %s (%s) failed to launch: %s", record.operation_id, kind, exc
            )
            with suppress(Exception):
                self.store.record_agent_task_receipt(
                    record.operation_id,
                    "operation_launch_failed_after_admission",
                    {"exception_type": type(exc).__name__, "detail": str(exc)[:2000]},
                    tier="diagnostic",
                )
            raise

    def launch_admitted(self, operation_id: str) -> AgentTaskRecord:
        """Launch one task whose durable admission already committed.

        Admission and provider dispatch are separate durability boundaries.  The
        caller therefore supplies only the operation identity: the request,
        continuation cause, parent, and launch bindings all come back from the
        durable row and its admission receipt.  This is also the startup repair
        seam for a task that was admitted before the process disappeared.
        """

        self._require_startup_effects_open("provider task launch")
        record = self._require_operation(operation_id)
        with self._controls_lock:
            if self._shutdown_requested or operation_id in self._workers:
                return self._require_operation(operation_id)
        if record.status != "queued":
            return record

        try:
            request = self._request_from_record(record)
            self._validate_request_type(record.kind, request)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "The admitted task has no valid persisted request for its kind."
            ) from exc
        if request.model_dump(mode="json") != record.request:
            raise ValueError("The admitted task request failed its persisted roundtrip.")

        try:
            self.admit_provider_task(
                record.project_id,
                request,
                execution_host=(record.stage_host or "") if record.stage_root else None,
            )
        except ProviderSignedOut:
            return record

        intent = self.store.agent_task_admission_intent(operation_id)
        if intent is None:
            raise ValueError("The admitted task has no durable admission intent.")
        cause = intent.get("continuation_cause")
        if not isinstance(cause, str) or cause not in _AGENT_TASK_CONTINUATIONS:
            raise ValueError("The admitted task has no valid continuation cause.")
        intent_parent = intent.get("parent_operation_id")
        if "parent_operation_id" in intent:
            if intent_parent != record.parent_operation_id:
                raise ValueError("The admission intent changed its exact parent operation.")
        elif intent.get("has_parent") != (record.parent_operation_id is not None):
            raise ValueError("The legacy admission intent changed its parent presence.")

        parent = None
        if record.parent_operation_id is not None:
            parent = self.store.agent_task(record.parent_operation_id)
            if parent is None:
                raise ValueError("The admitted task lost its exact persisted parent.")

        continuation = cast(AgentTaskContinuation, cause)
        self._validate_launch_admission(
            record,
            request,
            parent=parent,
        )

        # The proof can race another in-process launcher.  Re-check the registry
        # after a negative proof so a claimed or already-advanced row is treated
        # as an idempotent duplicate rather than as an ambiguous dispatch.
        if not self.store.agent_task_dispatch_was_proven_not_started(operation_id):
            latest = self._require_operation(operation_id)
            with self._controls_lock:
                if operation_id in self._workers:
                    return self._require_operation(operation_id)
            if latest.status != "queued":
                return latest
            raise ValueError(
                "The admitted task has an ambiguous or already-started dispatch attempt."
            )

        return self._spawn_record(
            record,
            request,
            continuation=continuation,
            parent=parent,
        )

    def _validate_launch_admission(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        *,
        parent: AgentTaskRecord | None,
    ) -> None:
        """Validate immutable bindings before the first dispatch receipt."""

        if record.authorized_by is None or not record.authorized_by.display_name.strip():
            raise ValueError("The admitted task lost its human authorizer snapshot.")
        if record.native_session_id != request.session_id:
            raise ValueError("The admitted task request and native session do not agree.")
        if request.provider:
            require_runtime_id(request.provider, record.runtime_id)
        elif record.runtime_id:
            raise ValueError("The admitted task has a runtime without a provider.")
        if record.stage_host is not None and record.stage_root is None:
            raise ValueError("The admitted task has an incoherent execution stage binding.")
        if record.stage_root is not None and not record.stage_root.strip():
            raise ValueError("The admitted task has an empty execution stage root.")
        if record.write_scope_fingerprint is not None:
            raise ValueError("A queued admitted task cannot already carry a write-scope binding.")

        if record.kind == "episode_report":
            if record.dispatch_authority is not None:
                raise ValueError("An episode report task cannot carry dispatch authority.")
        else:
            if record.dispatch_authority is None:
                raise ValueError("The admitted task has no dispatch authority.")
            require_dispatch(record.dispatch_authority)

        request_episode_id = (
            request.episode_id
            if isinstance(
                request,
                (AutoResearchRunRequest, BranchMergeRunRequest, EpisodeReportRunRequest),
            )
            else request.control_episode_id
            if isinstance(request, RunRequest) and request.patch_kind == "experiment_loop"
            else None
        )
        if request_episode_id is not None and request_episode_id != record.episode_id:
            raise ValueError("The admitted task request changed its exact episode identity.")
        self.store.validate_agent_task_graph_target(record)

        expected_parent = record.parent_operation_id
        if (expected_parent is None) != (parent is None):
            raise ValueError("The admitted task changed its parent presence.")
        if parent is not None:
            if expected_parent != parent.operation_id:
                raise ValueError("The admitted task changed its exact parent operation.")
            if parent.project_id != record.project_id or parent.graph_target != record.graph_target:
                raise ValueError("The admitted task changed its parent project or graph target.")

    def _spawn_record(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        *,
        continuation: AgentTaskContinuation,
        parent: AgentTaskRecord | None = None,
    ) -> AgentTaskRecord:
        operation_id = record.operation_id
        with self._controls_lock:
            # Shutdown closes this same registry before taking its pause
            # snapshot. Late admissions stay queued for startup recovery.
            if self._shutdown_requested or operation_id in self._workers:
                return self._require_operation(operation_id)
            current = self._validated_spawn_record(record, request, parent=parent)
            if current.status != "queued":
                return current
            control = AgentProcessControl()
            worker = threading.Thread(
                target=self._run,
                args=(current, request, control, continuation),
                name=f"rcp-{current.kind}-{operation_id[:8]}",
                daemon=True,
            )
            # Registry membership is the one in-process dispatch claim.  It is
            # installed before any observable launch work so concurrent command
            # reconciliation cannot create a second thread for the same row.
            self._controls[operation_id] = control
            self._workers[operation_id] = worker
            dispatch_attempt_id = str(uuid.uuid4())
            try:
                self.store.record_agent_task_receipt(
                    operation_id,
                    "operation_dispatch_attempt",
                    {"dispatch_attempt_id": dispatch_attempt_id},
                    tier="diagnostic",
                )
                self._record_spawn_dispatch(
                    current,
                    request,
                    continuation=continuation,
                    parent=parent,
                )
                worker.start()
            except Exception:
                with suppress(Exception):
                    self.store.record_agent_task_receipt(
                        operation_id,
                        "operation_dispatch_failed_before_start",
                        {"dispatch_attempt_id": dispatch_attempt_id},
                        tier="diagnostic",
                    )
                if self._workers.get(operation_id) is worker:
                    self._controls.pop(operation_id, None)
                    self._workers.pop(operation_id, None)
                raise
            with suppress(Exception):
                self.store.record_agent_task_receipt(
                    operation_id,
                    "operation_dispatch_started",
                    {"dispatch_attempt_id": dispatch_attempt_id},
                    tier="diagnostic",
                )
        return current

    def _validated_spawn_record(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        *,
        parent: AgentTaskRecord | None,
    ) -> AgentTaskRecord:
        current = self._require_operation(record.operation_id)
        if (
            current.project_id != record.project_id
            or current.episode_id != record.episode_id
            or current.graph_target != record.graph_target
            or current.kind != record.kind
            or current.request != record.request
            or current.request != request.model_dump(mode="json")
            or current.attempt != record.attempt
            or current.parent_operation_id != record.parent_operation_id
            or current.runtime_id != record.runtime_id
            or (parent is None) != (current.parent_operation_id is None)
            or (parent is not None and current.parent_operation_id != parent.operation_id)
            or current.native_session_id != record.native_session_id
            or current.stage_host != record.stage_host
            or current.stage_root != record.stage_root
            or current.write_scope_fingerprint != record.write_scope_fingerprint
            or current.authorized_by != record.authorized_by
            or current.dispatch_authority != record.dispatch_authority
        ):
            raise ValueError("The committed task changed before background dispatch.")
        try:
            current_request = self._request_from_record(current)
            self._validate_request_type(current.kind, current_request)
        except (TypeError, ValueError) as exc:
            raise ValueError("The committed task lost its persisted request contract.") from exc
        if current_request.model_dump(mode="json") != current.request:
            raise ValueError("The committed task request failed its persisted roundtrip.")
        return current

    def _record_spawn_dispatch(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        *,
        continuation: AgentTaskContinuation,
        parent: AgentTaskRecord | None,
    ) -> None:
        operation_id = record.operation_id
        reuses_native_checkpoint = continuation in _NATIVE_CHECKPOINT_CONTINUATIONS
        already_recorded = any(
            receipt.category == "operation_created"
            for receipt in self.store.agent_task_receipts(operation_id)
        )
        if already_recorded:
            return
        self.store.record_agent_task_receipt(
            operation_id,
            "operation_created",
            {
                "kind": record.kind,
                "attempt": record.attempt,
                "has_parent": parent is not None,
                "continuation_cause": continuation,
                "resumed": reuses_native_checkpoint,
            },
        )
        if (
            parent
            and isinstance(request, AutoResearchRunRequest)
            and continuation not in {"resume", "retry", "handoff", "graph_repair"}
        ):
            label = {
                "fresh": f"Auto-research {request.role} turn",
                "watcher_wake": "Auto-research watcher wake",
                "graph_condition_wake": "Auto-research graph-condition wake",
                "message_wake": "Auto-research message wake",
                "lifecycle_wake": "Auto-research lifecycle wake",
                "auto_research_continuation": "Auto-research human-authorized continuation",
            }[continuation]
            self.store.record_agent_task_event(
                operation_id,
                f"{label} queued from task {parent.operation_id[:8]}.",
            )
        elif parent and isinstance(request, EpisodeReportRunRequest):
            self.store.record_agent_task_event(
                operation_id,
                "Wrapping up visualization and report",
            )
        elif parent:
            action = (
                "Repairing the graph update from"
                if continuation == "graph_repair"
                else "Resuming"
                if continuation == "resume"
                else "Retrying"
            )
            feedback = "" if continuation == "resume" else " with prior failure diagnostics"
            self.store.record_agent_task_event(
                operation_id,
                f"{action} task {parent.operation_id[:8]} as attempt {record.attempt}{feedback}.",
            )
        elif (
            isinstance(request, RunRequest)
            and bool(request.watcher_ids)
            and request.trigger in {"watcher", "experiment_run"}
        ):
            self.store.record_agent_task_receipt(
                operation_id,
                "watcher_notification",
                {"watcher_ids": request.watcher_ids},
            )
            event = (
                "Pending watcher completion reauthorized by human Run."
                if request.trigger == "experiment_run"
                else "Watcher completion queued."
            )
            self.store.record_agent_task_event(operation_id, event)
        else:
            self.store.record_agent_task_event(operation_id, "Agent task queued.")

    def _run(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        control: AgentProcessControl,
        continuation: AgentTaskContinuation,
    ) -> None:
        operation_id = record.operation_id
        current = self.store.agent_task(operation_id)
        if current is None:
            self._forget_control(operation_id)
            return
        # Admission may have inherited a durable conversation-stage binding.
        # Launch only from that stored record, never the caller's pre-insert model.
        record = current
        # A durable Pause can win after the initial read. Only the atomic
        # queued-to-running claim grants dispatch; a refused claim follows the
        # same pause settlement path without entering the provider stream.
        dispatch_claimed = (
            current.status != "pausing"
            and not control.pause_requested.is_set()
            and self.store.mark_agent_task_running(operation_id)
        )
        if not dispatch_claimed:
            self.store.pause_agent_task(operation_id)
            execution = AgentTaskExecution(
                operation_id=operation_id,
                store=self.store,
                control=control,
                runtime_id=record.runtime_id,
                stage_host=record.stage_host,
                stage_root=record.stage_root,
                write_scope_fingerprint=record.write_scope_fingerprint,
                continuation=continuation,
            )
            try:
                self._task_settled(record, request, execution)
            finally:
                self._forget_control(operation_id)
            return
        continuation = experiment_rerun_continuation(self, record, request, continuation)
        execution = AgentTaskExecution(
            operation_id=operation_id,
            store=self.store,
            control=control,
            runtime_id=record.runtime_id,
            stage_host=record.stage_host,
            stage_root=record.stage_root,
            write_scope_fingerprint=record.write_scope_fingerprint,
            continuation=continuation,
            retry_feedback=(
                self._retry_feedback(record) if continuation in {"retry", "handoff"} else ()
            ),
        )
        awaiting_remote_result = False
        try:
            try:
                outcome = asyncio.run(
                    self._consume(record.project_id, record.kind, request, execution)
                )
            finally:
                self._stream_closed(record, request, execution)
        except TaskPaused as exc:
            result: dict[str, object] | None = None
            if exc.messages or exc.artifacts:
                result = {"messages": exc.messages}
                if exc.artifacts:
                    result["artifacts"] = [item.model_dump(mode="json") for item in exc.artifacts]
            self.store.pause_agent_task(
                operation_id,
                detail=str(exc) or None,
                result=result,
            )
        except TaskAwaitingRemoteResult as exc:
            awaiting_remote_result = True
            self.store.update_agent_task_message(
                operation_id,
                str(exc),
                phase="awaiting_remote_result",
                event=True,
            )
            self._schedule_remote_reconciliation(delay=0)
        except Exception as exc:  # The persisted task is the API error boundary.
            if isinstance(exc, StateUnreachable):
                # A stage checkpoint or context read that could not reach the
                # host escapes here untyped otherwise, and the classifier below
                # would read it as an ordinary failure. Only ssh's own 255 is
                # a lost link; anything the host answered is not.
                execution.stage_unreachable = True
            if (
                isinstance(request, AutoResearchRunRequest)
                and request.role == "orchestrator"
                and isinstance(exc, AutoResearchOrchestratorTerminalFailure)
            ):
                record_structural_failure(
                    self,
                    operation_id=operation_id,
                    diagnostic=str(exc),
                )
            elif (
                isinstance(request, EpisodeReportRunRequest)
                or (isinstance(request, AutoResearchRunRequest) and request.role == "orchestrator")
            ) and isinstance(exc, TaskFailed):
                self.store.record_agent_task_receipt(
                    operation_id,
                    "provider_terminal_error",
                    {
                        "provider": request.provider,
                        "classification": classify_terminal_error(str(exc)),
                    },
                    tier="diagnostic",
                )
            self.store.record_agent_task_receipt(
                operation_id,
                "operation_exception",
                {"exception_type": type(exc).__name__},
                tier="diagnostic",
            )
            partial = exc.messages if isinstance(exc, TaskFailed) else []
            artifacts = exc.artifacts if isinstance(exc, TaskFailed) else []
            result: dict[str, object] = {"messages": partial}
            if artifacts:
                result["artifacts"] = [item.model_dump(mode="json") for item in artifacts]
            if isinstance(exc, TaskFailed):
                # The one call from the general engine into one job type's
                # policy, kept on purpose.  It fires after a provider failure
                # deep inside a running worker, so there is no caller to invert.
                # Replacing it with a generic failure event that Experiment
                # policy subscribes to would be a dispatch registry under
                # another name, and would hide the behaviour rather than
                # decouple it.  One honest named call is the better trade —
                # which is why the callee moved out and this call did not.
                record_bound_experiment_session_limit(self, record, request, str(exc))
            current = self.store.agent_task(operation_id)
            report_already_finalized = (
                isinstance(request, EpisodeReportRunRequest)
                and current is not None
                and current.status in {"succeeded", "failed"}
            )
            if not report_already_finalized:
                failure_kind = self._failure_kind(operation_id, request, execution, str(exc))
                # The journal's only record that this turn failed. RCP's own
                # classification and the exception type, never the error text:
                # that is provider output and can carry token-shaped values.
                logger.warning(
                    "task failed operation=%s kind=%s host=%s failure_kind=%s exception=%s",
                    operation_id,
                    record.kind,
                    execution.stage_host or "local",
                    failure_kind or "-",
                    type(exc).__name__,
                )
                self.store.fail_agent_task(
                    operation_id,
                    str(exc),
                    result=result if partial or artifacts else None,
                    failure_kind=failure_kind,
                )
        else:
            self._complete_task_outcome(record, request, execution, outcome)
        finally:
            try:
                if isinstance(request, RunRequest) and request.patch_kind == "experiment_loop":
                    self.store.settle_ready_experiment_loop_stops()
            finally:
                try:
                    if not awaiting_remote_result:
                        self._task_settled(record, request, execution)
                finally:
                    self._forget_control(operation_id)

    def _stream_closed(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        execution: AgentTaskExecution,
    ) -> None:
        if self.on_stream_closed is None:
            return
        try:
            self.on_stream_closed(record.project_id, record.kind, request, execution)
        except Exception as exc:
            # An observer must never replace the stream's actual paused, failed,
            # or completed verdict.
            with suppress(Exception):
                self.store.record_agent_task_receipt(
                    execution.operation_id,
                    "stream_closed_callback_failed",
                    {"exception_type": type(exc).__name__},
                    tier="diagnostic",
                )

    def _complete_task_outcome(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        execution: AgentTaskExecution,
        outcome: AgentTaskOutcome,
        *,
        remote_pid_file: str | None = None,
    ) -> None:
        """Commit one consumed stream, live or recorded, to its original task."""

        operation_id = record.operation_id
        # Only ingest runs owe a graph revision. A chat turn answers a
        # question; changing the graph is the exception, not the contract.
        if record.kind in {"seed", "refresh"} and outcome.applied_revision is None:
            if execution.control.pause_requested.is_set():
                self.store.pause_agent_task(operation_id)
            else:
                self.store.record_agent_task_receipt(
                    operation_id,
                    "missing_applied_revision",
                    {"agent_stream_completed": True},
                    tier="diagnostic",
                )
                self.store.fail_agent_task(
                    operation_id,
                    "The agent stopped without applying a graph revision.",
                    remote_pid_file=remote_pid_file,
                )
            return
        result: dict[str, object] = {"messages": outcome.messages}
        if outcome.artifacts:
            result["artifacts"] = [item.model_dump(mode="json") for item in outcome.artifacts]
        if outcome.graph_update is not None:
            result["graph_update"] = outcome.graph_update.model_dump(mode="json")
        if outcome.graph_updates:
            result["graph_updates"] = [
                item.model_dump(mode="json") for item in outcome.graph_updates
            ]
        current = self.store.agent_task(operation_id)
        report_already_finalized = (
            isinstance(request, EpisodeReportRunRequest)
            and current is not None
            and current.status in {"succeeded", "failed"}
        )
        if not report_already_finalized:
            self.store.complete_agent_task(
                operation_id,
                applied_revision=outcome.applied_revision,
                result=result,
                remote_pid_file=remote_pid_file,
            )

    def _bound_execution_host(self, operation_id: str, request: AgentTaskRequest) -> str:
        """The host a request runs on, or "" when it is local or cannot be resolved."""

        run_on = getattr(request, "run_on", None)
        if run_on in {None, "local"}:
            return ""
        record = self.store.agent_task(operation_id)
        project = self.store.project(record.project_id) if record is not None else None
        if project is None:
            return ""
        try:
            return provider_login_host(load_manifest(project.locator), run_on)
        except (OSError, ValueError, KeyError):
            return ""

    def _failure_kind(
        self,
        operation_id: str,
        request: AgentTaskRequest,
        execution: AgentTaskExecution,
        error: str,
    ) -> AgentFailureKind | None:
        """Name this failure so recovery can offer the right next step."""

        provider = request.provider
        profile = None
        if isinstance(provider, str) and provider:
            with suppress(ValueError, KeyError):
                profile = profile_for(provider)
        exit = self.store.agent_task_provider_exit(operation_id)
        kind = classify_agent_failure(
            error=error,
            return_code=exit.return_code if exit is not None else None,
            # A stage that never opened checkpointed no host; the turn was
            # still bound to one, and a link lost opening the stage is on it.
            host=execution.stage_host or self._bound_execution_host(operation_id, request),
            profile=profile,
            provider_spoke_for_itself=exit is not None and exit.spoke_for_itself,
            link_lost_before_provider=exit is None and execution.stage_unreachable,
        )
        if kind == "provider_auth" and provider:
            host = execution.stage_host or ""
            record_provider_failure(
                self.store,
                provider,
                host,
                generation=execution.login_generation,
                evidence=error,
                source="turn",
            )
            state = self.store.provider_login_state(provider, host)
            if state.state == "signed_in" and state.generation > execution.login_generation:
                # The startup gate is released once the provider speaks, so a member
                # can verify the account before this turn reports the old login's
                # death. The store already ignored that stale failure; the task must
                # not be parked behind a sign-in nobody needs to repeat. It fails as
                # an ordinary provider error and recovery retries it.
                kind = None
        return kind

    def _schedule_remote_reconciliation(self, *, delay: float) -> None:
        """Schedule one bounded pass over original tasks waiting on host journals."""

        if self.recorded_stream is None:
            return

        def run() -> None:
            with self._controls_lock:
                if self._remote_reconciliation_timer is timer:
                    self._remote_reconciliation_timer = None
                if self._shutdown_requested:
                    return
                self._remote_reconciliation_worker = threading.current_thread()
            retry = False
            try:
                self._require_startup_effects_open("remote result reconciliation")
                retry = self._reconcile_remote_results()
            except MaintenanceAdmissionClosed:
                retry = True
            except Exception:
                logger.exception("Remote result reconciliation failed")
                retry = True
            finally:
                with self._controls_lock:
                    self._remote_reconciliation_worker = None
                    retry = retry or self._remote_reconciliation_requested
                    self._remote_reconciliation_requested = False
            if retry:
                self._schedule_remote_reconciliation(
                    delay=REMOTE_RESULT_RECONCILIATION_INTERVAL_SECONDS
                )

        timer = threading.Timer(delay, run)
        timer.daemon = True
        with self._controls_lock:
            if self._shutdown_requested or self._remote_reconciliation_timer is not None:
                return
            if self._remote_reconciliation_worker is not None:
                self._remote_reconciliation_requested = True
                return
            self._remote_reconciliation_timer = timer
        timer.start()

    def _reconcile_remote_results(self) -> bool:
        """Advance every host-journalled pass that has no live local consumer."""

        # Import lazily: the owner table imports Work, whose runtime types import
        # this module. Background owns scheduling, not owner registration.
        from rcp.runs.remote_finalization import plan_remote_reconciliation

        retry = False
        for waiting in plan_remote_reconciliation(self.store):
            decision = waiting.reconciliation
            if decision.action == "wait":
                retry = True
                continue
            if decision.action == "settled" or not waiting.actionable:
                continue
            with self._remote_result_lock:
                if not self.store.claim_recorded_finalization(waiting.record.operation_id):
                    continue

            try:
                record = self._require_operation(waiting.record.operation_id)
                request = self._request_from_record(record)
                continuation = (
                    self.store.agent_task_continuation_cause(record.operation_id) or "fresh"
                )
                if continuation not in _AGENT_TASK_CONTINUATIONS:
                    continuation = "fresh"
                execution = AgentTaskExecution(
                    operation_id=record.operation_id,
                    store=self.store,
                    control=AgentProcessControl(),
                    runtime_id=record.runtime_id,
                    stage_host=record.stage_host,
                    stage_root=record.stage_root,
                    write_scope_fingerprint=record.write_scope_fingerprint,
                    continuation=cast(AgentTaskContinuation, continuation),
                )
                pid_file = decision.pid_file
                assert pid_file is not None
                if decision.action == "fail":
                    self.store.fail_agent_task(
                        record.operation_id,
                        decision.reason,
                        remote_pid_file=pid_file,
                    )
            except Exception:
                self.store.release_recorded_finalization(waiting.record.operation_id)
                raise
            if decision.action == "fail":
                self._task_settled(record, request, execution)
                continue

            assert decision.recorded is not None
            assert self.recorded_stream is not None
            try:
                source = self.recorded_stream(
                    record.project_id,
                    record.kind,
                    request,
                    execution,
                    decision.recorded,
                )
                outcome = asyncio.run(
                    self._consume(
                        record.project_id,
                        record.kind,
                        request,
                        execution,
                        source=source,
                        recorded=True,
                    )
                )
                self._complete_task_outcome(
                    record,
                    request,
                    execution,
                    outcome,
                    remote_pid_file=pid_file,
                )
            except TaskPaused:
                self.store.release_recorded_finalization(record.operation_id)
                retry = True
                continue
            except StateMissing as exc:
                # The host answered: this stage is gone, replaced, or not ours.
                # Waiting for it to answer differently is waiting forever, so
                # the turn it belonged to fails for a human to see.
                self.store.fail_agent_task(record.operation_id, str(exc), remote_pid_file=pid_file)
                self._task_settled(record, request, execution)
                continue
            except StateUnavailable:
                # The host answered a moment ago and cannot be reached now.
                # That says nothing about the pass, which is journalled and
                # intact, so this waits like any other unreachable host rather
                # than settling an untouched result as failed.
                self.store.release_recorded_finalization(record.operation_id)
                retry = True
                continue
            except TaskFailed as exc:
                if execution.stage_unreachable:
                    # This failure is the outage, not a verdict: a stage read
                    # during settlement could not reach the host and settlement
                    # reported it the way it reports a deliverable the agent
                    # botched. A journalled provider error stays a real failure,
                    # even if the host goes away immediately afterwards.
                    self.store.release_recorded_finalization(record.operation_id)
                    retry = True
                    continue
                result: dict[str, object] | None = None
                if exc.messages or exc.artifacts:
                    result = {"messages": exc.messages}
                    if exc.artifacts:
                        result["artifacts"] = [
                            item.model_dump(mode="json") for item in exc.artifacts
                        ]
                self.store.fail_agent_task(
                    record.operation_id,
                    str(exc),
                    result=result,
                    remote_pid_file=pid_file,
                )
            except Exception as exc:
                self.store.record_agent_task_receipt(
                    record.operation_id,
                    "recorded_finalization_exception",
                    {"exception_type": type(exc).__name__},
                    tier="diagnostic",
                )
                self.store.fail_agent_task(
                    record.operation_id,
                    str(exc),
                    remote_pid_file=pid_file,
                )
            finally:
                self._stream_closed(record, request, execution)
            self._task_settled(record, request, execution)
        return retry

    def _transport_retry_attempt(self, record: AgentTaskRecord) -> int:
        """How many times this lineage has already been reattempted for a lost link.

        A wait that ended in a refused admission admits no child, so the lineage
        cannot carry it. Its receipt can, and must: without it a restart would
        recompute this as zero and hand the turn the first, shortest wait again,
        so repeated restarts could reattempt without bound.
        """

        attempts = sum(
            receipt.category == "transport_auto_retry_failed"
            for receipt in self.store.agent_task_receipts(record.operation_id)
        )
        parent = record.parent_operation_id
        while parent and attempts <= AGENT_TRANSPORT_RETRY_LIMIT:
            if not self.store.agent_task_has_receipt(parent, "transport_auto_retry"):
                break
            attempts += 1
            ancestor = self.store.agent_task(parent)
            parent = ancestor.parent_operation_id if ancestor is not None else None
        return attempts

    def _auto_retry_transport_loss(self, record: AgentTaskRecord) -> None:
        """Reattempt a turn whose link died, a bounded number of times.

        The work is not what failed. A run keeps its own SSH connection, so the
        blame is narrowed to this run, but a network change still ends it for a
        reason it had no part in. A human pressing Retry is the same call, so
        this reuses it rather than growing a second recovery path.
        """

        settled = self.store.agent_task(record.operation_id)
        if settled is None or settled.failure_kind != "transport_lost" or not settled.can_retry:
            return
        attempt = self._transport_retry_attempt(settled)
        if attempt >= AGENT_TRANSPORT_RETRY_LIMIT:
            self.store.record_agent_task_receipt(
                settled.operation_id,
                "transport_auto_retry_exhausted",
                {"attempts": attempt},
                tier="summary",
            )
            return
        self.store.record_agent_task_receipt(
            settled.operation_id,
            "transport_auto_retry",
            {
                "attempt": attempt + 1,
                "delay_seconds": AGENT_TRANSPORT_RETRY_BACKOFF_SECONDS[attempt],
            },
            tier="summary",
        )
        self._schedule_transport_retry(settled.operation_id, attempt=attempt)

    def _schedule_transport_retry(
        self,
        operation_id: str,
        *,
        attempt: int,
        delay: float | None = None,
    ) -> None:
        if delay is None:
            delay = AGENT_TRANSPORT_RETRY_BACKOFF_SECONDS[attempt]

        def run() -> None:
            try:
                self._run_transport_retry(operation_id, attempt=attempt)
            finally:
                with self._controls_lock:
                    if timer in self._transport_retry_timers:
                        self._transport_retry_timers.remove(timer)

        timer = threading.Timer(delay, run)
        timer.daemon = True
        with self._controls_lock:
            if self._shutdown_requested or self._transport_retry_closed:
                return
            self._transport_retry_timers.append(timer)
        timer.start()

    def _run_transport_retry(self, operation_id: str, *, attempt: int) -> None:
        """Fire one armed reattempt: the body of its timer, fenced against shutdown."""

        with self._transport_retry_fence:
            if self._shutdown_requested or self._transport_retry_closed:
                return
            # From here until the child has a worker, shutdown waits for us.
            self._transport_retry_admissions += 1
        try:
            if self._transport_retry_superseded(operation_id):
                return
            wait = seconds_until_automatic_launch()
            if wait > 0:
                # The machine only just woke, likely for a few seconds, and a
                # launch started now would lose its link the same way. The
                # attempt is not spent; it waits for a wake long enough to finish.
                self._schedule_transport_retry(operation_id, attempt=attempt, delay=wait)
                return
            try:
                self.retry(
                    operation_id,
                    authorized_by=self.store.agent_task_authorizer(operation_id),
                )
            except AgentTaskAlreadyContinued:
                # The check above and this admission are not one transaction;
                # the claim inside admission is. Something else took the turn
                # over in between, so this stands down exactly as if the check
                # had seen it.
                with suppress(Exception):
                    self.store.record_agent_task_receipt(
                        operation_id,
                        "transport_auto_retry_superseded",
                        {"reason": "another attempt already took this turn over"},
                        tier="summary",
                    )
            except Exception as exc:
                # The human still has Retry; a failed reattempt must not
                # become a second failure report on top of the one they
                # already have.
                with suppress(Exception):
                    self.store.record_agent_task_receipt(
                        operation_id,
                        "transport_auto_retry_failed",
                        {"exception_type": type(exc).__name__},
                        tier="diagnostic",
                    )
                # A host that is still rebooting refuses admission too, and
                # that is the case the later, longer waits exist for. No
                # child was admitted, so the receipt chain cannot carry the
                # count and this hands it to the next wait directly.
                if attempt + 1 < AGENT_TRANSPORT_RETRY_LIMIT:
                    with suppress(Exception):
                        self._schedule_transport_retry(operation_id, attempt=attempt + 1)
                else:
                    with suppress(Exception):
                        self.store.record_agent_task_receipt(
                            operation_id,
                            "transport_auto_retry_exhausted",
                            {"attempts": attempt + 1},
                            tier="summary",
                        )
        finally:
            with self._transport_retry_fence:
                self._transport_retry_admissions -= 1
                self._transport_retry_fence.notify_all()

    def _rearm_owed_transport_retries(self) -> None:
        """Re-arm reattempts a previous process promised and could not keep.

        The receipt that promises one is durable; the wait is a timer that dies
        with the process. Without this, stopping RCP during a wait turns an
        automatic reattempt into a turn that stays failed until a human notices.
        The wait starts over rather than resuming, because how much of it had
        already elapsed was never written down.
        """

        for operation_id in self.store.owed_transport_retry_operation_ids():
            record = self.store.agent_task(operation_id)
            if record is None or not record.can_retry:
                continue
            attempt = self._transport_retry_attempt(record)
            if attempt >= AGENT_TRANSPORT_RETRY_LIMIT:
                continue
            self._schedule_transport_retry(operation_id, attempt=attempt)

    def _transport_retry_superseded(self, operation_id: str) -> bool:
        """Whether this turn was already taken over while the wait ran.

        A human pressing Retry, a recovery owner, or a second timer all leave a
        child on the failed task. Firing anyway would run the turn a second time
        after the first already finished, repeating whatever it did. This read
        is the cheap early exit; the claim that closes the remaining window is
        admission itself, which refuses a second recovery child of one parent
        inside the transaction that would insert it.
        """

        settled = self.store.agent_task(operation_id)
        superseded = (
            settled is None
            or not settled.can_retry
            or self.store.agent_task_has_continuation(operation_id)
        )
        if superseded:
            with suppress(Exception):
                self.store.record_agent_task_receipt(
                    operation_id,
                    "transport_auto_retry_superseded",
                    {"reason": "another attempt already took this turn over"},
                    tier="summary",
                )
        return superseded

    def _task_settled(
        self,
        record: AgentTaskRecord,
        request: AgentTaskRequest,
        execution: AgentTaskExecution,
    ) -> None:
        if isinstance(request, EpisodeReportRunRequest):
            return
        try:
            self._auto_retry_transport_loss(record)
        except Exception as exc:
            with suppress(Exception):
                self.store.record_agent_task_receipt(
                    execution.operation_id,
                    "transport_auto_retry_failed",
                    {"exception_type": type(exc).__name__},
                    tier="diagnostic",
                )
        if self.on_task_settled is not None:
            try:
                self.on_task_settled(record.project_id, record.kind, request, execution)
            except Exception as exc:
                # Delivery observation runs after the task verdict and must never
                # replace it, including when the agent stream itself failed.
                with suppress(Exception):
                    self.store.record_agent_task_receipt(
                        execution.operation_id,
                        "task_settled_callback_failed",
                        {"exception_type": type(exc).__name__},
                        tier="diagnostic",
                    )

    async def _consume(
        self,
        project_id: str,
        kind: AgentTaskKind,
        request: AgentTaskRequest,
        execution: AgentTaskExecution,
        *,
        source: AsyncIterator[str] | None = None,
        recorded: bool = False,
    ) -> AgentTaskOutcome:
        applied_revision: int | None = None
        messages: list[str] = []
        artifacts: list[AgentArtifactDescriptor] = []
        graph_update: GraphUpdateResult | None = None
        graph_updates: list[GraphUpdateResult] = []
        awaiting_remote_result: str | None = None
        # `aclosing` so an error or a pause closes the run generator here rather
        # than leaving it suspended for the garbage collector: its `finally` is
        # what releases the canonical run lock and retains the scratch folder.
        frames = source if source is not None else self.stream(project_id, kind, request, execution)
        async with aclosing(frames) as stream:
            async for frame in stream:
                event = _event_from_sse(frame)
                if event.usage is not None:
                    usage_record = self.store.record_agent_usage(
                        execution.operation_id,
                        event.usage,
                        idempotent=recorded,
                    )
                    usage_receipt_exists = recorded and any(
                        receipt.category == "provider_usage"
                        and receipt.payload.get("usage_id") == usage_record.usage_id
                        for receipt in self.store.agent_task_receipts(execution.operation_id)
                    )
                    if not usage_receipt_exists:
                        self.store.record_agent_task_receipt(
                            execution.operation_id,
                            "provider_usage",
                            {
                                "usage_id": usage_record.usage_id,
                                "counted": usage_record.counted,
                                "count_reason": usage_record.count_reason,
                                "provider_profile": usage_record.provider_profile,
                                "processed_input_tokens": usage_record.processed_input_tokens,
                                "generated_tokens": usage_record.generated_tokens,
                            },
                            tier="diagnostic",
                        )
                if event.event == "remote_result_pending":
                    awaiting_remote_result = (
                        event.text
                        or "Waiting for the remote result of a turn RCP stopped watching."
                    )
                    continue
                if event.event == "error":
                    raise TaskFailed(event.text or "The agent task failed.", messages, artifacts)
                if event.event == "paused":
                    raise TaskPaused(event.text, messages, artifacts)
                if event.event == "runtime_fallback":
                    self.store.record_agent_task_receipt(
                        execution.operation_id,
                        "provider_runtime_fallback",
                        _runtime_fallback_payload(event.text),
                        tier="diagnostic",
                    )
                    continue
                if event.event == "runtime":
                    if not request.provider:
                        raise TaskFailed(
                            "The provider runtime has no admitted provider.",
                            messages,
                            artifacts,
                        )
                    try:
                        self.store.checkpoint_agent_task_runtime(
                            execution.operation_id,
                            provider=request.provider,
                            runtime_id=event.text,
                        )
                    except ValueError as exc:
                        # A requeue of this same operation can legitimately reach
                        # a different runtime than the one already recorded. That
                        # is a verdict about this task, not an internal fault.
                        raise TaskFailed(str(exc), messages, artifacts) from exc
                    execution.runtime_id = event.text
                    continue
                if event.event == "session" and event.session_id:
                    self.store.checkpoint_agent_task(
                        execution.operation_id,
                        native_session_id=event.session_id,
                    )
                    checkpoint_exists = recorded and any(
                        receipt.category == "native_agent_checkpoint"
                        and receipt.payload.get("native_session_id") == event.session_id
                        for receipt in self.store.agent_task_receipts(execution.operation_id)
                    )
                    if not checkpoint_exists:
                        self.store.record_agent_task_receipt(
                            execution.operation_id,
                            "native_agent_checkpoint",
                            {
                                "provider": request.provider,
                                "runtime_id": execution.runtime_id,
                                "run_on": request.run_on,
                                "native_session_id": event.session_id,
                                "continuation_cause": execution.continuation,
                                "resumed": execution.reuses_native_checkpoint,
                            },
                            tier="diagnostic",
                        )
                    self.store.update_agent_task_message(
                        execution.operation_id,
                        "Agent task is running.",
                        phase="agent",
                    )
                if event.event == "message":
                    revision = _applied_revision(event.text)
                    parsed_graph_updates = _graph_updates(event.text)
                    if parsed_graph_updates is not None:
                        graph_updates.extend(parsed_graph_updates)
                        graph_updates = graph_updates[-GRAPH_UPDATE_HISTORY_MAX_COUNT:]
                        if parsed_graph_updates:
                            graph_update = parsed_graph_updates[-1]
                    parsed_graph_update = _graph_update(event.text)
                    if parsed_graph_update is not None:
                        graph_update = parsed_graph_update
                    if revision is None:
                        revision_candidates = (
                            [parsed_graph_update] if parsed_graph_update is not None else []
                        ) + list(reversed(parsed_graph_updates or []))
                        revision = next(
                            (
                                update.applied_revision
                                for update in revision_candidates
                                if update.applied_revision is not None
                            ),
                            None,
                        )
                    if revision is not None:
                        applied_revision = revision
                        # A retained Experiment patch can report its historical
                        # commit id while the captured state is the current
                        # idempotent result. Keep that state and revision paired.
                        if execution.applied_graph_state is None:
                            execution.applied_revision = revision
                        self.store.update_agent_task_message(
                            execution.operation_id,
                            "Applying the graph update.",
                            phase="applying",
                            event=True,
                        )
                    elif (
                        parsed_graph_update is None
                        and parsed_graph_updates is None
                        and event.text.strip()
                        and len(messages) < 32
                    ):
                        messages.append(event.text.strip()[:16_000])
                if event.event == "answer" and event.text.strip():
                    # The final answer always survives the cap: it replaces the newest trace.
                    if len(messages) >= 32:
                        messages.pop()
                    messages.append(event.text.strip()[:16_000])
                if (
                    event.event == "artifact"
                    and event.artifact is not None
                    and len(artifacts) < CHAT_ARTIFACT_MAX_COUNT
                    and event.artifact.artifact_id not in {item.artifact_id for item in artifacts}
                ):
                    artifacts.append(event.artifact)
                if event.event == "raw" and event.text.startswith(
                    "Omitted oversized provider event"
                ):
                    self.store.record_agent_task_event(
                        execution.operation_id,
                        event.text,
                        level="warning",
                    )
                    self.store.record_agent_task_receipt(
                        execution.operation_id,
                        "provider_event_omitted",
                        {"reason": "provider_event_exceeded_stream_limit"},
                        tier="trace",
                    )
        if awaiting_remote_result is not None:
            raise TaskAwaitingRemoteResult(awaiting_remote_result)
        return AgentTaskOutcome(
            applied_revision=(
                applied_revision if applied_revision is not None else execution.applied_revision
            ),
            messages=messages,
            artifacts=artifacts,
            graph_update=graph_update,
            graph_updates=graph_updates,
        )

    def _require_operation(self, operation_id: str) -> AgentTaskRecord:
        record = self.store.agent_task(operation_id)
        if record is None:
            raise KeyError(operation_id)
        return record

    def _session_is_rcp_owned(self, record: AgentTaskRecord) -> bool:
        if record.kind in {"node_chat", "project_chat", "paper_coach"}:
            return bool(record.native_session_id)
        seen: set[str] = set()
        current = record
        while current.operation_id not in seen:
            seen.add(current.operation_id)
            request = self._request_from_record(current)
            if request.session_id is None:
                return bool(current.native_session_id)
            if current.parent_operation_id:
                parent = self.store.agent_task(current.parent_operation_id)
            else:
                parent = self._continued_session_owner(current)
            if (
                parent is None
                or parent.project_id != current.project_id
                or parent.kind != current.kind
                or parent.native_session_id != request.session_id
            ):
                return False
            current = parent
        return False

    def _continued_session_owner(self, record: AgentTaskRecord) -> AgentTaskRecord | None:
        """The source orchestrator task whose session a continuation root resumes."""

        episode = self.store.episode(record.episode_id or "")
        if episode is None or episode.continues_episode_id is None:
            return None
        source = self.store.episode(episode.continues_episode_id)
        if source is None or source.root_operation_id is None:
            return None
        binding = self.store.auto_research_actor_binding(source.root_operation_id)
        if binding is None:
            return None
        return self.store.agent_task(binding.current_operation_id)

    def _retry_feedback(self, record: AgentTaskRecord) -> tuple[str, ...]:
        feedback: list[str] = []
        seen_operations: set[str] = set()
        seen_errors: set[str] = set()
        parent_id = record.parent_operation_id
        while parent_id and parent_id not in seen_operations and len(feedback) < 3:
            seen_operations.add(parent_id)
            parent = self.store.agent_task(parent_id)
            if (
                parent is None
                or parent.project_id != record.project_id
                or parent.kind != record.kind
            ):
                break
            if parent.error:
                detail = " ".join(parent.error.split())[:1600]
                if detail and detail not in seen_errors:
                    feedback.append(
                        f"Attempt {parent.attempt} ({parent.status}) failed with: {detail}"
                    )
                    seen_errors.add(detail)
            parent_id = parent.parent_operation_id
        return tuple(feedback)

    def _failure_is_session_limit(self, record: AgentTaskRecord) -> bool:
        return self._failure_classified_as(record, "session_limit")

    def _failure_is_stale_session(self, record: AgentTaskRecord) -> bool:
        """The provider no longer holds the native session this task would resume."""

        return self._failure_classified_as(record, "stale_session")

    def _failure_classified_as(self, record: AgentTaskRecord, classification: str) -> bool:
        classified_receipt = any(
            receipt.category == "provider_terminal_error"
            and receipt.payload.get("classification") == classification
            for receipt in self.store.agent_task_receipts(record.operation_id)
        )
        return classified_receipt or (
            bool(record.error) and classify_terminal_error(record.error or "") == classification
        )

    def _continuation_context_is_unavailable(self, record: AgentTaskRecord) -> bool:
        return any(
            receipt.category == "continuation_context_unavailable"
            and receipt.payload.get("retry_required") is True
            for receipt in self.store.agent_task_receipts(record.operation_id)
        )

    @staticmethod
    def _request_from_record(record: AgentTaskRecord) -> AgentTaskRequest:
        model: type[AgentTaskRequest] = {
            "paper_coach": CoachRequest,
            "auto_research": AutoResearchRunRequest,
            "branch_merge": BranchMergeRunRequest,
            "episode_report": EpisodeReportRunRequest,
        }.get(record.kind, RunRequest)
        return load_stored_request(model, record.request, operation_id=record.operation_id)

    @staticmethod
    def _validate_request_type(kind: AgentTaskKind, request: AgentTaskRequest) -> None:
        if kind == "paper_coach" and not isinstance(request, CoachRequest):
            raise TypeError("paper_coach requires a CoachRequest")
        if kind == "auto_research" and not isinstance(request, AutoResearchRunRequest):
            raise TypeError("auto_research requires an AutoResearchRunRequest")
        if kind == "branch_merge" and not isinstance(request, BranchMergeRunRequest):
            raise TypeError("branch_merge requires a BranchMergeRunRequest")
        if kind == "episode_report" and not isinstance(request, EpisodeReportRunRequest):
            raise TypeError("episode_report requires an EpisodeReportRunRequest")
        if kind not in {
            "paper_coach",
            "auto_research",
            "branch_merge",
            "episode_report",
        } and not isinstance(request, RunRequest):
            raise TypeError(f"{kind} requires a RunRequest")

    def _forget_control(self, operation_id: str) -> None:
        with self._controls_lock:
            self._controls.pop(operation_id, None)
            self._workers.pop(operation_id, None)


def _runtime_fallback_payload(text: str) -> dict[str, object]:
    """Keep an unparsable diagnostic rather than losing why a runtime was skipped."""

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = None
    return payload if isinstance(payload, dict) else {"detail": text[:400]}


def _event_from_sse(frame: str) -> AgentEvent:
    data = next(
        (line[6:] for line in frame.splitlines() if line.startswith("data: ")),
        "",
    )
    if not data:
        raise ValueError("The background task emitted an invalid event.")
    return AgentEvent.model_validate_json(data)


def _applied_revision(text: str) -> int | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or "applied_revision" not in value:
        return None
    try:
        return int(value["applied_revision"])
    except (TypeError, ValueError):
        return None


def _graph_update(text: str) -> GraphUpdateResult | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or "graph_update" not in value:
        return None
    try:
        return GraphUpdateResult.model_validate(value["graph_update"])
    except (TypeError, ValueError):
        return None


def _graph_updates(text: str) -> list[GraphUpdateResult] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or "graph_updates" not in value:
        return None
    raw_updates = value["graph_updates"]
    if not isinstance(raw_updates, list):
        return None
    try:
        return [GraphUpdateResult.model_validate(item) for item in raw_updates]
    except (TypeError, ValueError):
        return None
