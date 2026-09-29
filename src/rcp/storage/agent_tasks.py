from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from statistics import median
from typing import Literal

from pydantic import (
    TypeAdapter,
)

from rcp.artifacts import AgentArtifactDescriptor
from rcp.core.authority import (
    AgentDispatchAuthority,
    AgentDispatchScope,
    AgentTaskAuthority,
    require_dispatch,
)
from rcp.core.models import (
    AuthorizedHuman,
)
from rcp.core.transition_models import GraphTargetRef
from rcp.limits import (
    AGENT_COMMAND_EVENT_MAX_BYTES,
    AGENT_TASK_ESTIMATE_HISTORY_LIMIT,
    AGENT_TASK_ESTIMATE_SAMPLE_LIMIT,
    AGENT_TASK_EVENT_LIST_DEFAULT_LIMIT,
    AGENT_TASK_EVENT_LIST_MAX_LIMIT,
    AGENT_TASK_EVENT_RETENTION_COUNT,
    AGENT_TASK_LIST_DEFAULT_LIMIT,
    AGENT_TASK_LIST_FINISHED_CHAT_SECONDS,
    AGENT_TASK_LIST_MAX_LIMIT,
    AGENT_TASK_LIST_OPEN_CHAT_LIMIT,
    AGENT_TASK_RECEIPT_LIST_LIMIT,
    AGENT_TASK_RECEIPT_MAX_BYTES,
    AGENT_TASK_RECEIPT_RETENTION_COUNTS,
    AGENT_TASK_RESULT_MAX_BYTES,
    CHAT_ARTIFACT_MAX_COUNT,
    GRAPH_UPDATE_HISTORY_MAX_COUNT,
    PATCH_OUTPUT_RETENTION_DAYS,
    RUN_TRACE_RETENTION_DAYS,
    WRITING_SESSION_RETENTION_DAYS,
    WRITING_SESSIONS_PER_PROJECT,
)
from rcp.providers import ProviderUsage, require_runtime_id
from rcp.storage.models import (
    ACTIVE_AGENT_TASK_STATUSES,
    AGENT_TASK_PROJECTION_FIELDS,
    AGENT_TASK_TRANSITIONS,
    AWAITING_HUMAN_AGENT_TASK_STATUSES,
    AgentFailureKind,
    AgentTaskAdmissionConflict,
    AgentTaskAlreadyContinued,
    AgentTaskContractRecord,
    AgentTaskEventRecord,
    AgentTaskKind,
    AgentTaskReceiptRecord,
    AgentTaskReceiptTier,
    AgentTaskRecord,
    AgentTaskStatus,
    AgentUsageCell,
    AgentUsageCountReason,
    AgentUsageMetric,
    AgentUsageRecord,
    AgentUsageSnapshot,
    AutoResearchRole,
    ChatSessionContextRecord,
    ProviderExit,
    RunStageLifecycleRecord,
    _canonical_uuid4,
    _required_timestamp,
    _result_view_reference_time,
)

# Ordered Apply history is a contiguous latest tail. The singular projection
# retains the detailed latest result; history entries are concise so task JSON
# remains below its existing 64 KiB storage boundary.
_GRAPH_UPDATE_HISTORY_RESERVE_BYTES = 8 * 1024

_PROTECTED_AGENT_TASK_RECEIPT_CATEGORIES = (
    "operation_admitted",
    "operation_dispatch_attempt",
    "operation_dispatch_failed_before_start",
    "operation_dispatch_started",
    "operation_dispatch_reset",
    "chat_stage_layout",
    "compute_command_started",
    "compute_command_result",
    "remote_provider_started",
    "remote_provider_stopped",
    "herdr_binding_start",
    "herdr_binding_stop",
)
_PROTECTED_AGENT_TASK_RECEIPT_PLACEHOLDERS = ", ".join(
    "?" for _category in _PROTECTED_AGENT_TASK_RECEIPT_CATEGORIES
)

_AGENT_TASK_CONTINUATION_CAUSES = frozenset(
    {
        "fresh",
        "resume",
        "retry",
        "handoff",
        "graph_repair",
        "watcher_wake",
        "graph_condition_wake",
        "message_wake",
        "lifecycle_wake",
        "auto_research_continuation",
        "episode_report",
    }
)
# An ordinary task's children are its recoveries, and the first one admitted
# takes it over: `agent_task_has_continuation` already reads any child as
# exactly that. Claiming it inside the transaction that inserts the child lets
# an automatic reattempt and a human Retry race without running the turn twice.
# Experiment and Auto-research recoveries keep their own atomic claims, because
# their lineages carry children that are not recoveries. The first graph repair
# of a Work turn has its own claimant too; a recovery of a failed repair, which
# reaches this path as `graph_repair`, is an ordinary recovery.
_EXCLUSIVE_CONTINUATION_CAUSES = frozenset({"resume", "retry", "handoff", "graph_repair"})


def _joined_repositories(aliases: Sequence[str]) -> str:
    """Name repositories the way a sentence does, not the way a tuple does."""

    names = [alias for alias in aliases if alias]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


@dataclass(frozen=True)
class _AgentTaskTransitionResult:
    outcome: Literal["applied", "refused", "missing"]
    observed_status: AgentTaskStatus | None = None


@dataclass
class _RunStageLifecycleAggregate:
    owner_refs: set[str]
    must_exist: bool = False
    protect_from_cleanup: bool = False


class AgentTaskStoreMixin:
    """Agent task lifecycle, chat sessions, usage, receipts, and pruning."""

    def agent_task_profile(self, operation_id: str) -> Literal["ordinary", "orchestrator"]:
        """Resolve the one semantic profile canonically bound to a task."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT run.operation_id, invocation.role
                FROM graph_runs AS run
                LEFT JOIN auto_research_invocations AS invocation
                  ON invocation.operation_id = run.operation_id
                WHERE run.operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return "orchestrator" if row["role"] == "orchestrator" else "ordinary"

    def create_agent_task(
        self,
        record: AgentTaskRecord,
        *,
        continuation_cause: str = "fresh",
    ) -> AgentTaskRecord:
        if record.kind == "episode_report":
            raise ValueError("episode report tasks must use their episode wrap-up allocation")
        if record.episode_id is not None:
            raise ValueError("episode tasks must spend from their episode manager atomically")
        try:
            with self.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if continuation_cause == "fresh":
                    self._require_project_accepts_new_work(connection, record.project_id)
                self._require_codex_continuation_task(connection, record)
                if self._has_active_chat_overlap(connection, record):
                    raise AgentTaskAdmissionConflict(
                        "Another task is already active in this conversation."
                    )
                if (
                    record.parent_operation_id is not None
                    and continuation_cause in _EXCLUSIVE_CONTINUATION_CAUSES
                    and connection.execute(
                        "SELECT 1 FROM graph_runs WHERE parent_operation_id = ? LIMIT 1",
                        (record.parent_operation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise AgentTaskAlreadyContinued(
                        "Another attempt already continues this task; "
                        "recover its latest attempt instead."
                    )
                self._insert_agent_task(
                    connection,
                    record,
                    continuation_cause=continuation_cause,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Could not create the agent task.") from exc
        stored = self.agent_task(record.operation_id)
        assert stored is not None
        return stored

    def create_branch_merge_task(self, record: AgentTaskRecord) -> AgentTaskRecord:
        """Admit one human-dispatched, graph-only merge without spending episode budget."""

        from rcp.runs.task_policy import task_graph_capable

        if (
            record.kind != "branch_merge"
            or record.episode_id is None
            or record.status != "queued"
            or not record.visible
            or record.parent_operation_id is not None
            or record.authorized_by is None
            or record.graph_target.kind != "branch"
        ):
            raise ValueError("a branch merge requires one visible attributed branch root task")
        authority = record.dispatch_authority
        if (
            authority is None
            or authority.profile != "orchestrator"
            or authority.task_contract != "orchestrate"
            or authority.scope.episode_id != record.episode_id
            or authority.scope.patch_kind != "work"
        ):
            raise ValueError("a branch merge requires exact graph-only orchestrator authority")
        require_dispatch(authority)
        try:
            with self.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM graph_runs WHERE operation_id = ?",
                    (record.operation_id,),
                ).fetchone()
                if existing is not None:
                    stored = self._agent_task_record(existing)
                    if stored.model_dump(exclude=AGENT_TASK_PROJECTION_FIELDS) != record.model_dump(
                        exclude=AGENT_TASK_PROJECTION_FIELDS
                    ):
                        raise ValueError("the branch merge task conflicts with its durable id")
                    return stored
                self._require_project_accepts_new_work(connection, record.project_id)
                episode = connection.execute(
                    "SELECT * FROM episodes WHERE episode_id = ?",
                    (record.episode_id,),
                ).fetchone()
                if episode is None:
                    raise KeyError(record.episode_id)
                stored_episode = self._episode_record(episode)
                if (
                    stored_episode.mode != "auto_research"
                    or stored_episode.project_id != record.project_id
                    or stored_episode.graph_target != record.graph_target
                ):
                    raise ValueError("branch merge requires its exact Auto-research episode")
                # A branch merges on branch facts: nothing about the episode's
                # status, ending, or paused turns is a condition, and merging ends
                # nothing. The only writers that matter are live graph-capable tasks.
                if any(
                    task.kind != "branch_merge"
                    and task.status in {"queued", "running", "pausing"}
                    and task_graph_capable(task.kind, task.request)
                    for task in self._unsettled_graph_target_tasks_in_connection(
                        connection, record.project_id, record.graph_target
                    )
                ):
                    raise ValueError("the graph branch still has an active writer")
                self._insert_agent_task(connection, record, continuation_cause="fresh")
        except sqlite3.IntegrityError as exc:
            raise ValueError("another merge is already active for this branch") from exc
        stored = self.agent_task(record.operation_id)
        assert stored is not None
        return stored

    def _insert_agent_task(
        self,
        connection: sqlite3.Connection,
        record: AgentTaskRecord,
        *,
        continuation_cause: str,
    ) -> None:
        if continuation_cause not in _AGENT_TASK_CONTINUATION_CAUSES:
            raise ValueError("An agent task admission has an invalid continuation cause.")
        if self._contains_legacy_lineage_key(record.request):
            raise ValueError("agent task requests must use episode_id, not campaign_id")
        self._validate_dispatch_authority_insert(connection, record)
        record = self._bind_chat_stage(connection, record)
        self._validate_experiment_task_insert(connection, record)
        self._validate_graph_target_insert(connection, record)
        self._require_graph_branch_admission_open(connection, record)
        connection.execute(
            """
            INSERT INTO graph_runs (
                operation_id, project_id, episode_id, kind, status, request_json,
                created_at, updated_at, started_at, finished_at,
                status_message, error, applied_revision, result_json, attempt,
                parent_operation_id, runtime_id, native_session_id, stage_host,
                history_only, stage_root, graph_target_json, write_scope_fingerprint,
                estimate_seconds, estimate_samples, phase,
                last_activity_at, dispatch_authority_json, authorized_space_id,
                authorized_user_id, authorized_display_name, visible
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.operation_id,
                record.project_id,
                record.episode_id,
                record.kind,
                record.status,
                json.dumps(record.request, separators=(",", ":")),
                record.created_at,
                record.updated_at,
                record.started_at,
                record.finished_at,
                record.status_message,
                record.error,
                record.applied_revision,
                self._bounded_result_json(record.result),
                record.attempt,
                record.parent_operation_id,
                record.runtime_id,
                record.native_session_id,
                record.stage_host,
                int(record.history_only),
                record.stage_root,
                record.graph_target.model_dump_json(),
                record.write_scope_fingerprint,
                record.estimate_seconds,
                record.estimate_samples,
                record.phase,
                record.last_activity_at,
                (
                    record.dispatch_authority.model_dump_json()
                    if record.dispatch_authority is not None
                    else None
                ),
                record.authorized_by.space_id if record.authorized_by is not None else None,
                record.authorized_by.user_id if record.authorized_by is not None else None,
                record.authorized_by.display_name if record.authorized_by is not None else None,
                int(record.visible),
            ),
        )
        self._insert_agent_task_receipt(
            connection,
            record.operation_id,
            "operation_admitted",
            self._bounded_receipt_payload(
                {
                    "kind": record.kind,
                    "attempt": record.attempt,
                    "parent_operation_id": record.parent_operation_id,
                    "continuation_cause": continuation_cause,
                    "admission_committed": True,
                }
            ),
            tier="summary",
            created_at=record.created_at,
        )

    def validate_agent_task_graph_target(self, record: AgentTaskRecord) -> None:
        """Recheck the same durable target contract immediately before dispatch."""

        with self.connection() as connection:
            self._validate_graph_target_insert(connection, record)

    @staticmethod
    def _validate_graph_target_insert(
        connection: sqlite3.Connection,
        record: AgentTaskRecord,
    ) -> None:
        """Bind every graph-capable continuation to its durable target."""

        if record.episode_id is None:
            if record.graph_target.kind == "branch":
                if (
                    record.kind not in {"node_chat", "project_chat"}
                    or record.request.get("patch_kind", "work") != "work"
                    or record.request.get("control_episode_id") is not None
                ):
                    raise ValueError(
                        "only an ordinary conversation may independently target a branch"
                    )
                branch = connection.execute(
                    "SELECT project_id, mode, graph_target_json FROM episodes WHERE episode_id = ?",
                    (record.graph_target.branch_id,),
                ).fetchone()
                if (
                    branch is None
                    or branch["project_id"] != record.project_id
                    or branch["mode"] != "auto_research"
                    or GraphTargetRef.model_validate_json(branch["graph_target_json"])
                    != record.graph_target
                ):
                    raise ValueError(
                        "a branch conversation requires its exact project graph branch"
                    )
        else:
            episode = connection.execute(
                "SELECT project_id, graph_target_json FROM episodes WHERE episode_id = ?",
                (record.episode_id,),
            ).fetchone()
            if episode is None:
                raise ValueError("an episode task requires its durable episode parent")
            if episode["project_id"] != record.project_id:
                raise ValueError("an episode task belongs to another project")
            if json.loads(episode["graph_target_json"])["kind"] != record.graph_target.kind or (
                json.loads(episode["graph_target_json"]).get("branch_id")
                != record.graph_target.branch_id
            ):
                raise ValueError("an episode task cannot change its graph target")

        if record.parent_operation_id is None:
            return
        parent = connection.execute(
            "SELECT graph_target_json FROM graph_runs WHERE operation_id = ?",
            (record.parent_operation_id,),
        ).fetchone()
        if parent is None:
            return
        if json.loads(parent["graph_target_json"]) != record.graph_target.model_dump(mode="json"):
            raise ValueError("a task continuation cannot change its graph target")

    @staticmethod
    def _require_graph_branch_admission_open(
        connection: sqlite3.Connection, record: AgentTaskRecord
    ) -> None:
        """Serialize new graph writers with merge while admitting read-only tasks."""

        from rcp.runs.task_policy import task_graph_capable

        if (
            record.graph_target.kind != "branch"
            or record.kind == "branch_merge"
            or not task_graph_capable(record.kind, record.request)
        ):
            return
        merging = connection.execute(
            """
            SELECT 1 FROM graph_runs
            WHERE project_id = ? AND graph_target_json = ?
              AND kind = 'branch_merge' AND status IN ('queued', 'running', 'pausing')
            LIMIT 1
            """,
            (record.project_id, record.graph_target.model_dump_json()),
        ).fetchone()
        if merging is not None:
            raise AgentTaskAdmissionConflict(
                "The graph branch is being merged. Try again after the merge settles."
            )

    @classmethod
    def _contains_legacy_lineage_key(cls, value: object) -> bool:
        if isinstance(value, dict):
            return "campaign_id" in value or any(
                cls._contains_legacy_lineage_key(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(cls._contains_legacy_lineage_key(item) for item in value)
        return False

    @staticmethod
    def _validate_dispatch_authority_insert(
        connection: sqlite3.Connection,
        record: AgentTaskRecord,
    ) -> None:
        """Keep a recovery or continuation on its parent's admitted authority."""

        if record.kind == "episode_report":
            if record.episode_id is None or record.parent_operation_id is None:
                raise ValueError(
                    "An episode report allocation requires its concluding episode task."
                )
            if record.dispatch_authority is not None:
                raise ValueError("An episode report allocation cannot carry graph authority.")
            parent = connection.execute(
                """
                SELECT run.project_id, run.episode_id
                FROM graph_runs AS run
                WHERE run.operation_id = ? AND run.episode_id = ?
                  AND run.visible = 1 AND run.kind != 'episode_report'
                """,
                (record.parent_operation_id, record.episode_id),
            ).fetchone()
            if parent is None or parent["project_id"] != record.project_id:
                raise ValueError(
                    "An episode report allocation must continue its exact concluding task."
                )
            return

        if record.kind == "auto_research":
            if record.episode_id is None:
                raise ValueError("An episode task requires its exact episode identity.")
            if (
                connection.execute(
                    "SELECT 1 FROM auto_research_episodes WHERE episode_id = ?",
                    (record.episode_id,),
                ).fetchone()
                is None
            ):
                raise ValueError("An Auto-research task requires its canonical mode state.")
            request = record.request
            role = TypeAdapter(AutoResearchRole).validate_python(request.get("role"))
            raw_actor = request.get("actor_operation_id")
            if not isinstance(raw_actor, str) or not raw_actor.strip():
                raise ValueError("An Auto-research task requires its canonical actor identity.")
            actor_operation_id = raw_actor.strip()
            is_root = record.parent_operation_id is None
            expected = AgentDispatchAuthority(
                profile="orchestrator" if role == "orchestrator" else "ordinary",
                task_contract="orchestrate" if role == "orchestrator" else "work_auto",
                scope=AgentDispatchScope(
                    run_truth_scope=sorted(set(request.get("run_truth_scope") or ())),
                    episode_id=record.episode_id,
                    patch_kind="work",
                ),
            )
            require_dispatch(expected)
            if record.dispatch_authority != expected:
                raise ValueError(
                    "An Auto-research task must carry its exact server-owned dispatch authority."
                )

            if is_root:
                if role != "orchestrator" or actor_operation_id != record.operation_id:
                    raise ValueError(
                        "An Auto-research root must be its sole canonical orchestrator actor."
                    )
                return

            parent = connection.execute(
                """
                SELECT run.*, invocation.role AS auto_research_role,
                       invocation.actor_operation_id
                FROM graph_runs AS run
                JOIN auto_research_invocations AS invocation
                  ON invocation.operation_id = run.operation_id
                WHERE run.operation_id = ? AND run.episode_id = ?
                """,
                (record.parent_operation_id, record.episode_id),
            ).fetchone()
            if (
                parent is None
                or parent["project_id"] != record.project_id
                or parent["kind"] != record.kind
            ):
                raise ValueError(
                    "An agent task continuation must preserve its parent's project and task kind."
                )

            if actor_operation_id == record.operation_id:
                parent_role = TypeAdapter(AutoResearchRole).validate_python(
                    parent["auto_research_role"]
                )
                if role != "worker" or parent_role != "orchestrator":
                    raise ValueError(
                        "Only the Auto-research orchestrator may admit a new worker actor."
                    )
                parent_json = parent["dispatch_authority_json"]
                if parent_json is None:
                    raise ValueError("A new Auto-research worker requires orchestrator authority.")
                parent_authority = AgentDispatchAuthority.model_validate_json(parent_json)
                assert record.dispatch_authority is not None
                if (
                    parent_authority.profile != "orchestrator"
                    or parent_authority.task_contract != "orchestrate"
                    or record.dispatch_authority.scope.episode_id
                    != parent_authority.scope.episode_id
                    or record.dispatch_authority.scope.run_truth_scope
                    != parent_authority.scope.run_truth_scope
                ):
                    raise ValueError("An Auto-research worker must inherit project-wide scope.")
                return

            origin = connection.execute(
                """
                SELECT run.dispatch_authority_json,
                       invocation.role AS auto_research_role
                FROM graph_runs AS run
                JOIN auto_research_invocations AS invocation
                  ON invocation.operation_id = run.operation_id
                WHERE run.operation_id = ? AND run.episode_id = ?
                """,
                (actor_operation_id, record.episode_id),
            ).fetchone()
            if origin is None:
                raise ValueError(
                    "An Auto-research continuation requires its canonical actor origin."
                )
            origin_role = TypeAdapter(AutoResearchRole).validate_python(
                origin["auto_research_role"]
            )
            if origin_role != role:
                raise ValueError(
                    "An Auto-research continuation cannot change its canonical actor role."
                )
            origin_json = origin["dispatch_authority_json"]
            if origin_json is not None:
                origin_authority = AgentDispatchAuthority.model_validate_json(origin_json)
                if record.dispatch_authority != origin_authority:
                    raise ValueError(
                        "An Auto-research continuation must preserve actor-origin authority."
                    )
                return

            # Migration-only: a same-allocation Resume/Retry of an actor recorded before
            # dispatch authority existed may bind today's closed contract. Paid continuations,
            # wakes, and reauthorization may not use this exception.
            parent_actor = parent["actor_operation_id"]
            if not (
                record.attempt == int(parent["attempt"]) + 1
                and parent_actor == actor_operation_id
                and parent["dispatch_authority_json"] is None
            ):
                raise ValueError(
                    "An Auto-research continuation cannot invent authority for an unbound actor."
                )
            return

        if record.parent_operation_id is None:
            return
        parent = connection.execute(
            """
            SELECT project_id, kind, dispatch_authority_json
            FROM graph_runs WHERE operation_id = ?
            """,
            (record.parent_operation_id,),
        ).fetchone()
        if parent is None:
            raise ValueError("An agent task continuation requires its existing parent task.")
        if parent["project_id"] != record.project_id or parent["kind"] != record.kind:
            raise ValueError(
                "An agent task continuation must preserve its parent's project and task kind."
            )
        if parent["dispatch_authority_json"] is None:
            # A task recorded before dispatch authority existed carries none. An
            # authorization that never happened cannot be invented retroactively,
            # and refusing here would strand every pre-upgrade Resume and Retry.
            # The child still resolves and gates its own binding at dispatch.
            return
        parent_authority = AgentDispatchAuthority.model_validate_json(
            parent["dispatch_authority_json"]
        )
        if record.dispatch_authority != parent_authority:
            raise ValueError(
                "An agent task continuation must preserve its parent's dispatch authority."
            )

    @staticmethod
    def _bind_chat_stage(
        connection: sqlite3.Connection,
        record: AgentTaskRecord,
    ) -> AgentTaskRecord:
        """Keep one exact scratch directory bound to a conversation.

        Every later task in the same chat inherits the prior host/root pair
        while it is inserted under the same write transaction. This makes the
        task ledger authoritative even when project identity adoption rewrites
        ``graph_runs.project_id``; a provider's saved cwd is never renamed or
        re-derived. Multiple saved pairs mean the durable conversation binding
        is already ambiguous, so continuing would risk resuming a native
        session in the wrong directory.
        """

        if record.kind not in {"node_chat", "project_chat"}:
            return record
        chat_id = record.request.get("chat_id")
        if not isinstance(chat_id, str) or not chat_id:
            return record
        prior_chat_targets = connection.execute(
            """
            SELECT DISTINCT graph_target_json
            FROM graph_runs
            WHERE project_id = ? AND kind = ?
              AND json_extract(request_json, '$.chat_id') = ?
            """,
            (record.project_id, record.kind, chat_id),
        ).fetchall()
        if any(
            GraphTargetRef.model_validate_json(row["graph_target_json"]) != record.graph_target
            for row in prior_chat_targets
        ):
            raise ValueError(
                "This conversation belongs to another graph target and cannot continue here."
            )
        # Recovery carries a server-owned stage, but must still prove that the
        # stable conversation has not moved to a different graph target.
        if record.stage_root is not None:
            return record
        session_id = record.request.get("session_id")
        watcher_ids = record.request.get("watcher_ids")
        if isinstance(session_id, str) and session_id:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(stage_host, '') AS host, stage_root AS root,
                                graph_target_json,
                                json_extract(request_json, '$.chat_id') AS chat_id
                FROM graph_runs
                WHERE project_id = ? AND kind = ?
                  AND native_session_id = ?
                """,
                (record.project_id, record.kind, session_id),
            ).fetchall()
            if any(
                GraphTargetRef.model_validate_json(row["graph_target_json"]) != record.graph_target
                or row["chat_id"] != chat_id
                for row in rows
            ):
                raise ValueError(
                    "This native session belongs to another conversation or graph target."
                )
            rows = [row for row in rows if row["root"]]
        elif (
            record.request.get("trigger") == "watcher"
            and isinstance(watcher_ids, list)
            and watcher_ids
            and all(isinstance(item, str) and item for item in watcher_ids)
        ):
            placeholders = ",".join("?" for _ in watcher_ids)
            rows = connection.execute(
                f"""
                SELECT DISTINCT COALESCE(run.stage_host, '') AS host,
                                run.stage_root AS root
                FROM watchers AS watcher
                JOIN graph_runs AS run
                  ON run.operation_id = watcher.origin_operation_id
                WHERE watcher.watcher_id IN ({placeholders})
                  AND watcher.project_id = ?
                  AND watcher.origin_task_kind = ?
                  AND watcher.chat_id = ?
                  AND run.stage_root IS NOT NULL AND run.stage_root != ''
                """,
                (*watcher_ids, record.project_id, record.kind, chat_id),
            ).fetchall()
        else:
            return record
        bindings = {(str(row["host"]), str(row["root"])) for row in rows}
        if len(bindings) > 1:
            raise ValueError(
                "This conversation has conflicting saved workspace bindings and cannot "
                "continue safely."
            )
        if not bindings:
            return record
        saved_host, saved_root = next(iter(bindings))
        return record.model_copy(
            update={"stage_host": saved_host or None, "stage_root": saved_root}
        )

    def chat_stage_layout(
        self,
        *,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        stage_host: str,
        stage_root: str,
    ) -> Literal["split-v1"] | None:
        """Return the one immutable local-chat stage-layout marker for a binding."""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT receipt.payload_json
                FROM graph_run_receipts AS receipt
                JOIN graph_runs AS run ON run.operation_id = receipt.operation_id
                WHERE receipt.category = 'chat_stage_layout'
                  AND run.project_id = ? AND run.kind = ?
                  AND json_extract(run.request_json, '$.chat_id') = ?
                  AND json_extract(receipt.payload_json, '$.stage_host') = ?
                  AND json_extract(receipt.payload_json, '$.stage_root') = ?
                ORDER BY receipt.receipt_id ASC
                """,
                (
                    project_id,
                    kind,
                    chat_id,
                    stage_host,
                    stage_root,
                ),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("The conversation stage has multiple layout markers.")
        try:
            payload = json.loads(rows[0]["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("The conversation stage layout marker is malformed.") from exc
        expected = {
            "layout": "split-v1",
            "stage_host": stage_host,
            "stage_root": stage_root,
            "workspace_root": str(PurePosixPath(stage_root) / "workspace"),
        }
        if payload != expected:
            raise ValueError("The conversation stage layout marker conflicts with its binding.")
        return "split-v1"

    def chat_stage_has_prior_binding(
        self,
        *,
        operation_id: str,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        stage_host: str,
        stage_root: str,
    ) -> bool:
        """Return whether another task durably bound this exact conversation stage."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE operation_id != ? AND project_id = ? AND kind = ?
                  AND json_extract(request_json, '$.chat_id') = ?
                  AND COALESCE(stage_host, '') = ? AND stage_root = ?
                LIMIT 1
                """,
                (operation_id, project_id, kind, chat_id, stage_host, stage_root),
            ).fetchone()
        return row is not None

    def record_chat_stage_layout(
        self,
        operation_id: str,
        *,
        stage_root: str,
        workspace_root: str,
    ) -> None:
        """Record one idempotent split-layout marker before stage checkpointing."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute(
                """
                SELECT project_id, kind, json_extract(request_json, '$.chat_id') AS chat_id
                FROM graph_runs WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if (
                task is None
                or task["kind"] not in {"node_chat", "project_chat"}
                or not task["chat_id"]
            ):
                raise ValueError("The agent task has no durable chat stage binding.")
            payload = {
                "layout": "split-v1",
                "stage_host": "",
                "stage_root": stage_root,
                "workspace_root": workspace_root,
            }
            payload_json = self._bounded_receipt_payload(payload)
            rows = connection.execute(
                """
                SELECT receipt.receipt_id, receipt.payload_json
                FROM graph_run_receipts AS receipt
                JOIN graph_runs AS run ON run.operation_id = receipt.operation_id
                WHERE receipt.category = 'chat_stage_layout'
                  AND run.project_id = ? AND run.kind = ?
                  AND json_extract(run.request_json, '$.chat_id') = ?
                  AND json_extract(receipt.payload_json, '$.stage_host') = ''
                  AND json_extract(receipt.payload_json, '$.stage_root') = ?
                ORDER BY receipt.receipt_id ASC
                """,
                (task["project_id"], task["kind"], task["chat_id"], stage_root),
            ).fetchall()
            if rows:
                if any(row["payload_json"] != payload_json for row in rows):
                    raise ValueError(
                        "The conversation stage layout marker conflicts with its stage."
                    )
                duplicate_ids = [row["receipt_id"] for row in rows[1:]]
                if duplicate_ids:
                    placeholders = ",".join("?" for _ in duplicate_ids)
                    connection.execute(
                        f"DELETE FROM graph_run_receipts WHERE receipt_id IN ({placeholders})",
                        duplicate_ids,
                    )
                return
            legacy = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE operation_id != ? AND project_id = ? AND kind = ?
                  AND json_extract(request_json, '$.chat_id') = ?
                  AND COALESCE(stage_host, '') = '' AND stage_root = ?
                LIMIT 1
                """,
                (
                    operation_id,
                    task["project_id"],
                    task["kind"],
                    task["chat_id"],
                    stage_root,
                ),
            ).fetchone()
            if legacy is not None:
                raise ValueError("A legacy conversation stage cannot acquire a split layout.")
            self._insert_agent_task_receipt(
                connection,
                operation_id,
                "chat_stage_layout",
                payload_json,
                tier="summary",
                created_at=self.now(),
            )

    @staticmethod
    def _has_active_chat_overlap(
        connection: sqlite3.Connection,
        record: AgentTaskRecord,
    ) -> bool:
        if record.kind not in {"node_chat", "project_chat"}:
            return False
        chat_id = record.request.get("chat_id")
        if not isinstance(chat_id, str) or not chat_id:
            return False
        active = connection.execute(
            """
            SELECT 1 FROM graph_runs
            WHERE project_id = ? AND kind = ?
              AND json_extract(request_json, '$.chat_id') = ?
              AND status IN ('queued', 'running', 'pausing')
            LIMIT 1
            """,
            (record.project_id, record.kind, chat_id),
        ).fetchone()
        return active is not None

    def agent_task(self, operation_id: str) -> AgentTaskRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT graph_runs.*,
                       EXISTS (
                           SELECT 1 FROM graph_run_receipts AS receipt
                           WHERE receipt.operation_id = graph_runs.operation_id
                             AND receipt.category IN (
                                 'experiment_recovery_abandoned',
                                 'auto_research_recovery_abandoned'
                             )
                       ) AS recovery_abandoned
                FROM graph_runs WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        return self._agent_task_record(row) if row else None

    def agent_task_continuation_session_id(
        self,
        project_id: str,
        operation_id: str,
    ) -> str | None:
        """Return the executable session binding for one non-historical task."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT native_session_id
                FROM graph_runs
                WHERE project_id = ? AND operation_id = ?
                  AND history_only = 0
                """,
                (project_id, operation_id),
            ).fetchone()
        if row is None or not row["native_session_id"]:
            return None
        return str(row["native_session_id"])

    @staticmethod
    def detach_agent_tasks_for_history(
        connection: sqlite3.Connection,
        operation_ids: list[str] | tuple[str, ...],
    ) -> int:
        """Fence selected terminal tasks and delete their continuation indexes.

        The caller owns the surrounding transaction so restore and import can
        combine this with their other concrete lifecycle owners atomically.
        Durable task rows keep their raw session ids as historical evidence;
        projection is what stops exporting them as executable continuations.
        """

        if not connection.in_transaction:
            raise ValueError("history-only task detachment requires an active transaction")
        selected = tuple(dict.fromkeys(operation_ids))
        if not selected:
            return 0
        if any(not isinstance(operation_id, str) or not operation_id for operation_id in selected):
            raise ValueError("history-only task identities must be non-empty strings")
        selected_json = json.dumps(selected, separators=(",", ":"))
        rows = connection.execute(
            """
            SELECT operation_id, status, native_session_id
            FROM graph_runs
            WHERE operation_id IN (SELECT value FROM json_each(?))
            """,
            (selected_json,),
        ).fetchall()
        found = {str(row["operation_id"]) for row in rows}
        missing = sorted(set(selected) - found)
        if missing:
            raise KeyError(missing[0])
        nonterminal = sorted(
            str(row["operation_id"])
            for row in rows
            if row["status"] not in {"succeeded", "failed", "interrupted"}
        )
        if nonterminal:
            raise ValueError(
                "Only terminal tasks can become history-only: " + ", ".join(nonterminal)
            )

        unresolved_revision = connection.execute(
            """
            SELECT candidate_id
            FROM artifact_revision_candidates
            WHERE status IN ('pending', 'accepting', 'conflicted')
              AND (
                source_operation_id IN (SELECT value FROM json_each(?))
                OR revision_operation_id IN (SELECT value FROM json_each(?))
              )
            LIMIT 1
            """,
            (selected_json, selected_json),
        ).fetchone()
        if unresolved_revision is not None:
            raise ValueError(
                "A task with an unresolved artifact revision cannot become history-only."
            )

        shared = connection.execute(
            """
            SELECT operation_id
            FROM graph_runs
            WHERE history_only = 0
              AND operation_id NOT IN (SELECT value FROM json_each(?))
              AND native_session_id IN (
                  SELECT native_session_id
                  FROM graph_runs
                  WHERE operation_id IN (SELECT value FROM json_each(?))
                    AND native_session_id IS NOT NULL
              )
            LIMIT 1
            """,
            (selected_json, selected_json),
        ).fetchone()
        if shared is not None:
            raise ValueError(
                "A selected task shares its native session with a task that remains live."
            )

        changed = connection.execute(
            """
            UPDATE graph_runs
            SET history_only = 1
            WHERE history_only = 0
              AND operation_id IN (SELECT value FROM json_each(?))
            """,
            (selected_json,),
        ).rowcount
        for table in ("writing_sessions", "chat_session_contexts"):
            connection.execute(
                f"""
                DELETE FROM {table}
                WHERE native_session_id IN (
                    SELECT native_session_id
                    FROM graph_runs
                    WHERE operation_id IN (SELECT value FROM json_each(?))
                      AND native_session_id IS NOT NULL
                )
                """,
                (selected_json,),
            )
        return changed

    def mark_agent_tasks_history_only(
        self,
        operation_ids: list[str] | tuple[str, ...],
    ) -> int:
        """Apply the history-only fence in one immediate transaction."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self.detach_agent_tasks_for_history(connection, operation_ids)

    def detach_agent_tasks_for_restore(
        self,
        connection: sqlite3.Connection,
        *,
        diagnostic: str,
        now: str,
    ) -> None:
        """Interrupt and fence every task captured by an offline restore."""

        if not connection.in_transaction:
            raise ValueError("restored task detachment requires an active transaction")
        detail = " ".join(diagnostic.split())[:2000]
        if not detail:
            raise ValueError("restored task detachment requires a diagnostic")
        _required_timestamp(now)
        rows = connection.execute(
            "SELECT operation_id, status FROM graph_runs ORDER BY operation_id"
        ).fetchall()
        interrupted = [
            str(row["operation_id"])
            for row in rows
            if row["status"] not in {"succeeded", "failed", "interrupted"}
        ]
        if interrupted:
            selected_json = json.dumps(interrupted, separators=(",", ":"))
            connection.execute(
                """
                UPDATE graph_runs
                SET status = 'interrupted', updated_at = ?, finished_at = COALESCE(finished_at, ?),
                    status_message = ?, error = ?, phase = 'interrupted', last_activity_at = ?
                WHERE operation_id IN (SELECT value FROM json_each(?))
                """,
                (now, now, detail, detail, now, selected_json),
            )
            for operation_id in interrupted:
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    detail,
                    level="warning",
                    created_at=now,
                )
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "operation_interrupted",
                    self._bounded_receipt_payload({"status": "interrupted", "reason": "restore"}),
                    tier="summary",
                    created_at=now,
                )
        operation_ids = tuple(str(row["operation_id"]) for row in rows)
        self.detach_agent_tasks_for_history(connection, operation_ids)

    def mark_agent_artifact_kept(
        self,
        operation_id: str,
        artifact_id: str,
        *,
        kept_filename: str,
        kept_at: str,
    ) -> AgentArtifactDescriptor:
        """Bind one task artifact to its live repository file without a digest guard."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT result_json FROM graph_runs WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            result = json.loads(row["result_json"]) if row["result_json"] else None
            if not isinstance(result, dict) or not isinstance(result.get("artifacts"), list):
                raise KeyError(artifact_id)
            updated: AgentArtifactDescriptor | None = None
            artifacts: list[dict[str, object]] = []
            for raw in result["artifacts"]:
                descriptor = AgentArtifactDescriptor.model_validate(raw)
                if descriptor.artifact_id == artifact_id:
                    if descriptor.kept_filename is not None:
                        updated = descriptor
                    else:
                        updated = descriptor.model_copy(
                            update={"kept_filename": kept_filename, "kept_at": kept_at}
                        )
                    descriptor = updated
                artifacts.append(descriptor.model_dump(mode="json"))
            if updated is None:
                raise KeyError(artifact_id)
            result = {**result, "artifacts": artifacts}
            connection.execute(
                "UPDATE graph_runs SET result_json = ?, updated_at = ? WHERE operation_id = ?",
                (self._bounded_result_json(result), self.now(), operation_id),
            )
        return updated

    def agent_task_authorizer(self, operation_id: str) -> AuthorizedHuman | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT authorized_space_id, authorized_user_id, authorized_display_name
                FROM graph_runs
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return self._authorized_human_snapshot(row)

    def agent_task_authority(
        self,
        project_id: str,
        operation_id: str,
    ) -> AgentTaskAuthority:
        """Resolve one direct task only inside the project applying its Patch."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT operation_id, project_id, episode_id, kind, graph_target_json,
                       dispatch_authority_json,
                       authorized_space_id, authorized_user_id, authorized_display_name
                FROM graph_runs
                WHERE project_id = ? AND operation_id = ?
                """,
                (project_id, operation_id),
            ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        dispatch_json = row["dispatch_authority_json"]
        stored_target = GraphTargetRef.model_validate_json(row["graph_target_json"])
        return AgentTaskAuthority(
            operation_id=str(row["operation_id"]),
            project_id=str(row["project_id"]),
            apply_target=(GraphTargetRef() if row["kind"] == "branch_merge" else stored_target),
            authorized_by=self._authorized_human_snapshot(row),
            episode_id=row["episode_id"],
            dispatch_authority=(
                AgentDispatchAuthority.model_validate_json(dispatch_json)
                if dispatch_json is not None
                else None
            ),
        )

    def _claim_agent_task_graph_repair(
        self,
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> sqlite3.Row:
        """Claim one repairable graph result inside its caller's transaction."""

        row = connection.execute(
            "SELECT * FROM graph_runs WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        data = dict(row)
        request = json.loads(data["request_json"])
        result = json.loads(data["result_json"]) if data.get("result_json") else None
        graph_update = result.get("graph_update") if isinstance(result, dict) else None
        eligible = (
            data["status"] == "succeeded"
            and not bool(data.get("history_only"))
            and data["kind"] in {"node_chat", "project_chat"}
            and isinstance(request, dict)
            and request.get("mode") == "work"
            and bool(data.get("native_session_id"))
            and bool(data.get("stage_root"))
            and isinstance(graph_update, dict)
            and graph_update.get("status") == "rejected"
            and graph_update.get("repairable") is True
        )
        if not eligible:
            raise ValueError(
                "This task has no repairable graph update. Start a new Work turn instead."
            )
        if request.get("patch_kind") == "experiment_loop":
            control_node_id = request.get("control_node_id")
            episode_id = request.get("control_episode_id")
            invocation = request.get("control_invocation")
            if (
                not isinstance(control_node_id, str)
                or not isinstance(episode_id, str)
                or not isinstance(invocation, int)
            ):
                raise ValueError("The Experiment graph repair lost its control binding.")
            self._validate_current_experiment_graph_repair(
                connection,
                project_id=data["project_id"],
                control_node_id=control_node_id,
                episode_id=episode_id,
                invocation=invocation,
                operation_id=operation_id,
            )
        assert isinstance(result, dict)
        assert isinstance(graph_update, dict)
        graph_update = {**graph_update, "repairable": False}
        claimed_result = {**result, "graph_update": graph_update}
        claimed_json = self._bounded_result_json(claimed_result)
        cursor = connection.execute(
            """
            UPDATE graph_runs
            SET result_json = ?, updated_at = ?
            WHERE operation_id = ? AND result_json = ?
            """,
            (claimed_json, self.now(), operation_id, data["result_json"]),
        )
        if cursor.rowcount != 1:
            raise ValueError("This graph update repair was already claimed.")
        claimed = connection.execute(
            "SELECT * FROM graph_runs WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        assert claimed is not None
        return claimed

    def claim_agent_task_graph_repair(self, operation_id: str) -> AgentTaskRecord:
        """Atomically consume one rejected Work result's manual repair eligibility."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._claim_agent_task_graph_repair(connection, operation_id)
        claimed = self.agent_task(operation_id)
        assert claimed is not None
        return claimed

    def create_agent_task_graph_repair(
        self,
        parent_operation_id: str,
        record: AgentTaskRecord,
    ) -> AgentTaskRecord:
        """Atomically claim an ordinary Work repair and admit its child task."""

        if (
            record.status != "queued"
            or not record.visible
            or record.parent_operation_id != parent_operation_id
            or record.kind not in {"node_chat", "project_chat"}
            or record.episode_id is not None
            or record.request.get("mode") != "work"
            or record.request.get("patch_kind") != "work"
        ):
            raise ValueError("An ordinary Work graph repair requires a queued child task.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._claim_agent_task_graph_repair(connection, parent_operation_id)
            if self._has_active_chat_overlap(connection, record):
                raise AgentTaskAdmissionConflict(
                    "Another task is already active in this conversation."
                )
            self._insert_agent_task(
                connection,
                record,
                continuation_cause="graph_repair",
            )
            stored = connection.execute(
                "SELECT * FROM graph_runs WHERE operation_id = ?", (record.operation_id,)
            ).fetchone()
            assert stored is not None
        return self._agent_task_record(stored)

    def agent_tasks(
        self,
        project_id: str,
        *,
        limit: int = AGENT_TASK_LIST_DEFAULT_LIMIT,
        include_hidden: bool = False,
        graph_target: GraphTargetRef | None = None,
    ) -> list[AgentTaskRecord]:
        """The newest tasks, plus every chat whose latest turn is still open.

        A chat turn that is running or waiting on a person stays listed after
        newer tasks push it past ``limit``, so the Chats panel can always show
        it. Only a chat's latest turn counts: a failure followed by a later turn
        in the same chat is history, not an open item. A latest turn that
        finished recently stays too, so a client that saw it open also sees it
        end.
        """
        target_json = graph_target.model_dump_json() if graph_target is not None else None
        open_statuses = sorted(ACTIVE_AGENT_TASK_STATUSES | AWAITING_HUMAN_AGENT_TASK_STATUSES)
        finished_since = (
            datetime.fromisoformat(self.now())
            - timedelta(seconds=AGENT_TASK_LIST_FINISHED_CHAT_SECONDS)
        ).isoformat()
        # Each branch is index-backed (graph_runs_project, graph_runs_status,
        # graph_runs_finished, graph_runs_chat_turn), so the list never ranks a
        # project's whole chat history; the active-task poll calls it every second.
        scope = (
            "{run}.project_id = :project AND (:hidden OR {run}.visible = 1)"
            " AND (:target IS NULL OR {run}.graph_target_json = :target)"
        )
        own_scope, later_scope = scope.format(run="graph_runs"), scope.format(run="later")
        statuses = ",".join(f":status{index}" for index in range(len(open_statuses)))
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                WITH recent AS (
                    SELECT operation_id FROM graph_runs
                    WHERE {own_scope}
                    ORDER BY created_at DESC
                    LIMIT :limit
                ),
                candidates AS (
                    SELECT operation_id, created_at, 1 AS still_open,
                           json_extract(request_json, '$.chat_id') AS chat_id
                    FROM graph_runs
                    WHERE {own_scope} AND status IN ({statuses})
                      AND kind IN ('node_chat', 'project_chat') AND history_only = 0
                    UNION ALL
                    SELECT operation_id, created_at, 0 AS still_open,
                           json_extract(request_json, '$.chat_id') AS chat_id
                    FROM graph_runs
                    WHERE {own_scope} AND finished_at >= :finished_since
                      AND status NOT IN ({statuses})
                      AND kind IN ('node_chat', 'project_chat') AND history_only = 0
                ),
                open_chats AS (
                    SELECT operation_id FROM candidates
                    WHERE chat_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM graph_runs AS later
                        WHERE {later_scope}
                          AND json_extract(later.request_json, '$.chat_id') = candidates.chat_id
                          AND later.kind IN ('node_chat', 'project_chat')
                          AND (later.created_at, later.operation_id)
                              > (candidates.created_at, candidates.operation_id)
                    )
                    ORDER BY still_open DESC, created_at DESC, operation_id DESC
                    LIMIT :open_limit
                )
                SELECT graph_runs.*,
                       EXISTS (
                           SELECT 1 FROM graph_run_receipts AS receipt
                           WHERE receipt.operation_id = graph_runs.operation_id
                             AND receipt.category IN (
                                 'experiment_recovery_abandoned',
                                 'auto_research_recovery_abandoned'
                             )
                       ) AS recovery_abandoned
                FROM graph_runs
                WHERE operation_id IN (SELECT operation_id FROM recent)
                   OR operation_id IN (SELECT operation_id FROM open_chats)
                ORDER BY created_at DESC
                """,
                {
                    "project": project_id,
                    "hidden": int(include_hidden),
                    "target": target_json,
                    "limit": max(1, min(limit, AGENT_TASK_LIST_MAX_LIMIT)),
                    **{f"status{index}": status for index, status in enumerate(open_statuses)},
                    "finished_since": finished_since,
                    "open_limit": AGENT_TASK_LIST_OPEN_CHAT_LIMIT,
                },
            ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def project_tasks_with_kept_artifacts(self, project_id: str) -> list[AgentTaskRecord]:
        """Retained chat outputs across complete history, without decoding unrelated tasks."""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT graph_runs.* FROM graph_runs
                WHERE project_id = ? AND kind IN ('node_chat', 'project_chat')
                  AND EXISTS (
                      SELECT 1 FROM json_each(graph_runs.result_json, '$.artifacts') AS artifact
                      WHERE artifact.type = 'object'
                        AND json_extract(artifact.value, '$.kept_filename') IS NOT NULL
                  )
                ORDER BY created_at DESC, operation_id
                """,
                (project_id,),
            ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def all_project_agent_tasks(self, project_id: str) -> list[AgentTaskRecord]:
        """Return the complete typed task set for durable project capture."""

        try:
            canonical_project_id = _canonical_uuid4(
                project_id,
                label="project identity",
            )
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT graph_runs.*,
                       EXISTS (
                           SELECT 1 FROM graph_run_receipts AS receipt
                           WHERE receipt.operation_id = graph_runs.operation_id
                             AND receipt.category IN (
                                 'experiment_recovery_abandoned',
                                 'auto_research_recovery_abandoned'
                             )
                       ) AS recovery_abandoned
                FROM graph_runs
                WHERE project_id = ?
                ORDER BY created_at, operation_id
                """,
                (canonical_project_id,),
            ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def graph_target_tasks(
        self,
        project_id: str,
        graph_target: GraphTargetRef,
        *,
        include_hidden: bool = False,
    ) -> list[AgentTaskRecord]:
        """Return every task bound to one exact graph target without a list-page limit."""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT graph_runs.*,
                       EXISTS (
                           SELECT 1 FROM graph_run_receipts AS receipt
                           WHERE receipt.operation_id = graph_runs.operation_id
                             AND receipt.category IN (
                                 'experiment_recovery_abandoned',
                                 'auto_research_recovery_abandoned'
                             )
                       ) AS recovery_abandoned
                FROM graph_runs
                WHERE project_id = ? AND graph_target_json = ? AND (? OR visible = 1)
                ORDER BY created_at, operation_id
                """,
                (
                    project_id,
                    graph_target.model_dump_json(),
                    int(include_hidden),
                ),
            ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def unsettled_graph_target_tasks(
        self,
        project_id: str,
        graph_target: GraphTargetRef,
    ) -> list[AgentTaskRecord]:
        """Return live tasks and recoverable paused leaves on one exact target."""

        with self.connection() as connection:
            return self._unsettled_graph_target_tasks_in_connection(
                connection, project_id, graph_target
            )

    def _unsettled_graph_target_tasks_in_connection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        graph_target: GraphTargetRef,
    ) -> list[AgentTaskRecord]:
        rows = connection.execute(
            """
            SELECT run.* FROM graph_runs AS run
            WHERE run.project_id = ? AND run.graph_target_json = ?
              AND (
                run.status IN ('queued', 'running', 'pausing')
                OR (
                  run.status = 'paused'
                  AND NOT EXISTS (
                    SELECT 1 FROM graph_runs AS child
                    WHERE child.parent_operation_id = run.operation_id
                      AND child.episode_id IS run.episode_id
                      AND child.attempt = run.attempt + 1
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM graph_run_receipts AS receipt
                    WHERE receipt.operation_id = run.operation_id
                      AND receipt.category IN (
                        'auto_research_recovery_abandoned',
                        'experiment_recovery_abandoned',
                        'auto_research_orchestrator_failure'
                      )
                  )
                )
              )
            ORDER BY run.created_at, run.operation_id
            """,
            (project_id, graph_target.model_dump_json()),
        ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def episode_tasks(
        self,
        episode_id: str,
        *,
        include_hidden: bool = False,
        newest: int | None = None,
    ) -> list[AgentTaskRecord]:
        """Return one episode's tasks without exposing hidden wrap-up work by default.

        ``newest`` keeps only that many of the most recent tasks, still in creation order.
        """

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT graph_runs.*,
                           EXISTS (
                               SELECT 1 FROM graph_run_receipts AS receipt
                               WHERE receipt.operation_id = graph_runs.operation_id
                                 AND receipt.category IN (
                                     'experiment_recovery_abandoned',
                                     'auto_research_recovery_abandoned'
                                 )
                           ) AS recovery_abandoned
                    FROM graph_runs
                    WHERE episode_id = ? AND (? OR visible = 1)
                    ORDER BY created_at DESC, operation_id DESC
                """
                + ("    LIMIT ?" if newest is not None else "")
                + """
                ) ORDER BY created_at, operation_id
                """,
                (episode_id, int(include_hidden)) + (() if newest is None else (newest,)),
            ).fetchall()
        return [self._agent_task_record(row) for row in rows]

    def has_active_chat_task(
        self,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
    ) -> bool:
        """Return whether one exact chat already owns an active task."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE project_id = ? AND kind = ?
                  AND json_extract(request_json, '$.chat_id') = ?
                  AND status IN ('queued', 'running', 'pausing')
                LIMIT 1
                """,
                (project_id, kind, chat_id),
            ).fetchone()
        return row is not None

    def has_chat_native_session_origin(
        self,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        node_id: str | None,
        provider: str,
        execution_machine: str,
        native_session_id: str,
    ) -> bool:
        """Prove that RCP previously observed this session on the exact chat binding."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE project_id = ? AND kind = ?
                  AND json_extract(request_json, '$.chat_id') = ?
                  AND json_extract(request_json, '$.node_id') IS ?
                  AND json_extract(request_json, '$.provider') = ?
                  AND json_extract(request_json, '$.run_on') = ?
                  AND native_session_id = ?
                  AND history_only = 0
                LIMIT 1
                """,
                (
                    project_id,
                    kind,
                    chat_id,
                    node_id,
                    provider,
                    execution_machine,
                    native_session_id,
                ),
            ).fetchone()
        return row is not None

    def chat_graph_target(self, project_id: str, chat_id: str) -> GraphTargetRef | None:
        """Resolve a conversation's target from durable task and native-session bindings."""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT graph_target_json FROM graph_runs
                WHERE project_id = ? AND kind IN ('node_chat', 'project_chat')
                  AND json_extract(request_json, '$.chat_id') = ?
                UNION
                SELECT run.graph_target_json FROM chat_session_contexts AS context
                JOIN graph_runs AS run ON run.operation_id = context.committed_operation_id
                WHERE context.project_id = ? AND context.chat_id = ?
                """,
                (project_id, chat_id, project_id, chat_id),
            ).fetchall()
        targets = {
            target.key: target
            for row in rows
            for target in [GraphTargetRef.model_validate_json(row["graph_target_json"])]
        }
        if len(targets) > 1:
            raise ValueError("This conversation has conflicting graph target bindings.")
        return next(iter(targets.values()), None)

    def chat_session_context(
        self,
        provider: str,
        execution_machine: str,
        native_session_id: str,
    ) -> ChatSessionContextRecord | None:
        """Read the durable baseline for one exact native provider session."""

        with self.connection() as connection:
            row = self._chat_session_context_row(
                connection,
                provider,
                execution_machine,
                native_session_id,
            )
        return self._chat_session_context_record(row) if row is not None else None

    def validate_chat_session_context_binding(
        self,
        provider: str,
        execution_machine: str,
        native_session_id: str,
        *,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        node_id: str | None,
    ) -> ChatSessionContextRecord | None:
        """Return an existing baseline only when its complete binding matches."""

        with self.connection() as connection:
            row = self._chat_session_context_row(
                connection,
                provider,
                execution_machine,
                native_session_id,
            )
            if row is None:
                return None
            self._validate_chat_session_context_binding(
                row,
                project_id=project_id,
                kind=kind,
                chat_id=chat_id,
                node_id=node_id,
            )
        return self._chat_session_context_record(row)

    def commit_chat_session_context(
        self,
        *,
        provider: str,
        execution_machine: str,
        native_session_id: str,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        node_id: str | None,
        protocol_version: int,
        snapshot_json: str,
        snapshot_sha256: str,
        committed_operation_id: str,
        expected_snapshot_sha256: str | None,
    ) -> ChatSessionContextRecord:
        """CAS one session baseline, inserting only when no prior digest is expected."""

        now = self.now()
        ChatSessionContextRecord.model_validate(
            {
                "provider": provider,
                "execution_machine": execution_machine,
                "native_session_id": native_session_id,
                "project_id": project_id,
                "kind": kind,
                "chat_id": chat_id,
                "node_id": node_id,
                "protocol_version": protocol_version,
                "snapshot_json": snapshot_json,
                "snapshot_sha256": snapshot_sha256,
                "committed_operation_id": committed_operation_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        try:
            json.loads(snapshot_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Chat session context snapshot must be valid JSON.") from exc
        actual_sha256 = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        if snapshot_sha256 != actual_sha256:
            raise ValueError("Chat session context snapshot SHA-256 does not match its JSON.")

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._chat_session_context_row(
                    connection,
                    provider,
                    execution_machine,
                    native_session_id,
                )
                if row is None:
                    if expected_snapshot_sha256 is not None:
                        raise ValueError(
                            "Chat session context compare-and-swap failed: prior baseline is missing."
                        )
                    connection.execute(
                        """
                        INSERT INTO chat_session_contexts (
                            provider, execution_machine, native_session_id,
                            project_id, kind, chat_id, node_id, protocol_version,
                            snapshot_json, snapshot_sha256, committed_operation_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            provider,
                            execution_machine,
                            native_session_id,
                            project_id,
                            kind,
                            chat_id,
                            node_id,
                            protocol_version,
                            snapshot_json,
                            snapshot_sha256,
                            committed_operation_id,
                            now,
                            now,
                        ),
                    )
                else:
                    self._validate_chat_session_context_binding(
                        row,
                        project_id=project_id,
                        kind=kind,
                        chat_id=chat_id,
                        node_id=node_id,
                    )
                    if expected_snapshot_sha256 != row["snapshot_sha256"]:
                        raise ValueError(
                            "Chat session context compare-and-swap failed: prior digest changed."
                        )
                    changed = connection.execute(
                        """
                        UPDATE chat_session_contexts
                        SET protocol_version = ?, snapshot_json = ?, snapshot_sha256 = ?,
                            committed_operation_id = ?, updated_at = ?
                        WHERE provider = ? AND execution_machine = ? AND native_session_id = ?
                          AND snapshot_sha256 = ?
                        """,
                        (
                            protocol_version,
                            snapshot_json,
                            snapshot_sha256,
                            committed_operation_id,
                            now,
                            provider,
                            execution_machine,
                            native_session_id,
                            expected_snapshot_sha256,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise ValueError(
                            "Chat session context compare-and-swap failed: prior digest changed."
                        )
            except Exception:
                connection.rollback()
                raise

        stored = self.chat_session_context(provider, execution_machine, native_session_id)
        assert stored is not None
        return stored

    def record_agent_usage(
        self,
        operation_id: str,
        usage: ProviderUsage,
        *,
        idempotent: bool = False,
    ) -> AgentUsageRecord:
        """Persist one provider usage report and mark duplicate reports excluded."""

        task = self.agent_task(operation_id)
        if task is None:
            raise ValueError(f"Cannot attribute provider usage to unknown task {operation_id!r}")
        usage_id = str(uuid.uuid4())
        recorded_usage_id = usage_id
        now = self.now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT usage_id FROM agent_usage
                WHERE operation_id = ? AND provider_profile = ? AND dedupe_key = ?
                    AND counted = 1
                LIMIT 1
                """,
                (operation_id, usage.provider_profile, usage.dedupe_key),
            ).fetchone()
            if duplicate is not None and idempotent:
                recorded_usage_id = str(duplicate["usage_id"])
            else:
                counted = duplicate is None
                count_reason: AgentUsageCountReason = "counted" if counted else "duplicate"
                connection.execute(
                    """
                    INSERT INTO agent_usage (
                        usage_id, project_id, operation_id, provider, model,
                        task_kind, provider_profile, provider_event_type, dedupe_key, counted,
                        count_reason, created_at, processed_input_tokens,
                        generated_tokens, cached_input_tokens,
                        cache_creation_input_tokens, cache_write_input_tokens,
                        reasoning_output_tokens, reported_input_tokens,
                        reported_output_tokens, reported_total_tokens,
                        provider_fields_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        usage_id,
                        task.project_id,
                        operation_id,
                        task.request.get("provider") or "unknown",
                        task.request.get("model"),
                        task.kind,
                        usage.provider_profile,
                        usage.provider_event_type,
                        usage.dedupe_key,
                        int(counted),
                        count_reason,
                        now,
                        usage.processed_input_tokens,
                        usage.generated_tokens,
                        usage.cached_input_tokens,
                        usage.cache_creation_input_tokens,
                        usage.cache_write_input_tokens,
                        usage.reasoning_output_tokens,
                        usage.reported_input_tokens,
                        usage.reported_output_tokens,
                        usage.reported_total_tokens,
                        json.dumps(usage.provider_fields, separators=(",", ":")),
                    ),
                )
        record = self.agent_usage_record(recorded_usage_id)
        assert record is not None
        return record

    def agent_usage_record(self, usage_id: str) -> AgentUsageRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_usage WHERE usage_id = ?", (usage_id,)
            ).fetchone()
        return self._agent_usage_record(row) if row else None

    def agent_usage(self, project_id: str) -> list[AgentUsageRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_usage
                WHERE project_id = ?
                ORDER BY created_at ASC, usage_id ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._agent_usage_record(row) for row in rows]

    def agent_usage_snapshot(self, project_id: str) -> AgentUsageSnapshot:
        # Hidden report generation is an internal episode wrap-up, not an
        # operational task or usage cell on the user-facing meter.
        records = [
            record
            for record in self.agent_usage(project_id)
            if record.task_kind != "episode_report"
        ]
        input_processed, generated, counted_records, excluded_records = self._agent_usage_metrics(
            records
        )
        return AgentUsageSnapshot(
            project_id=project_id,
            input_processed=input_processed,
            generated=generated,
            counted_records=counted_records,
            excluded_records=excluded_records,
            records=records,
        )

    def _agent_usage_metrics(
        self,
        records: list[AgentUsageRecord],
    ) -> tuple[AgentUsageMetric, AgentUsageMetric, int, int]:
        counted = [record for record in records if record.counted]
        # Input reports describe the full context of one request. For a resumed
        # native session, later reports supersede earlier context sizes; generated
        # output is newly produced content and remains additive.
        latest_input_by_session: dict[tuple[str, str], AgentUsageRecord] = {}
        input_cells: dict[tuple[AgentTaskKind, str], AgentUsageCell] = {}
        generated_cells: dict[tuple[AgentTaskKind, str], AgentUsageCell] = {}
        tasks: dict[str, AgentTaskRecord | None] = {}
        for record in counted:
            if record.operation_id not in tasks:
                tasks[record.operation_id] = self.agent_task(record.operation_id)
            task = tasks[record.operation_id]
            if task is None:
                continue
            native_session_id = task.native_session_id or task.request.get("session_id")
            session_key = (
                (record.provider, native_session_id)
                if isinstance(native_session_id, str) and native_session_id
                else (record.provider, f"usage:{record.usage_id}")
            )
            previous = latest_input_by_session.get(session_key)
            if previous is None or (record.created_at, record.usage_id) > (
                previous.created_at,
                previous.usage_id,
            ):
                latest_input_by_session[session_key] = record

            key = (task.kind, record.provider)
            generated_cell = generated_cells.setdefault(
                key,
                AgentUsageCell(task_kind=task.kind, provider=record.provider),
            )
            generated_cell.generated_tokens += record.generated_tokens
            generated_cell.counted_records += 1

        for record in latest_input_by_session.values():
            task = tasks[record.operation_id]
            if task is None:
                continue
            key = (task.kind, record.provider)
            input_cell = input_cells.setdefault(
                key,
                AgentUsageCell(task_kind=task.kind, provider=record.provider),
            )
            input_cell.processed_input_tokens += record.processed_input_tokens
            input_cell.cached_input_tokens += record.cached_input_tokens
            input_cell.counted_records += 1

        input_total = sum(cell.processed_input_tokens for cell in input_cells.values())
        generated_total = sum(cell.generated_tokens for cell in generated_cells.values())
        cached_total = sum(cell.cached_input_tokens for cell in input_cells.values())
        return (
            AgentUsageMetric(
                total_tokens=input_total,
                cached_tokens=cached_total,
                cache_share=cached_total / input_total if input_total else 0.0,
                block_tokens=input_total / 20 if input_total else 0.0,
                cells=sorted(
                    input_cells.values(),
                    key=lambda cell: (cell.task_kind, cell.provider),
                ),
            ),
            AgentUsageMetric(
                total_tokens=generated_total,
                block_tokens=generated_total / 20 if generated_total else 0.0,
                cells=sorted(
                    generated_cells.values(),
                    key=lambda cell: (cell.task_kind, cell.provider),
                ),
            ),
            len(counted),
            len(records) - len(counted),
        )

    def has_resumable_paused_chat_task(
        self,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
    ) -> bool:
        """Whether this conversation has a paused attempt awaiting a decision.

        A Resume or Retry creates a child operation immediately. Once that child
        exists, the paused parent no longer blocks a later ordinary turn; if the
        child itself pauses, it is independently found by this query.
        """

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM graph_runs AS paused
                WHERE paused.project_id = ?
                    AND paused.kind = ?
                    AND paused.status = 'paused'
                    AND paused.history_only = 0
                    AND paused.native_session_id IS NOT NULL
                    AND (paused.stage_host IS NULL OR paused.stage_host = ''
                         OR paused.stage_root IS NOT NULL)
                    AND json_extract(paused.request_json, '$.chat_id') = ?
                    AND NOT EXISTS (
                        SELECT 1
                        FROM graph_runs AS child
                        WHERE child.parent_operation_id = paused.operation_id
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM graph_run_receipts AS receipt
                        WHERE receipt.operation_id = paused.operation_id
                          AND receipt.category = 'experiment_recovery_abandoned'
                    )
                LIMIT 1
                """,
                (project_id, kind, chat_id),
            ).fetchone()
        return row is not None

    def has_any_active_agent_task(self) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE status IN ('queued', 'running', 'pausing')
                LIMIT 1
                """
            ).fetchone()
        return row is not None

    def has_active_agent_task(self, project_id: str) -> bool:
        with self.connection() as connection:
            canonical_project_id = self._resolve_project_id_from_connection(connection, project_id)
            row = connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE project_id = ?
                  AND status IN ('queued', 'running', 'pausing')
                LIMIT 1
                """,
                (canonical_project_id,),
            ).fetchone()
        return row is not None

    def agent_task_events(
        self, operation_id: str, *, limit: int = AGENT_TASK_EVENT_LIST_DEFAULT_LIMIT
    ) -> list[AgentTaskEventRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM graph_run_events
                WHERE operation_id = ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (operation_id, max(1, min(limit, AGENT_TASK_EVENT_LIST_MAX_LIMIT))),
            ).fetchall()
        return [self._agent_task_event_record(row) for row in rows]

    def record_agent_task_event(
        self,
        operation_id: str,
        message: str,
        *,
        level: Literal["info", "warning", "error"] = "info",
    ) -> None:
        detail = " ".join(message.split())[:2000]
        if not detail:
            return
        with self.connection() as connection:
            self._insert_agent_task_event(
                connection,
                operation_id,
                detail,
                level=level,
                created_at=self.now(),
            )

    @staticmethod
    def _insert_agent_task_event(
        connection: sqlite3.Connection,
        operation_id: str,
        detail: str,
        *,
        level: Literal["info", "warning", "error"],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO graph_run_events (
                operation_id, created_at, level, message, episode_id
            )
            SELECT operation_id, ?, ?, ?, episode_id
            FROM graph_runs WHERE operation_id = ?
            """,
            (created_at, level, detail, operation_id),
        )
        connection.execute(
            """
            DELETE FROM graph_run_events
            WHERE operation_id = ? AND event_kind = 'message' AND event_id NOT IN (
                SELECT event_id FROM graph_run_events
                WHERE operation_id = ? AND event_kind = 'message'
                ORDER BY event_id DESC
                LIMIT ?
            )
            """,
            (operation_id, operation_id, AGENT_TASK_EVENT_RETENTION_COUNT),
        )

    def agent_task_receipts(
        self, operation_id: str, *, limit: int = AGENT_TASK_RECEIPT_LIST_LIMIT
    ) -> list[AgentTaskReceiptRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM graph_run_receipts
                WHERE operation_id = ?
                ORDER BY receipt_id ASC
                LIMIT ?
                """,
                (operation_id, max(1, min(limit, AGENT_TASK_RECEIPT_LIST_LIMIT))),
            ).fetchall()
        receipts = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json"))
            receipts.append(AgentTaskReceiptRecord.model_validate(data))
        return receipts

    def agent_task_degradations(self, operation_ids: Sequence[str]) -> dict[str, str]:
        """Return the named tasks' provider-degradation notes, keyed by operation.

        Read from the exit receipt that already records it rather than from a
        task column: the receipt is the durable original. Callers pass the tasks
        they are about to project, so the read stays on the receipt index and
        costs what that page of tasks costs. Those ids carry their own project
        check: every caller resolves its tasks through a project-scoped read
        before asking for their notes. A correction round records a second exit
        for the same task, so the newest note wins; it describes the pass that
        actually stands.
        """

        if not operation_ids:
            return {}
        placeholders = ",".join("?" for _ in operation_ids)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT operation_id, payload_json
                FROM graph_run_receipts
                WHERE operation_id IN ({placeholders}) AND category = 'provider_exit'
                ORDER BY receipt_id ASC
                """,  # noqa: S608 - placeholders are generated, never caller text
                tuple(operation_ids),
            ).fetchall()
        notes: dict[str, str] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            note = payload.get("degradation") if isinstance(payload, dict) else None
            if isinstance(note, str) and note:
                notes[str(row["operation_id"])] = note
        return notes

    def agent_task_continuation_cause(self, operation_id: str) -> str | None:
        """Return the durable launch cause for one task attempt.

        Recovery must preserve patch-only graph-repair semantics instead of
        inferring a full Work turn from the request shape alone.
        """

        intent = self.agent_task_admission_intent(operation_id)
        if intent is not None:
            cause = intent["continuation_cause"]
            assert isinstance(cause, str)
            return cause

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'operation_created'
                ORDER BY receipt_id ASC
                LIMIT 1
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        cause = payload.get("continuation_cause") if isinstance(payload, dict) else None
        return cause if isinstance(cause, str) and cause else None

    def agent_task_continuation_causes(self, operation_ids: Sequence[str]) -> dict[str, str | None]:
        """Return the durable launch cause of many tasks in one read.

        The read-model twin of ``agent_task_continuation_cause``: the admission
        intent's cause where one was recorded, else the creation receipt's. It
        does not re-validate each intent against its task; a projection reads
        causes, it does not launch on them.
        """

        ids = list(dict.fromkeys(operation_ids))
        causes: dict[str, str | None] = {operation_id: None for operation_id in ids}
        if not ids:
            return causes
        admitted: dict[str, str | None] = {}
        created: dict[str, str | None] = {}
        with self.connection() as connection:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT operation_id, category, payload_json FROM graph_run_receipts
                    WHERE operation_id IN ({placeholders})
                      AND category IN ('operation_admitted', 'operation_created')
                    ORDER BY receipt_id ASC
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    try:
                        payload = json.loads(row["payload_json"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    cause = payload.get("continuation_cause")
                    cause = cause if isinstance(cause, str) and cause else None
                    operation_id = str(row["operation_id"])
                    if row["category"] == "operation_admitted" or (
                        payload.get("admission_committed") is True
                    ):
                        admitted.setdefault(operation_id, cause)
                    else:
                        created.setdefault(operation_id, cause)
        for operation_id in ids:
            if operation_id in admitted:
                causes[operation_id] = admitted[operation_id]
            elif operation_id in created:
                causes[operation_id] = created[operation_id]
        return causes

    def agent_task_admission_intent(self, operation_id: str) -> dict[str, object] | None:
        """Return one exact durable launch intent, including the legacy recovery form."""

        with self.connection() as connection:
            task = connection.execute(
                """
                SELECT kind, attempt, parent_operation_id
                FROM graph_runs WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            admitted_rows = connection.execute(
                """
                SELECT payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'operation_admitted'
                ORDER BY receipt_id ASC
                """,
                (operation_id,),
            ).fetchall()
            legacy_rows = (
                []
                if admitted_rows
                else connection.execute(
                    """
                    SELECT payload_json FROM graph_run_receipts
                    WHERE operation_id = ? AND category = 'operation_created'
                    ORDER BY receipt_id ASC
                    """,
                    (operation_id,),
                ).fetchall()
            )
        if len(admitted_rows) > 1:
            raise ValueError("The agent task has multiple admission intents.")
        if admitted_rows:
            intent = self._validated_agent_task_admission_payload(
                admitted_rows[0]["payload_json"],
                legacy=False,
            )
        else:
            legacy_intents: list[dict[str, object]] = []
            for row in legacy_rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict) and payload.get("admission_committed") is True:
                    legacy_intents.append(
                        self._validated_agent_task_admission_payload(
                            row["payload_json"],
                            legacy=True,
                        )
                    )
            if len(legacy_intents) > 1:
                raise ValueError("The agent task has multiple legacy admission intents.")
            intent = legacy_intents[0] if legacy_intents else None
        if intent is None:
            return None
        if task is None or (
            intent["kind"] != task["kind"]
            or intent["attempt"] != task["attempt"]
            or (
                "parent_operation_id" in intent
                and intent["parent_operation_id"] != task["parent_operation_id"]
            )
            or (
                "has_parent" in intent
                and intent["has_parent"] != (task["parent_operation_id"] is not None)
            )
        ):
            raise ValueError("The agent task admission intent does not match its task.")
        return intent

    @staticmethod
    def _validated_agent_task_admission_payload(
        payload_json: str,
        *,
        legacy: bool,
    ) -> dict[str, object]:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("The agent task admission intent is malformed.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The agent task admission intent is malformed.")
        kind = payload.get("kind")
        attempt = payload.get("attempt")
        cause = payload.get("continuation_cause")
        expected_keys = (
            {
                "kind",
                "attempt",
                "has_parent",
                "continuation_cause",
                "resumed",
                "admission_committed",
            }
            if legacy
            else {
                "kind",
                "attempt",
                "parent_operation_id",
                "continuation_cause",
                "admission_committed",
            }
        )
        if (
            set(payload) != expected_keys
            or not isinstance(kind, str)
            or not kind
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 1
            or not isinstance(cause, str)
            or cause not in _AGENT_TASK_CONTINUATION_CAUSES
            or payload.get("admission_committed") is not True
        ):
            raise ValueError("The agent task admission intent is malformed.")
        if legacy:
            if not isinstance(payload.get("has_parent"), bool) or not isinstance(
                payload.get("resumed"), bool
            ):
                raise ValueError("The legacy agent task admission intent is malformed.")
        elif "parent_operation_id" not in payload or not (
            payload["parent_operation_id"] is None
            or (
                isinstance(payload["parent_operation_id"], str)
                and bool(payload["parent_operation_id"])
            )
        ):
            raise ValueError("The agent task admission intent is malformed.")
        return payload

    @staticmethod
    def _unresolved_remote_provider_passes(
        connection: sqlite3.Connection, stage_host: str, stage_root: str
    ) -> list[tuple[str, str]]:
        rows = connection.execute(
            """
            SELECT started.operation_id,
                   json_extract(started.payload_json, '$.pid_file') AS pid_file
            FROM graph_run_receipts AS started
            WHERE started.category = 'remote_provider_started'
              AND json_extract(started.payload_json, '$.stage_host') = ?
              AND json_extract(started.payload_json, '$.stage_root') = ?
              AND NOT EXISTS (
                  SELECT 1 FROM graph_run_receipts AS stopped
                  WHERE stopped.category = 'remote_provider_stopped'
                    AND stopped.operation_id = started.operation_id
                    AND json_extract(stopped.payload_json, '$.pid_file') =
                        json_extract(started.payload_json, '$.pid_file')
              )
            ORDER BY started.receipt_id
            """,
            (stage_host, stage_root),
        ).fetchall()
        return [(str(row["operation_id"]), str(row["pid_file"])) for row in rows]

    def unresolved_remote_provider_passes(
        self, stage_host: str, stage_root: str
    ) -> list[tuple[str, str]]:
        """Return passes whose remote process group has not been confirmed absent."""
        with self.connection() as connection:
            return self._unresolved_remote_provider_passes(connection, stage_host, stage_root)

    def unresolved_herdr_bindings(
        self, stage_root: str | None = None
    ) -> list[tuple[str, dict[str, object]]]:
        """Return durable native panes whose closure has not been confirmed."""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT started.operation_id, started.payload_json
                FROM graph_run_receipts AS started
                WHERE started.category = 'herdr_binding_start'
                  AND (? IS NULL OR json_extract(started.payload_json, '$.stage_root') = ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_run_receipts AS stopped
                      WHERE stopped.category = 'herdr_binding_stop'
                        AND stopped.operation_id = started.operation_id
                        AND json_extract(stopped.payload_json, '$.pane_id') =
                            json_extract(started.payload_json, '$.pane_id')
                  )
                ORDER BY started.receipt_id
                """,
                (stage_root, stage_root),
            ).fetchall()
        return [(str(row["operation_id"]), json.loads(row["payload_json"])) for row in rows]

    def begin_herdr_binding(self, operation_id: str, binding: dict[str, object]) -> None:
        stage_root = binding.get("stage_root")
        if not isinstance(stage_root, str) or not stage_root.startswith("/"):
            raise ValueError("A Herdr binding requires an absolute stage root.")
        if not isinstance(binding.get("pane_id"), str):
            raise ValueError("A Herdr binding requires its exact pane ID.")
        payload = self._bounded_receipt_payload(binding)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            conflict = connection.execute(
                """
                SELECT 1 FROM graph_run_receipts AS started
                WHERE started.category = 'herdr_binding_start'
                  AND json_extract(started.payload_json, '$.stage_root') = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_run_receipts AS stopped
                      WHERE stopped.category = 'herdr_binding_stop'
                        AND stopped.operation_id = started.operation_id
                        AND json_extract(stopped.payload_json, '$.pane_id') =
                            json_extract(started.payload_json, '$.pane_id')
                  )
                LIMIT 1
                """,
                (stage_root,),
            ).fetchone()
            if conflict is not None:
                raise ValueError(
                    "A previous Herdr agent in this stage has not been confirmed closed."
                )
            self._insert_agent_task_receipt(
                connection,
                operation_id,
                "herdr_binding_start",
                payload,
                tier="summary",
                created_at=self.now(),
            )

    def finish_herdr_binding(self, operation_id: str, binding: dict[str, object]) -> None:
        pane_id = binding.get("pane_id")
        if not isinstance(pane_id, str):
            raise ValueError("A Herdr stop requires its exact pane ID.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            started = connection.execute(
                """
                SELECT payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'herdr_binding_start'
                  AND json_extract(payload_json, '$.pane_id') = ?
                ORDER BY receipt_id DESC LIMIT 1
                """,
                (operation_id, pane_id),
            ).fetchone()
            if started is None:
                raise ValueError("Herdr pane has no matching start receipt.")
            stopped = connection.execute(
                """
                SELECT 1 FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'herdr_binding_stop'
                  AND json_extract(payload_json, '$.pane_id') = ?
                LIMIT 1
                """,
                (operation_id, pane_id),
            ).fetchone()
            if stopped is None:
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "herdr_binding_stop",
                    started["payload_json"],
                    tier="summary",
                    created_at=self.now(),
                )

    def begin_remote_provider_pass(
        self,
        operation_id: str,
        stage_host: str,
        stage_root: str,
        pid_file: str,
        *,
        supervised: bool = False,
    ) -> None:
        """Atomically reserve an exact remote stage before launching one provider pass.

        `supervised` says a turn supervisor is writing a journal under this
        pidfile. It is what lets a restart tell a pass whose result is still
        recoverable from a pass whose only record died with the process.
        """
        root = PurePosixPath(stage_root)
        pid = PurePosixPath(pid_file)
        if (
            not stage_host.strip()
            or not root.is_absolute()
            or not pid.is_relative_to(root)
            or pid == root
            or ".." in pid.parts
        ):
            raise ValueError("A remote provider pass requires its exact host, stage and pidfile.")
        payload = self._bounded_receipt_payload(
            {
                "stage_host": stage_host,
                "stage_root": stage_root,
                "pid_file": pid_file,
                "supervised": supervised,
            }
        )
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._unresolved_remote_provider_passes(connection, stage_host, stage_root):
                raise AgentTaskAdmissionConflict(
                    "A provider call in this remote stage is live or its exit is unconfirmed."
                )
            if (
                connection.execute(
                    """
                SELECT 1 FROM graph_run_receipts
                WHERE category = 'remote_provider_started'
                  AND (json_extract(payload_json, '$.stage_host') = ? OR operation_id = ?)
                  AND json_extract(payload_json, '$.pid_file') = ?
                LIMIT 1
                """,
                    (stage_host, operation_id, pid_file),
                ).fetchone()
                is not None
            ):
                raise ValueError("A remote provider pass must use a new pidfile identity.")
            self._insert_agent_task_receipt(
                connection,
                operation_id,
                "remote_provider_started",
                payload,
                tier="summary",
                created_at=self.now(),
            )

    def finish_remote_provider_pass(self, operation_id: str, pid_file: str) -> None:
        """Record confirmed absence for exactly one previously reserved process group."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._finish_remote_provider_pass(connection, operation_id, pid_file)

    def _finish_remote_provider_pass(
        self,
        connection: sqlite3.Connection,
        operation_id: str,
        pid_file: str,
    ) -> None:
        started = connection.execute(
            """
            SELECT payload_json FROM graph_run_receipts
            WHERE operation_id = ? AND category = 'remote_provider_started'
              AND json_extract(payload_json, '$.pid_file') = ?
            """,
            (operation_id, pid_file),
        ).fetchone()
        if started is None:
            raise ValueError("The remote provider pass has no matching start receipt.")
        if (
            connection.execute(
                """
                SELECT 1 FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'remote_provider_stopped'
                  AND json_extract(payload_json, '$.pid_file') = ?
                """,
                (operation_id, pid_file),
            ).fetchone()
            is not None
        ):
            return
        self._insert_agent_task_receipt(
            connection,
            operation_id,
            "remote_provider_stopped",
            started["payload_json"],
            tier="summary",
            created_at=self.now(),
        )

    def record_agent_task_receipt(
        self,
        operation_id: str,
        category: str,
        payload: dict[str, object],
        *,
        tier: AgentTaskReceiptTier = "summary",
    ) -> None:
        safe_category = " ".join(category.split())[:100]
        if not safe_category:
            return
        if safe_category in {
            "operation_admitted",
            "operation_dispatch_reset",
            "remote_provider_started",
            "remote_provider_stopped",
        }:
            raise ValueError(f"{safe_category} is reserved for an atomic task transition")
        if tier not in AGENT_TASK_RECEIPT_RETENTION_COUNTS:
            raise ValueError(f"Unknown agent-task receipt tier: {tier}")
        payload_json = self._bounded_receipt_payload(payload)
        with self.connection() as connection:
            self._insert_agent_task_receipt(
                connection,
                operation_id,
                safe_category,
                payload_json,
                tier=tier,
                created_at=self.now(),
            )

    @staticmethod
    def _insert_agent_task_receipt(
        connection: sqlite3.Connection,
        operation_id: str,
        category: str,
        payload_json: str,
        *,
        tier: AgentTaskReceiptTier,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO graph_run_receipts (
                operation_id, created_at, tier, category, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (operation_id, created_at, tier, category, payload_json),
        )
        protected_count = int(
            connection.execute(
                f"""
                SELECT COUNT(*) FROM graph_run_receipts
                WHERE operation_id = ? AND tier = ?
                  AND category IN ({_PROTECTED_AGENT_TASK_RECEIPT_PLACEHOLDERS})
                """,
                (operation_id, tier, *_PROTECTED_AGENT_TASK_RECEIPT_CATEGORIES),
            ).fetchone()[0]
        )
        ordinary_limit = max(0, AGENT_TASK_RECEIPT_RETENTION_COUNTS[tier] - protected_count)
        connection.execute(
            f"""
            DELETE FROM graph_run_receipts
            WHERE operation_id = ? AND tier = ?
              AND category NOT IN ({_PROTECTED_AGENT_TASK_RECEIPT_PLACEHOLDERS})
              AND receipt_id NOT IN (
                SELECT receipt_id FROM graph_run_receipts
                WHERE operation_id = ? AND tier = ?
                  AND category NOT IN ({_PROTECTED_AGENT_TASK_RECEIPT_PLACEHOLDERS})
                ORDER BY receipt_id DESC
                LIMIT ?
            )
            """,
            (
                operation_id,
                tier,
                *_PROTECTED_AGENT_TASK_RECEIPT_CATEGORIES,
                operation_id,
                tier,
                *_PROTECTED_AGENT_TASK_RECEIPT_CATEGORIES,
                ordinary_limit,
            ),
        )

    def record_agent_task_contract(
        self, operation_id: str, role: str, content: str, sha256: str
    ) -> None:
        """Persist immutable contract content outside bounded diagnostic receipts."""
        safe_role = " ".join(role.split())[:200]
        if not safe_role:
            raise ValueError("agent-task contract role is empty")
        with self.connection() as connection:
            existing = connection.execute(
                """
                SELECT sha256, content FROM graph_run_contracts
                WHERE operation_id = ? AND role = ?
                """,
                (operation_id, safe_role),
            ).fetchone()
            if existing is not None:
                if existing["sha256"] != sha256 or existing["content"] != content:
                    raise ValueError("immutable agent-task contract already differs")
                return
            connection.execute(
                """
                INSERT INTO graph_run_contracts (
                    operation_id, role, created_at, sha256, content
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (operation_id, safe_role, self.now(), sha256, content),
            )

    def agent_task_contract(self, operation_id: str, role: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT content FROM graph_run_contracts
                WHERE operation_id = ? AND role = ?
                """,
                (operation_id, role),
            ).fetchone()
        return str(row["content"]) if row is not None else None

    def agent_task_contracts(self, operation_id: str) -> list[AgentTaskContractRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT operation_id, role, created_at, sha256, content
                FROM graph_run_contracts
                WHERE operation_id = ?
                ORDER BY rowid
                """,
                (operation_id,),
            ).fetchall()
        return [AgentTaskContractRecord.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _bounded_receipt_payload(payload: dict[str, object]) -> str:
        keys = [str(key)[:80] for key in list(payload)[:32]]
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "omitted": True,
                    "reason": "payload_not_json_serializable",
                    "keys": keys,
                },
                separators=(",", ":"),
            )
        byte_length = len(encoded.encode("utf-8"))
        if byte_length <= AGENT_TASK_RECEIPT_MAX_BYTES:
            return encoded
        return json.dumps(
            {
                "omitted": True,
                "reason": "payload_exceeded_limit",
                "byte_length": byte_length,
                "keys": keys,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _bounded_command_payload(payload: dict[str, object]) -> str:
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("agent command event payload is not valid JSON") from exc
        if len(encoded.encode("utf-8")) > AGENT_COMMAND_EVENT_MAX_BYTES:
            raise ValueError("agent command event payload exceeds the configured size limit")
        return encoded

    @staticmethod
    def _bounded_graph_update(
        raw_graph_update: object,
        *,
        concise: bool = False,
    ) -> dict[str, object] | None:
        if isinstance(raw_graph_update, dict) and raw_graph_update.get("status") in {
            "none",
            "applied",
            "rejected",
        }:
            raw_change_summary = raw_graph_update.get("change_summary")
            raw_proposal_ids = raw_graph_update.get("proposal_ids")
            raw_validation_messages = raw_graph_update.get("validation_messages")
            change_count, change_length = (2, 200) if concise else (32, 1600)
            proposal_count, proposal_length = (8, 100) if concise else (32, 400)
            validation_count, validation_length = (2, 200) if concise else (8, 1600)
            return {
                "status": raw_graph_update["status"],
                "applied_revision": (
                    raw_graph_update.get("applied_revision")
                    if isinstance(raw_graph_update.get("applied_revision"), int)
                    and not isinstance(raw_graph_update.get("applied_revision"), bool)
                    else None
                ),
                "change_summary": [
                    item[:change_length]
                    for item in (
                        raw_change_summary[:change_count]
                        if isinstance(raw_change_summary, list)
                        else []
                    )
                    if isinstance(item, str)
                ],
                "proposal_ids": [
                    item[:proposal_length]
                    for item in (
                        raw_proposal_ids[:proposal_count]
                        if isinstance(raw_proposal_ids, list)
                        else []
                    )
                    if isinstance(item, str)
                ],
                "validation_messages": [
                    item[:validation_length]
                    for item in (
                        raw_validation_messages[:validation_count]
                        if isinstance(raw_validation_messages, list)
                        else []
                    )
                    if isinstance(item, str)
                ],
                "correction_rounds": (
                    raw_graph_update.get("correction_rounds")
                    if isinstance(raw_graph_update.get("correction_rounds"), int)
                    and not isinstance(raw_graph_update.get("correction_rounds"), bool)
                    else 0
                ),
                "repairable": raw_graph_update.get("repairable") is True,
            }
        return None

    @classmethod
    def _bounded_result_json(cls, result: dict[str, object] | None) -> str | None:
        if result is None:
            return None
        raw_artifacts = result.get("artifacts")
        artifacts: list[dict[str, object]] = []
        if isinstance(raw_artifacts, list):
            for raw_artifact in raw_artifacts[:CHAT_ARTIFACT_MAX_COUNT]:
                try:
                    descriptor = AgentArtifactDescriptor.model_validate(raw_artifact)
                except (TypeError, ValueError):
                    continue
                artifacts.append(descriptor.model_dump(mode="json"))
        payload: dict[str, object] = {"messages": []}
        if artifacts:
            payload["artifacts"] = artifacts

        graph_update = cls._bounded_graph_update(result.get("graph_update"))
        raw_graph_updates = result.get("graph_updates")
        graph_updates: list[dict[str, object]] = []
        latest_history_update: dict[str, object] | None = None
        if isinstance(raw_graph_updates, list):
            reverse_updates: list[dict[str, object]] = []
            for raw_update in reversed(raw_graph_updates):
                full_update = cls._bounded_graph_update(raw_update)
                if full_update is None:
                    continue
                if latest_history_update is None:
                    latest_history_update = full_update
                concise_update = cls._bounded_graph_update(full_update, concise=True)
                assert concise_update is not None
                reverse_updates.append(concise_update)
                if len(reverse_updates) == GRAPH_UPDATE_HISTORY_MAX_COUNT:
                    break
            graph_updates = list(reversed(reverse_updates))
        if graph_update is None:
            graph_update = latest_history_update
        if graph_update is not None:
            payload["graph_update"] = graph_update

        def encoded_size() -> int:
            return len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )

        result_limit = AGENT_TASK_RESULT_MAX_BYTES - 1
        base_limit = (
            result_limit - _GRAPH_UPDATE_HISTORY_RESERVE_BYTES if graph_updates else result_limit
        )
        while encoded_size() > base_limit:
            trimmed = False
            if graph_update is not None:
                for field in ("change_summary", "proposal_ids", "validation_messages"):
                    values = graph_update[field]
                    assert isinstance(values, list)
                    if values:
                        values.pop()
                        trimmed = True
                        break
            if not trimmed and artifacts:
                artifacts.pop()
                if not artifacts:
                    payload.pop("artifacts", None)
                trimmed = True
            if not trimmed:
                break

        retained_updates: list[dict[str, object]] = []
        for raw_update in reversed(graph_updates):
            update = {
                **raw_update,
                "change_summary": list(raw_update["change_summary"]),
                "proposal_ids": list(raw_update["proposal_ids"]),
                "validation_messages": list(raw_update["validation_messages"]),
            }
            candidate = [update, *retained_updates]
            payload["graph_updates"] = candidate
            while encoded_size() > result_limit:
                trimmed = False
                for field in ("change_summary", "proposal_ids", "validation_messages"):
                    values = update[field]
                    assert isinstance(values, list)
                    if values:
                        values.pop()
                        trimmed = True
                        break
                if not trimmed:
                    break
            if encoded_size() > result_limit:
                break
            retained_updates = candidate
        if retained_updates:
            payload["graph_updates"] = retained_updates
        else:
            payload.pop("graph_updates", None)

        raw_messages = result.get("messages")
        messages = raw_messages if isinstance(raw_messages, list) else []
        bounded: list[str] = []
        for raw_message in messages[:32]:
            if not isinstance(raw_message, str):
                continue
            message = raw_message.strip()
            if not message:
                continue
            bounded.append(message[:16_000])
            payload["messages"] = bounded
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(encoded.encode("utf-8")) > result_limit:
                bounded.pop()
                break
        payload["messages"] = bounded
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def agent_task_patch_output(self, operation_id: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT patch_json FROM graph_run_outputs WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return str(row["patch_json"]) if row else None

    def record_agent_task_patch_output(self, operation_id: str, patch_json: str) -> None:
        if len(patch_json.encode("utf-8")) > 2_000_000:
            raise ValueError("direct patch output exceeds the 2 MB recovery limit")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO graph_run_outputs (operation_id, created_at, patch_json)
                VALUES (?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    patch_json = excluded.patch_json
                """,
                (operation_id, self.now(), patch_json),
            )

    def agent_task_estimate(
        self,
        project_id: str,
        kind: AgentTaskKind,
        request: dict[str, object],
    ) -> tuple[float, int]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT request_json, started_at, finished_at
                FROM graph_runs
                WHERE project_id = ? AND kind = ? AND status = 'succeeded'
                    AND started_at IS NOT NULL AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (project_id, kind, AGENT_TASK_ESTIMATE_HISTORY_LIMIT),
            ).fetchall()
        durations: list[float] = []
        for row in rows:
            saved_request = json.loads(row["request_json"])
            if saved_request.get("provider") != request.get("provider"):
                continue
            if (saved_request.get("model") or "") != (request.get("model") or ""):
                continue
            try:
                started = datetime.fromisoformat(row["started_at"])
                finished = datetime.fromisoformat(row["finished_at"])
            except (TypeError, ValueError):
                continue
            duration = (finished - started).total_seconds()
            if duration > 0:
                durations.append(duration)
            if len(durations) == AGENT_TASK_ESTIMATE_SAMPLE_LIMIT:
                break
        if durations:
            return max(1.0, float(median(durations))), len(durations)
        return (600.0 if kind == "seed" else 300.0), 0

    @staticmethod
    def _transition_agent_task(
        connection: sqlite3.Connection,
        operation_id: str,
        target_status: AgentTaskStatus,
        *,
        assignments: str = "",
        parameters: tuple[object, ...] = (),
    ) -> _AgentTaskTransitionResult:
        """Apply one guarded status transition and report its database outcome.

        The immediate transaction fences the status observation and guarded
        update together. Callers keep the same connection for every event,
        receipt, notice, and cleanup belonging to the result.
        """

        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status FROM graph_runs WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return _AgentTaskTransitionResult("missing")
        observed_status: AgentTaskStatus = row["status"]
        allowed_statuses = tuple(sorted(AGENT_TASK_TRANSITIONS[target_status]))
        if observed_status not in AGENT_TASK_TRANSITIONS[target_status]:
            return _AgentTaskTransitionResult("refused", observed_status)

        status_placeholders = ", ".join("?" for _ in allowed_statuses)
        set_clause = "status = ?"
        if assignments:
            set_clause = f"{set_clause}, {assignments}"
        changed = connection.execute(
            f"""
            UPDATE graph_runs
            SET {set_clause}
            WHERE operation_id = ? AND status IN ({status_placeholders})
            """,
            (target_status, *parameters, operation_id, *allowed_statuses),
        ).rowcount
        if changed != 1:
            return _AgentTaskTransitionResult("refused", observed_status)
        return _AgentTaskTransitionResult("applied", observed_status)

    @staticmethod
    def _agent_task_refusal_message(operation: str, status: AgentTaskStatus) -> str:
        labels = {
            "start": "Start",
            "pause": "Pause",
            "complete": "Completion",
            "fail": "Failure",
            "interrupt": "Interruption",
        }
        return f"{labels[operation]} refused: this task already {status}."

    @staticmethod
    def _agent_task_status(
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> AgentTaskStatus | None:
        row = connection.execute(
            "SELECT status FROM graph_runs WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        return row["status"] if row is not None else None

    @staticmethod
    def _require_agent_task_transition(
        operation_id: str,
        transition: _AgentTaskTransitionResult,
    ) -> None:
        if transition.outcome == "missing":
            raise KeyError(operation_id)

    def mark_agent_task_running(self, operation_id: str) -> bool:
        """Atomically claim a queued task and report whether dispatch may proceed."""

        now = self.now()
        with self.connection() as connection:
            transition = self._transition_agent_task(
                connection,
                operation_id,
                "running",
                assignments=(
                    "started_at = ?, updated_at = ?, last_activity_at = ?, "
                    "phase = 'preparing', status_message = 'Preparing agent task.'"
                ),
                parameters=(now, now, now),
            )
            self._require_agent_task_transition(operation_id, transition)
            if transition.outcome == "applied":
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    "Preparing agent task.",
                    level="info",
                    created_at=now,
                )
            else:
                assert transition.observed_status is not None
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    self._agent_task_refusal_message("start", transition.observed_status),
                    level="warning",
                    created_at=now,
                )
        return transition.outcome == "applied"

    def update_agent_task_message(
        self,
        operation_id: str,
        message: str,
        *,
        phase: str | None = None,
        event: bool = False,
    ) -> None:
        now = self.now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            status = self._agent_task_status(connection, operation_id)
            if status is None:
                raise KeyError(operation_id)
            changed = connection.execute(
                """
                UPDATE graph_runs
                SET status_message = ?, updated_at = ?, last_activity_at = ?,
                    phase = COALESCE(?, phase)
                WHERE operation_id = ? AND status IN ('running', 'pausing')
                """,
                (message, now, now, phase, operation_id),
            ).rowcount
            if changed == 1 and event:
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    message,
                    level="info",
                    created_at=now,
                )

    def checkpoint_agent_task(
        self,
        operation_id: str,
        *,
        native_session_id: str | None = None,
        stage_host: str | None = None,
        stage_root: str | None = None,
    ) -> None:
        now = self.now()
        with self.connection() as connection:
            updated = connection.execute(
                """
                UPDATE graph_runs
                SET native_session_id = COALESCE(?, native_session_id),
                    stage_host = COALESCE(?, stage_host),
                    stage_root = COALESCE(?, stage_root),
                    updated_at = ?, last_activity_at = ?
                WHERE operation_id = ?
                  AND (
                      ? IS NULL
                      OR native_session_id IS NULL
                      OR native_session_id = ?
                  )
                """,
                (
                    native_session_id,
                    stage_host,
                    stage_root,
                    now,
                    now,
                    operation_id,
                    native_session_id,
                    native_session_id,
                ),
            ).rowcount
            if updated == 1:
                return
            existing = connection.execute(
                "SELECT native_session_id FROM graph_runs WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(operation_id)
            raise ValueError("Agent task native session conflicts with its saved RCP checkpoint.")

    def checkpoint_agent_task_runtime(
        self,
        operation_id: str,
        *,
        provider: str,
        runtime_id: str,
    ) -> None:
        """Record the runtime selected immediately before provider prompt delivery."""

        require_runtime_id(provider, runtime_id)
        now = self.now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_json FROM graph_runs WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            request = json.loads(row["request_json"])
            if not isinstance(request, dict) or request.get("provider") != provider:
                raise ValueError("Agent task runtime does not match its admitted provider.")
            receipts = connection.execute(
                """
                SELECT payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'provider_runtime_selected'
                ORDER BY receipt_id ASC
                """,
                (operation_id,),
            ).fetchall()
            if receipts:
                if len(receipts) != 1:
                    raise ValueError("Agent task has multiple provider runtime receipts.")
                payload = json.loads(receipts[0]["payload_json"])
                if isinstance(payload, dict) and payload.get("runtime_id") == runtime_id:
                    return
                raise ValueError("Agent task changed runtime after provider prompt delivery.")
            connection.execute(
                """
                UPDATE graph_runs
                SET runtime_id = ?, updated_at = ?, last_activity_at = ?
                WHERE operation_id = ?
                """,
                (runtime_id, now, now, operation_id),
            )
            self._insert_agent_task_receipt(
                connection,
                operation_id,
                "provider_runtime_selected",
                self._bounded_receipt_payload({"provider": provider, "runtime_id": runtime_id}),
                tier="summary",
                created_at=now,
            )

    def bind_agent_task_write_scope(
        self,
        operation_id: str,
        *,
        project_id: str,
        stage_host: str,
        stage_root: str,
        fingerprint: str,
        continuation_binding: bool,
        scope_repositories: Sequence[str] = (),
        compatible_previous_fingerprint: str | None = None,
        compatible_related_fingerprints: frozenset[str] = frozenset(),
    ) -> None:
        """Compare-and-set the durable filesystem scope before provider launch.

        A continuation must keep the scope its native session was launched with,
        so it is compared against the stage's current binding. A fresh launch
        resumes no session and establishes the binding instead: the providers
        spec scopes this comparison to Resume, Retry, watcher wake, correction,
        and child continuation, and says a legitimate scope change starts a
        fresh task/session. Comparing a fresh launch against superseded history
        made a chat's repository scope permanent, because a chat stage is named
        from its chat id and is never cleared.
        """

        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("agent task write-scope fingerprint must be lowercase SHA-256")
        normalized_host = stage_host or ""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT project_id, kind, native_session_id,
                       COALESCE(stage_host, '') AS stage_host,
                       stage_root, write_scope_fingerprint
                FROM graph_runs WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            if row["project_id"] != project_id:
                raise ValueError("agent task write scope belongs to a different project")
            if row["stage_host"] != normalized_host or row["stage_root"] != stage_root:
                raise ValueError("agent task write scope does not match its saved execution stage")
            existing = row["write_scope_fingerprint"]
            if existing not in {None, fingerprint, compatible_previous_fingerprint}:
                raise ValueError("agent task write scope changed after it was durably bound")

            clauses = ["(COALESCE(stage_host, '') = ? AND stage_root = ?)"]
            values: list[object] = [normalized_host, stage_root]
            native_session_id = row["native_session_id"]
            if native_session_id:
                clauses.append("native_session_id = ?")
                values.append(native_session_id)
            admissible = {
                fingerprint,
                compatible_previous_fingerprint,
                *compatible_related_fingerprints,
            }
            if continuation_binding:
                # The durable binding is the stage's current one. Rows older
                # than the most recent binding were superseded by a fresh
                # launch and no longer describe this stage.
                conflict = connection.execute(
                    f"""
                    SELECT operation_id, write_scope_fingerprint
                    FROM graph_runs
                    WHERE operation_id != ? AND kind = ?
                      AND write_scope_fingerprint IS NOT NULL
                      AND ({" OR ".join(clauses)})
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (operation_id, row["kind"], *values),
                ).fetchone()
                if conflict is not None and conflict["write_scope_fingerprint"] not in admissible:
                    raise ValueError(
                        self._write_scope_conflict_message(
                            connection,
                            bound_operation_id=conflict["operation_id"],
                            offered=scope_repositories,
                            continuation=True,
                        )
                    )
            else:
                # A fresh launch may rebind the stage, but never underneath a
                # run that is still using it.
                active = ",".join("?" for _ in ACTIVE_AGENT_TASK_STATUSES)
                conflict = connection.execute(
                    f"""
                    SELECT operation_id, write_scope_fingerprint
                    FROM graph_runs
                    WHERE operation_id != ? AND kind = ?
                      AND write_scope_fingerprint IS NOT NULL
                      AND status IN ({active})
                      AND ({" OR ".join(clauses)})
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (
                        operation_id,
                        row["kind"],
                        *sorted(ACTIVE_AGENT_TASK_STATUSES),
                        *values,
                    ),
                ).fetchone()
                if conflict is not None and conflict["write_scope_fingerprint"] not in admissible:
                    raise ValueError(
                        self._write_scope_conflict_message(
                            connection,
                            bound_operation_id=conflict["operation_id"],
                            offered=scope_repositories,
                            continuation=False,
                        )
                    )
            updated = connection.execute(
                """
                UPDATE graph_runs
                SET write_scope_fingerprint = ?, updated_at = ?
                WHERE operation_id = ?
                  AND write_scope_fingerprint IS ?
                """,
                (fingerprint, self.now(), operation_id, existing),
            ).rowcount
            if updated != 1:
                raise ValueError("agent task write scope changed while it was being bound")

    def agent_task_has_receipt(self, operation_id: str, category: str) -> bool:
        """Whether this task recorded one receipt of the given category."""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM graph_run_receipts
                WHERE operation_id = ? AND category = ? LIMIT 1
                """,
                (operation_id, category),
            ).fetchone()
        return row is not None

    def owed_transport_retry_operation_ids(self) -> list[str]:
        """Turns whose reattempt was armed but never fired.

        The receipt that promises one is durable and the wait that keeps it is
        not, so a process that stops mid-wait leaves turns owed a reattempt that
        would never come. A turn something else already continued is not owed
        one.
        """

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT run.operation_id FROM graph_runs AS run
                WHERE run.status = 'failed'
                  AND run.failure_kind = 'transport_lost'
                  AND EXISTS (
                      SELECT 1 FROM graph_run_receipts AS receipt
                      WHERE receipt.operation_id = run.operation_id
                        AND receipt.category = 'transport_auto_retry'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_runs AS child
                      WHERE child.parent_operation_id = run.operation_id
                  )
                ORDER BY run.created_at, run.operation_id
                """
            ).fetchall()
        return [str(row["operation_id"]) for row in rows]

    def agent_task_has_continuation(self, operation_id: str) -> bool:
        """Whether some later task already continues this one.

        A retry, a recovery and a correction all record themselves as a child of
        the task they follow, so this answers "has anything already taken this
        turn over" without knowing which of them did.
        """

        with self.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM graph_runs WHERE parent_operation_id = ? LIMIT 1",
                (operation_id,),
            ).fetchone()
        return row is not None

    def agent_task_provider_exit(self, operation_id: str) -> ProviderExit | None:
        """How this task's last provider process ended, if it reported.

        Failure classification needs more than the code: a revoked login and a
        dropped link can both end a turn, and a provider that reached its own
        terminal event or reported its own error exits through ssh the same way
        a lost link does. Only the code and what the provider managed to say
        together name what happened.
        """

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'provider_exit'
                ORDER BY receipt_id DESC LIMIT 1
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        payload: object = None
        with suppress(ValueError, TypeError):
            payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return None
        code = payload.get("return_code")
        counts = payload.get("event_counts")
        errors = counts.get("error") if isinstance(counts, dict) else None
        return ProviderExit(
            return_code=code if isinstance(code, int) and not isinstance(code, bool) else None,
            spoke_for_itself=(
                payload.get("explicit_terminal_event") is True
                or (isinstance(errors, int) and not isinstance(errors, bool) and errors > 0)
            ),
        )

    @staticmethod
    def _write_scope_conflict_message(
        connection: sqlite3.Connection,
        *,
        bound_operation_id: str,
        offered: Sequence[str],
        continuation: bool,
    ) -> str:
        """Name the repositories on both sides so the human can act on this."""

        bound = connection.execute(
            "SELECT request_json FROM graph_runs WHERE operation_id = ?",
            (bound_operation_id,),
        ).fetchone()
        aliases: list[str] = []
        if bound is not None:
            with suppress(ValueError, TypeError):
                stored = json.loads(bound["request_json"] or "{}")
                scope = stored.get("run_truth_scope") if isinstance(stored, dict) else None
                if isinstance(scope, list):
                    aliases = sorted({str(item) for item in scope if isinstance(item, str)})
        held = _joined_repositories(aliases) or "a different set of repositories"
        asked = _joined_repositories(offered)
        subject = f"This turn offers {asked}, and its" if asked else "This turn's"
        if continuation:
            return (
                f"{subject} conversation workspace is already authorized for {held}. "
                "A continuation keeps the repository scope its provider session was "
                "launched with. Start a new episode to change the repository scope."
            )
        return (
            f"{subject} conversation workspace is in use by a running turn authorized "
            f"for {held}. Wait for that turn to finish before starting one with a "
            "different repository scope."
        )

    def clear_agent_task_stage(self, operation_id: str) -> None:
        now = self.now()
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE graph_runs
                SET stage_host = NULL, stage_root = NULL, updated_at = ?
                WHERE operation_id = ?
                """,
                (now, operation_id),
            )

    def run_stage_lifecycles(
        self,
        *,
        as_of: datetime | None = None,
    ) -> tuple[RunStageLifecycleRecord, ...]:
        """Project every durable owner onto its exact run-stage lifecycle."""

        current = _result_view_reference_time(as_of)
        aggregates: dict[tuple[str, str], _RunStageLifecycleAggregate] = {}

        def add(
            *,
            stage_host: object,
            stage_root: object,
            owner_ref: str,
            must_exist: bool,
            protect_from_cleanup: bool,
        ) -> None:
            if not isinstance(stage_root, str) or not stage_root:
                return
            host = stage_host if isinstance(stage_host, str) else ""
            aggregate = aggregates.setdefault(
                (host, stage_root),
                _RunStageLifecycleAggregate(owner_refs=set()),
            )
            aggregate.owner_refs.add(owner_ref)
            aggregate.must_exist = aggregate.must_exist or must_exist
            aggregate.protect_from_cleanup = aggregate.protect_from_cleanup or protect_from_cleanup

        with self.connection() as connection:
            remote_pass_rows = connection.execute(
                """
                SELECT started.operation_id,
                       json_extract(started.payload_json, '$.stage_host') AS stage_host,
                       json_extract(started.payload_json, '$.stage_root') AS stage_root
                FROM graph_run_receipts AS started
                WHERE started.category = 'remote_provider_started'
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_run_receipts AS stopped
                      WHERE stopped.category = 'remote_provider_stopped'
                        AND stopped.operation_id = started.operation_id
                        AND json_extract(stopped.payload_json, '$.pid_file') =
                            json_extract(started.payload_json, '$.pid_file')
                  )
                """
            ).fetchall()
            task_rows = connection.execute(
                """
                SELECT run.operation_id, COALESCE(run.stage_host, '') AS stage_host,
                       run.stage_root,
                       (
                         run.status IN ('queued', 'running', 'pausing')
                         OR episode.status IN ('queued', 'running', 'stopping', 'wrapping_up')
                       ) AS live
                FROM graph_runs AS run
                LEFT JOIN episodes AS episode ON episode.episode_id = run.episode_id
                WHERE run.stage_root IS NOT NULL AND run.stage_root != ''
                """
            ).fetchall()
            episode_rows = connection.execute(
                """
                SELECT state.episode_id, COALESCE(state.stage_host, '') AS stage_host,
                       state.stage_root,
                       episode.status IN ('queued', 'running', 'stopping', 'wrapping_up') AS live
                FROM experiment_episode_state AS state
                JOIN episodes AS episode ON episode.episode_id = state.episode_id
                WHERE state.stage_root IS NOT NULL AND state.stage_root != ''
                """
            ).fetchall()
            wrapup_rows = connection.execute(
                """
                SELECT wrapup.episode_id, COALESCE(wrapup.stage_host, '') AS stage_host,
                       wrapup.stage_root,
                       wrapup.state IN ('pending', 'running') AS live
                FROM episode_wrapups AS wrapup
                WHERE wrapup.stage_root IS NOT NULL AND wrapup.stage_root != ''
                """
            ).fetchall()
            view_rows = connection.execute(
                """
                SELECT view_id, stage_host, stage_root, expires_at, kept_filename
                FROM result_views
                WHERE stage_root IS NOT NULL AND stage_root != ''
                """
            ).fetchall()
            chat_rows = connection.execute(
                """
                SELECT context.native_session_id,
                       COALESCE(run.stage_host, '') AS stage_host, run.stage_root
                FROM chat_session_contexts AS context
                JOIN graph_runs AS run
                  ON run.operation_id = context.committed_operation_id
                WHERE run.stage_root IS NOT NULL AND run.stage_root != ''
                """
            ).fetchall()
            artifact_revision_rows = connection.execute(
                """
                SELECT candidate.candidate_id,
                       candidate.stage_host, candidate.stage_root, candidate.status,
                       COALESCE(source.stage_host, '') AS source_stage_host,
                       source.stage_root AS source_stage_root,
                       NOT EXISTS (
                           SELECT 1
                           FROM json_each(source.result_json, '$.artifacts') AS artifact
                           WHERE json_extract(artifact.value, '$.artifact_id') =
                                 candidate.source_artifact_id
                             AND json_extract(artifact.value, '$.kept_filename') IS NOT NULL
                       ) AS source_stage_required
                FROM artifact_revision_candidates AS candidate
                JOIN graph_runs AS source
                  ON source.operation_id = candidate.source_operation_id
                WHERE candidate.stage_root != '' OR source.stage_root != ''
                """
            ).fetchall()

        for row in remote_pass_rows:
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"remote_provider:{row['operation_id']}",
                must_exist=True,
                protect_from_cleanup=True,
            )
        for row in task_rows:
            live = bool(row["live"])
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"graph_runs:{row['operation_id']}",
                must_exist=live,
                protect_from_cleanup=live,
            )
        for row in episode_rows:
            live = bool(row["live"])
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"experiment_episode_state:{row['episode_id']}",
                must_exist=live,
                protect_from_cleanup=live,
            )
        for row in wrapup_rows:
            live = bool(row["live"])
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"episode_wrapups:{row['episode_id']}",
                must_exist=live,
                protect_from_cleanup=live,
            )
        for row in view_rows:
            live = row["kept_filename"] is None and _required_timestamp(row["expires_at"]) > current
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"result_views:{row['view_id']}",
                must_exist=False,
                protect_from_cleanup=live,
            )
        for row in chat_rows:
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"chat_session_contexts:{row['native_session_id']}",
                must_exist=False,
                protect_from_cleanup=True,
            )
        for row in artifact_revision_rows:
            unresolved = row["status"] in {"pending", "accepting", "conflicted"}
            add(
                stage_host=row["stage_host"],
                stage_root=row["stage_root"],
                owner_ref=f"artifact_revision_candidates:{row['candidate_id']}",
                must_exist=unresolved,
                protect_from_cleanup=unresolved,
            )
            source_required = unresolved and bool(row["source_stage_required"])
            add(
                stage_host=row["source_stage_host"],
                stage_root=row["source_stage_root"],
                owner_ref=f"artifact_revision_sources:{row['candidate_id']}",
                must_exist=source_required,
                protect_from_cleanup=source_required,
            )

        return tuple(
            RunStageLifecycleRecord(
                stage_host=host,
                stage_root=root,
                owner_refs=tuple(sorted(aggregate.owner_refs)),
                must_exist=aggregate.must_exist,
                protect_from_cleanup=aggregate.protect_from_cleanup,
            )
            for (host, root), aggregate in sorted(aggregates.items())
        )

    def protected_run_stage_roots(self, stage_host: str) -> tuple[str, ...]:
        """Return exact stages whose durable lifecycle still depends on them."""

        if not isinstance(stage_host, str):
            raise ValueError("run-stage protection requires one execution host")
        return tuple(
            record.stage_root
            for record in self.run_stage_lifecycles()
            if record.stage_host == stage_host and record.protect_from_cleanup
        )

    def request_agent_task_pause(
        self,
        operation_id: str,
        *,
        requested_by: Literal["human", "shutdown", "member_removal"] = "human",
    ) -> AgentTaskRecord:
        now = self.now()
        with self.connection() as connection:
            transition = self._transition_agent_task(
                connection,
                operation_id,
                "pausing",
                assignments=(
                    "updated_at = ?, last_activity_at = ?, phase = 'pausing', "
                    "status_message = 'Pausing at the current checkpoint.'"
                ),
                parameters=(now, now),
            )
            if requested_by == "human":
                episode = connection.execute(
                    """
                    SELECT episode.stop_requested_at, episode.ending
                    FROM graph_runs AS run
                    JOIN episodes AS episode ON episode.episode_id = run.episode_id
                    WHERE run.operation_id = ?
                    """,
                    (operation_id,),
                ).fetchone()
                if episode is not None and (
                    episode["stop_requested_at"] is not None or episode["ending"] is not None
                ):
                    raise ValueError(
                        "This task's parent episode is stopping or ended and cannot be paused."
                    )
            self._require_agent_task_transition(operation_id, transition)
            if transition.outcome == "refused":
                raise ValueError("Only a queued or running operation can be paused.")
            self._insert_agent_task_event(
                connection,
                operation_id,
                {
                    "human": "Pause requested by the human.",
                    "shutdown": "Paused for RCP shutdown or reload.",
                    "member_removal": (
                        "Pause requested because the authorizing member is being removed."
                    ),
                }[requested_by],
                level="info",
                created_at=now,
            )
        record = self.agent_task(operation_id)
        assert record is not None
        return record

    def pause_agent_task(
        self,
        operation_id: str,
        *,
        detail: str | None = None,
        result: dict[str, object] | None = None,
    ) -> None:
        now = self.now()
        detail = (
            detail or "Paused. Resume from the saved agent session, or retry from the beginning."
        )
        result_json = self._bounded_result_json(result) if result is not None else None
        with self.connection() as connection:
            transition = self._transition_agent_task(
                connection,
                operation_id,
                "paused",
                assignments=(
                    "updated_at = ?, finished_at = ?, last_activity_at = ?, "
                    "phase = 'paused', status_message = ?, error = NULL, "
                    "result_json = COALESCE(?, result_json)"
                ),
                parameters=(now, now, now, detail, result_json),
            )
            self._require_agent_task_transition(operation_id, transition)
            if transition.outcome == "refused":
                assert transition.observed_status is not None
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    self._agent_task_refusal_message("pause", transition.observed_status),
                    level="warning",
                    created_at=now,
                )
            else:
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    detail,
                    level="warning",
                    created_at=now,
                )
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "operation_paused",
                    self._bounded_receipt_payload({"status": "paused"}),
                    tier="summary",
                    created_at=now,
                )
                self._insert_auto_research_task_lifecycle_notice(
                    connection,
                    operation_id=operation_id,
                    status="paused",
                    created_at=now,
                    diagnostic=detail,
                )

    def complete_agent_task(
        self,
        operation_id: str,
        *,
        applied_revision: int | None,
        result: dict[str, object],
        remote_pid_file: str | None = None,
    ) -> None:
        now = self.now()
        result_json = self._bounded_result_json(result)
        graph_update = result.get("graph_update")
        if not isinstance(graph_update, dict):
            graph_updates = result.get("graph_updates")
            if isinstance(graph_updates, list):
                graph_update = next(
                    (item for item in reversed(graph_updates) if isinstance(item, dict)),
                    None,
                )
        graph_rejected = isinstance(graph_update, dict) and graph_update.get("status") == "rejected"
        status_message = (
            "Completed; graph update rejected." if graph_rejected else "Agent task completed."
        )
        message = (
            f"Project graph updated to revision {applied_revision}."
            if applied_revision is not None
            else "Operational work completed, but its graph update was rejected."
            if graph_rejected
            else "Agent task completed."
        )
        payload: dict[str, object] = {"status": "succeeded"}
        if applied_revision is not None:
            payload["applied_revision"] = applied_revision
        if isinstance(graph_update, dict):
            payload["graph_update_status"] = str(graph_update.get("status") or "none")
        with self.connection() as connection:
            transition = self._transition_agent_task(
                connection,
                operation_id,
                "succeeded",
                assignments=(
                    "updated_at = ?, finished_at = ?, status_message = ?, error = NULL, "
                    "applied_revision = ?, result_json = ?, phase = 'complete', "
                    "last_activity_at = ?"
                ),
                parameters=(
                    now,
                    now,
                    status_message,
                    applied_revision,
                    result_json,
                    now,
                ),
            )
            self._require_agent_task_transition(operation_id, transition)
            if transition.outcome == "refused":
                assert transition.observed_status is not None
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    self._agent_task_refusal_message("complete", transition.observed_status),
                    level="warning",
                    created_at=now,
                )
            else:
                if remote_pid_file is not None:
                    self._finish_remote_provider_pass(connection, operation_id, remote_pid_file)
                if not graph_rejected:
                    connection.execute(
                        "DELETE FROM graph_run_outputs WHERE operation_id = ?",
                        (operation_id,),
                    )
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    message,
                    level="info",
                    created_at=now,
                )
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "operation_completed",
                    self._bounded_receipt_payload(payload),
                    tier="summary",
                    created_at=now,
                )
                self._insert_auto_research_task_lifecycle_notice(
                    connection,
                    operation_id=operation_id,
                    status="succeeded",
                    created_at=now,
                )

    def fail_agent_task(
        self,
        operation_id: str,
        error: str,
        *,
        status: Literal["failed", "interrupted"] = "failed",
        result: dict[str, object] | None = None,
        failure_kind: AgentFailureKind | None = None,
        remote_pid_file: str | None = None,
    ) -> None:
        """Record a failure, keeping any output the task produced before it.

        A chat turn that answered and then had its graph change rejected has
        already earned its reply; failing must not throw that away.

        `failure_kind` is what recovery reads to decide whether another attempt
        is worth making, so the projection can offer the right next step instead
        of offering Retry for a login no retry will fix.
        """
        now = self.now()
        detail = " ".join(error.split())[:2000] or "The background agent task failed."
        result_json = self._bounded_result_json(result) if result is not None else None
        with self.connection() as connection:
            transition = self._transition_agent_task(
                connection,
                operation_id,
                status,
                assignments=(
                    "updated_at = ?, finished_at = ?, status_message = ?, error = ?, "
                    "phase = ?, last_activity_at = ?, result_json = COALESCE(?, result_json), "
                    "failure_kind = ?"
                ),
                parameters=(now, now, detail, detail, status, now, result_json, failure_kind),
            )
            self._require_agent_task_transition(operation_id, transition)
            if transition.outcome == "refused":
                assert transition.observed_status is not None
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    self._agent_task_refusal_message(
                        "interrupt" if status == "interrupted" else "fail",
                        transition.observed_status,
                    ),
                    level="warning",
                    created_at=now,
                )
            else:
                if remote_pid_file is not None:
                    self._finish_remote_provider_pass(connection, operation_id, remote_pid_file)
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    detail,
                    level="error",
                    created_at=now,
                )
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "operation_failed",
                    self._bounded_receipt_payload({"status": status, "error_length": len(detail)}),
                    tier="summary",
                    created_at=now,
                )
                self._insert_auto_research_task_lifecycle_notice(
                    connection,
                    operation_id=operation_id,
                    status=status,
                    created_at=now,
                    diagnostic=detail,
                )

    def agent_task_dispatch_was_proven_not_started(self, operation_id: str) -> bool:
        """Return whether a queued task has durable proof no worker thread began."""

        try:
            admission_intent = self.agent_task_admission_intent(operation_id)
        except ValueError:
            return False
        if admission_intent is None:
            return False
        has_new_admission = "parent_operation_id" in admission_intent
        with self.connection() as connection:
            task = connection.execute(
                "SELECT status FROM graph_runs WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if task is None or task["status"] != "queued":
                return False
            latest_attempt = connection.execute(
                """
                SELECT receipt_id, payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'operation_dispatch_attempt'
                ORDER BY receipt_id DESC LIMIT 1
                """,
                (operation_id,),
            ).fetchone()
            latest_outcome = connection.execute(
                """
                SELECT receipt_id, category, payload_json FROM graph_run_receipts
                WHERE operation_id = ? AND category IN (
                    'operation_dispatch_failed_before_start',
                    'operation_dispatch_started'
                )
                ORDER BY receipt_id DESC LIMIT 1
                """,
                (operation_id,),
            ).fetchone()
            latest_reset = connection.execute(
                """
                SELECT receipt_id FROM graph_run_receipts
                WHERE operation_id = ? AND category = 'operation_dispatch_reset'
                ORDER BY receipt_id DESC LIMIT 1
                """,
                (operation_id,),
            ).fetchone()
        if latest_reset is not None and (
            (latest_attempt is None or latest_reset["receipt_id"] > latest_attempt["receipt_id"])
            and (
                latest_outcome is None or latest_reset["receipt_id"] > latest_outcome["receipt_id"]
            )
        ):
            # A concrete owner may atomically requeue a task whose previous
            # worker was interrupted. The reset receipt is the new dispatch
            # fence: all attempts before it belong to the completed prior
            # process and cannot make this queued restart ambiguous.
            return True
        if latest_attempt is None:
            # New admission is atomically written before dispatch and its
            # permanent receipt means absence of an attempt is positive proof.
            # Legacy operation_created receipts predate that retention guarantee,
            # so a missing attempt is ambiguous and cannot authorize retry.
            if latest_outcome is not None:
                return False
            return has_new_admission
        attempt_id = self._dispatch_attempt_id(latest_attempt["payload_json"])
        if attempt_id is None or latest_outcome is None:
            return False
        outcome_id = self._dispatch_attempt_id(latest_outcome["payload_json"])
        if outcome_id is None:
            return False
        return (
            latest_outcome["category"] == "operation_dispatch_failed_before_start"
            and outcome_id == attempt_id
        )

    @staticmethod
    def _dispatch_attempt_id(payload_json: str) -> str | None:
        """Read a dispatch receipt ID without treating malformed JSON as proof."""

        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        dispatch_attempt_id = payload.get("dispatch_attempt_id")
        if not isinstance(dispatch_attempt_id, str) or not dispatch_attempt_id.strip():
            return None
        return dispatch_attempt_id

    def operation_ids_awaiting_remote_result(self) -> list[str]:
        """Tasks nobody is watching, whose remote pass is still outstanding.

        Narrower than what the restart sweep preserves, and deliberately so. That
        set includes a turn a live worker is streaming right now: its pass is
        unresolved because it has not finished, not because it was abandoned. A
        reconciler let loose on those would race the worker to finalize the same
        task the moment a provider stopped before its consumer wrote the stop
        down. The durable phase is what says no one is watching.
        """

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT operation_id FROM graph_runs
                WHERE phase = 'awaiting_remote_result'
                  AND status IN ('queued', 'running', 'pausing')
                ORDER BY operation_id
                """
            ).fetchall()
        outstanding = self._supervised_remote_pass_operation_ids()
        return [str(row["operation_id"]) for row in rows if str(row["operation_id"]) in outstanding]

    def claim_recorded_finalization(self, operation_id: str) -> bool:
        """Take sole ownership of finalizing this task, or report someone else has.

        A pass receipt describes a remote process. It does not say who may settle
        the task, and two settlers would apply one turn twice. This moves the
        durable phase in a single statement, so exactly one caller sees it move.
        """

        now = self.now()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE graph_runs
                SET phase = 'finalizing_recorded_result', updated_at = ?
                WHERE operation_id = ? AND phase = 'awaiting_remote_result'
                """,
                (now, operation_id),
            ).rowcount
        return changed == 1

    def release_recorded_finalization(self, operation_id: str) -> None:
        """Hand the claim back when finalization did not settle the task."""

        now = self.now()
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE graph_runs
                SET phase = 'awaiting_remote_result', updated_at = ?
                WHERE operation_id = ? AND phase = 'finalizing_recorded_result'
                """,
                (now, operation_id),
            )

    def _supervised_remote_pass_operation_ids(self) -> set[str]:
        """Tasks whose provider may still be working under a journal on its host.

        The two preserved sets mean opposite things and both have to survive a
        restart. One is work proven never to have started. This is work that may
        well have finished: the process watching it is the one that died, and its
        result is sitting on a host waiting to be read. Interrupting these would
        throw away exactly what this design exists to keep.
        """

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT started.operation_id
                FROM graph_run_receipts AS started
                JOIN graph_runs AS run ON run.operation_id = started.operation_id
                WHERE started.category = 'remote_provider_started'
                  AND json_extract(started.payload_json, '$.supervised') = 1
                  AND run.status IN ('queued', 'running', 'pausing')
                  AND NOT EXISTS (
                      SELECT 1 FROM graph_run_receipts AS stopped
                      WHERE stopped.category = 'remote_provider_stopped'
                        AND stopped.operation_id = started.operation_id
                        AND json_extract(stopped.payload_json, '$.pid_file') =
                            json_extract(started.payload_json, '$.pid_file')
                  )
                """
            ).fetchall()
        return {str(row["operation_id"]) for row in rows}

    def interrupt_active_agent_tasks(
        self,
        *,
        preserve_operation_ids: set[str] | None = None,
    ) -> None:
        now = self.now()
        detail = (
            "RCP restarted before this operation finished. Resume from its saved session "
            "when available, or retry from the beginning."
        )
        preserved = sorted(
            {
                *(
                    operation_id
                    for operation_id in (preserve_operation_ids or set())
                    if self.agent_task_dispatch_was_proven_not_started(operation_id)
                ),
                *self._supervised_remote_pass_operation_ids(),
            }
        )
        preserve_clause = ""
        preserve_arguments: tuple[str, ...] = ()
        if preserved:
            placeholders = ",".join("?" for _ in preserved)
            preserve_clause = f" AND operation_id NOT IN ({placeholders})"
            preserve_arguments = tuple(preserved)
        waiting = sorted(self._supervised_remote_pass_operation_ids())
        active_statuses = tuple(sorted(AGENT_TASK_TRANSITIONS["interrupted"]))
        active_placeholders = ",".join("?" for _ in active_statuses)
        active_clause = f"status IN ({active_placeholders}){preserve_clause}"
        interrupted: list[str] = []
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if waiting:
                # These kept their status because their provider may still be
                # working. Say so, so nothing reads the spinner as a worker this
                # process is running: there is no local worker, only a host with
                # the answer on it.
                connection.execute(
                    f"""
                    UPDATE graph_runs
                    SET phase = 'awaiting_remote_result', status_message = ?, updated_at = ?
                    WHERE operation_id IN ({",".join("?" for _ in waiting)})
                    """,
                    (
                        "Waiting for the remote result of a turn RCP stopped watching.",
                        now,
                        *waiting,
                    ),
                )
            interrupted = [
                str(row["operation_id"])
                for row in connection.execute(
                    f"SELECT operation_id FROM graph_runs WHERE {active_clause}",
                    (*active_statuses, *preserve_arguments),
                ).fetchall()
            ]
            connection.execute(
                f"""
                UPDATE graph_runs
                SET status = 'interrupted', updated_at = ?, finished_at = ?,
                    status_message = ?, error = ?, phase = 'interrupted', last_activity_at = ?
                WHERE {active_clause}
                """,
                (
                    now,
                    now,
                    detail,
                    detail,
                    now,
                    *active_statuses,
                    *preserve_arguments,
                ),
            )
            for operation_id in interrupted:
                self._insert_auto_research_task_lifecycle_notice(
                    connection,
                    operation_id=operation_id,
                    status="interrupted",
                    created_at=now,
                    diagnostic=detail,
                )
                self._insert_agent_task_event(
                    connection,
                    operation_id,
                    detail,
                    level="warning",
                    created_at=now,
                )
                self._insert_agent_task_receipt(
                    connection,
                    operation_id,
                    "operation_interrupted",
                    self._bounded_receipt_payload(
                        {"status": "interrupted", "reason": "process_restart"}
                    ),
                    tier="summary",
                    created_at=now,
                )

    def prune_operational_storage(self, *, now: datetime | None = None) -> dict[str, int]:
        """Age out bulky run payloads. `graph_runs` rows are never deleted, so
        resume ancestry (invariant 10b) stays walkable for the life of a project."""

        current = _result_view_reference_time(now)
        inactive = """
            operation_id NOT IN (
                SELECT operation_id FROM graph_runs
                WHERE status IN ('queued', 'running', 'pausing')
            )
        """
        patch_cutoff = (current - timedelta(days=PATCH_OUTPUT_RETENTION_DAYS)).isoformat()
        trace_cutoff = (current - timedelta(days=RUN_TRACE_RETENTION_DAYS)).isoformat()
        with self.connection() as connection:
            expired_result_views = self._delete_expired_result_views_from_connection(
                connection,
                current,
            )
            outputs = connection.execute(
                f"DELETE FROM graph_run_outputs WHERE created_at < ? AND {inactive}",
                (patch_cutoff,),
            ).rowcount
            events = connection.execute(
                f"""
                DELETE FROM graph_run_events
                WHERE event_kind = 'message' AND created_at < ? AND {inactive}
                """,
                (trace_cutoff,),
            ).rowcount
            # Summary receipts carry the resume freshness proof (`operation_created`,
            # `chat_context_assembled`); only the bulky lower tiers age out.
            receipts = connection.execute(
                f"""
                DELETE FROM graph_run_receipts
                WHERE created_at < ? AND tier IN ('diagnostic', 'trace') AND {inactive}
                """,
                (trace_cutoff,),
            ).rowcount

            writing_cutoff = current - timedelta(days=WRITING_SESSION_RETENTION_DAYS)
            writing_rows = connection.execute(
                """
                SELECT native_session_id, project_id, last_resumed_at
                FROM writing_sessions
                ORDER BY project_id, last_resumed_at DESC
                """
            ).fetchall()
            delete_writing: list[str] = []
            writing_by_project: dict[str, list[sqlite3.Row]] = {}
            for row in writing_rows:
                writing_by_project.setdefault(str(row["project_id"]), []).append(row)
            for rows in writing_by_project.values():
                for index, row in enumerate(rows):
                    resumed_at = self._parse_time(row["last_resumed_at"])
                    if (
                        index >= WRITING_SESSIONS_PER_PROJECT
                        and resumed_at is not None
                        and resumed_at < writing_cutoff
                    ):
                        delete_writing.append(str(row["native_session_id"]))
            for session_id in delete_writing:
                connection.execute(
                    "DELETE FROM writing_sessions WHERE native_session_id = ?", (session_id,)
                )

        return {
            "outputs": outputs,
            "events": events,
            "receipts": receipts,
            "writing_sessions": len(delete_writing),
            "result_views": expired_result_views,
        }

    @staticmethod
    def _chat_session_context_row(
        connection: sqlite3.Connection,
        provider: str,
        execution_machine: str,
        native_session_id: str,
    ) -> sqlite3.Row | None:
        rows = connection.execute(
            "SELECT * FROM chat_session_contexts WHERE native_session_id = ?",
            (native_session_id,),
        ).fetchall()
        conflicts = [
            row
            for row in rows
            if row["provider"] != provider or row["execution_machine"] != execution_machine
        ]
        if conflicts:
            raise ValueError(
                "Chat session context provider or execution-machine conflict for native session."
            )
        return next(
            (
                row
                for row in rows
                if row["provider"] == provider and row["execution_machine"] == execution_machine
            ),
            None,
        )

    @staticmethod
    def _validate_chat_session_context_binding(
        row: sqlite3.Row,
        *,
        project_id: str,
        kind: Literal["node_chat", "project_chat"],
        chat_id: str,
        node_id: str | None,
    ) -> None:
        expected = {
            "project_id": project_id,
            "kind": kind,
            "chat_id": chat_id,
            "node_id": node_id,
        }
        conflicts = [name for name, value in expected.items() if row[name] != value]
        if conflicts:
            raise ValueError(
                "Chat session context immutable binding conflict: " + ", ".join(conflicts)
            )
