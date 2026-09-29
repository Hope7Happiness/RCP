from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future
from contextlib import AsyncExitStack, aclosing, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from rcp.agents.credential_gate import ProviderCredentialGate, remaining_startup_hold
from rcp.agents.failure_kinds import AgentFailureKind, transport_failure
from rcp.agents.git_access import ProviderGitAccess
from rcp.agents.invocation_broker import ProviderInvocationGate
from rcp.agents.provider_accounts import ProviderAccounts
from rcp.agents.provider_environment import ProviderCredentialStore, ProviderProcessEnvironment
from rcp.agents.schema import EXPERIMENT_WATCH_OUTPUT_GLOB
from rcp.agents.steering import LiveProviderSteering
from rcp.agents.write_scope import ProjectWriteScope
from rcp.artifacts import AgentArtifactDescriptor
from rcp.limits import (
    HERDR_NATIVE_PROMPT_START_TIMEOUT_SECONDS,
    HERDR_NATIVE_RECEIPT_POLL_SECONDS,
    PROVIDER_CREDENTIAL_STARTUP_MIN_HOLD_SECONDS,
    PROVIDER_STDERR_DRAIN_TIMEOUT_SECONDS,
    REMOTE_PROVIDER_KILL_WAIT_SECONDS,
    REMOTE_PROVIDER_PID_WAIT_SECONDS,
    REMOTE_PROVIDER_STOP_POLL_SECONDS,
    REMOTE_PROVIDER_STOP_TIMEOUT_SECONDS,
    REMOTE_PROVIDER_TERM_WAIT_SECONDS,
    TURN_JOURNAL_MAX_BYTES,
    TURN_JOURNAL_MAX_CONTROL_MESSAGES,
    TURN_JOURNAL_MAX_EVENT_BYTES,
    TURN_JOURNAL_MAX_EXPERIMENT_WATCH_BYTES,
    TURN_JOURNAL_MAX_EXPERIMENT_WATCH_FILES,
    TURN_JOURNAL_MAX_PATCH_BYTES,
    TURN_JOURNAL_MAX_STDERR_BYTES,
    TURN_JOURNAL_MAX_UPLINK_BYTES,
)
from rcp.providers import (
    AgentCapability,
    ModelChoice,
    ProviderId,
    ProviderRuntimeChoice,
    ProviderSteeringState,
    ProviderSteerReceipt,
    ProviderTurnRequest,
    ProviderUsage,
    profile_for,
)
from rcp.storage.models import ProviderLoginStateRecord, ProviderReadinessSnapshotRecord
from rcp.transport.remote_terminate_provider import ABSENT as REMOTE_PROBE_ABSENT
from rcp.transport.ssh import ssh_arguments
from rcp.transport.state import StateUnreachable, _remote_script

logger = logging.getLogger(__name__)

ProviderPathState = Literal[
    "resolved",
    "missing",
    "denied",
    "unconfigured",
    "unreachable",
]

_EXECUTION_ACCOUNT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,127}")


_REMOTE_PATH_MISSING = 40
_REMOTE_PATH_DENIED = 41
_REMOTE_PATH_NOT_FILE = 42
_REMOTE_PATH_NOT_EXECUTABLE = 43
_REMOTE_PATH_INSPECTION_FAILED = 44
_REMOTE_PATH_PROBE = (
    "import os, stat, sys\n"
    "try:\n"
    "    mode = os.stat(sys.argv[1]).st_mode\n"
    "except FileNotFoundError:\n"
    f"    raise SystemExit({_REMOTE_PATH_MISSING})\n"
    "except PermissionError:\n"
    f"    raise SystemExit({_REMOTE_PATH_DENIED})\n"
    "except OSError:\n"
    f"    raise SystemExit({_REMOTE_PATH_INSPECTION_FAILED})\n"
    "if not stat.S_ISREG(mode):\n"
    f"    raise SystemExit({_REMOTE_PATH_NOT_FILE})\n"
    "if not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):\n"
    f"    raise SystemExit({_REMOTE_PATH_NOT_EXECUTABLE})\n"
    "if not os.access(sys.argv[1], os.X_OK):\n"
    f"    raise SystemExit({_REMOTE_PATH_DENIED})\n"
)


class ProviderReadiness(BaseModel):
    provider: ProviderId
    #: The registry's display name, so no surface has to map an id to a label.
    label: str = ""
    installed: bool
    authenticated: bool
    version: str | None = None
    reason: str | None = None
    #: None means the profile has no work-like probe or it could not be checked.
    work_like_available: bool | None = None
    work_like_reason: str | None = None
    #: The exact executable checked. For an unconfigured provider this is the
    #: absolute candidate discovery found and used for a best-effort launch;
    #: a project manifest may save it as a stable pin.
    binary_path: str | None = None
    path_state: ProviderPathState = "resolved"
    #: `unreachable` because ssh itself ran and exited 255, the one unreachable
    #: a reattempt may fix. An ssh that could not start or gave no answer in
    #: time is unreachable too, but not this. Read by launch classification only.
    link_lost: bool = Field(default=False, exclude=True)
    #: What this CLI will actually accept, probed where it can enumerate and
    #: declared where it cannot. Empty when the provider is unreachable, which
    #: leaves the UI showing the saved manifest values.
    models: list[ModelChoice] = []
    runtimes: list[ProviderRuntimeChoice] = []
    #: The runtime an omitted manifest value resolves to. Selection surfaces read
    #: this rather than assuming a position inside `runtimes`.
    default_runtime: str = ""

    @model_validator(mode="after")
    def fill_provider_runtimes(self) -> ProviderReadiness:
        profile = profile_for(self.provider)
        if not self.runtimes:
            self.runtimes = list(profile.runtime_choices)
        if not self.default_runtime:
            self.default_runtime = profile.default_runtime
        return self


def work_like_launch_problem(readiness: object) -> str | None:
    """The one reason a Work-like launch is refused on readiness grounds.

    Launch, `rcp server provider check`, and Auto-research Retry admission all
    consult this, so a host whose CLI will not accept RCP's enforced settings is
    refused before a task is allocated rather than after its stream begins.
    `None` means launch may proceed; an unchecked probe is not a refusal.
    """

    if getattr(readiness, "work_like_available", None) is False:
        return getattr(readiness, "work_like_reason", None) or (
            "Provider Work readiness is unavailable."
        )
    reason = getattr(readiness, "work_like_reason", None)
    return reason or None


class ProviderExecutionAccount(BaseModel):
    """The nonsecret OS identity reached by the provider launch transport."""

    host: str
    reachable: bool
    os_account: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def identity_matches_reachability(self) -> ProviderExecutionAccount:
        if self.reachable != (self.os_account is not None):
            raise ValueError("reachable execution accounts require one observed account")
        if self.reachable and self.reason is not None:
            raise ValueError("a reachable execution account cannot carry a failure reason")
        if not self.reachable and not self.reason:
            raise ValueError("an unreachable execution account requires a reason")
        return self


class AgentEvent(BaseModel):
    # `answer` is the provider's final assistant message. `message` is any other
    # text the provider emitted on the way there — reasoning, tool output, item
    # summaries. Chat reads only `answer`, so a trace can never be mistaken for
    # the reply.
    event: Literal[
        "session",
        "message",
        "answer",
        "artifact",
        "raw",
        "error",
        "paused",
        "done",
        # Internal durable evidence emitted immediately before the selected
        # runtime can deliver this invocation's provider prompt.
        "runtime",
        # Internal process ownership receipts; these convey no prompt authority.
        "remote_process_start",
        "remote_process_stop",
        "herdr_binding_start",
        "herdr_binding_stop",
        # The run connection ended after the execution host accepted a
        # supervised turn. The original task now waits for that host's journal.
        "remote_result_pending",
        # Internal diagnostic emitted when a runtime failed before it could have
        # delivered the prompt and another candidate is about to be tried. API
        # pumps record it instead of forwarding it as UI text.
        "runtime_fallback",
        # Internal orchestration evidence emitted immediately after the provider
        # process exits. API pumps consume it instead of forwarding it as UI text.
        "provider_exit",
    ]
    text: str = ""
    session_id: str | None = None
    artifact: AgentArtifactDescriptor | None = None
    usage: ProviderUsage | None = None
    #: Typed cause on an `error` the launcher can name itself. Set only for a
    #: link lost before the provider started; a provider process that exits
    #: leaves its code in `provider_exit` instead, and classification reads
    #: that. Never inferred from text.
    failure_kind: AgentFailureKind | None = None


def _supervised_remote_turn_command(
    command: list[str],
    *,
    supervisor_path: str,
    pid_file: str,
    provider: str,
    runtime_id: str,
    provider_version: str | None,
    patch_path: str,
    watch_path: str,
    experiment_watch_glob: str,
    close_input_after_initial: bool,
) -> list[str]:
    """Wrap one remote provider pass in the execution-host journal."""

    wrapped = [
        "python3",
        supervisor_path,
        "--pid-file",
        pid_file,
        "--provider",
        provider,
        "--runtime-id",
        runtime_id,
        "--patch-path",
        patch_path,
        "--watch-path",
        watch_path,
        "--experiment-watch-glob",
        experiment_watch_glob,
        "--max-journal-bytes",
        str(TURN_JOURNAL_MAX_BYTES),
        "--max-event-bytes",
        str(TURN_JOURNAL_MAX_EVENT_BYTES),
        "--max-stderr-bytes",
        str(TURN_JOURNAL_MAX_STDERR_BYTES),
        "--max-patch-bytes",
        str(TURN_JOURNAL_MAX_PATCH_BYTES),
        "--max-uplink-bytes",
        str(TURN_JOURNAL_MAX_UPLINK_BYTES),
        "--max-control-messages",
        str(TURN_JOURNAL_MAX_CONTROL_MESSAGES),
        "--max-experiment-watch-files",
        str(TURN_JOURNAL_MAX_EXPERIMENT_WATCH_FILES),
        "--max-experiment-watch-bytes",
        str(TURN_JOURNAL_MAX_EXPERIMENT_WATCH_BYTES),
        "--stop-hold-seconds",
        str(PROVIDER_CREDENTIAL_STARTUP_MIN_HOLD_SECONDS),
        "--stop-grace-seconds",
        str(REMOTE_PROVIDER_TERM_WAIT_SECONDS),
        "--poll-seconds",
        str(REMOTE_PROVIDER_STOP_POLL_SECONDS),
    ]
    if provider_version:
        wrapped.extend(("--provider-version", provider_version))
    if close_input_after_initial:
        wrapped.append("--close-input-after-initial")
    return [*wrapped, "--", *command]


class AgentProcessControl:
    """Thread-safe pause control for one provider subprocess."""

    def __init__(self) -> None:
        self.pause_requested = threading.Event()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._remote_host: str | None = None
        self._remote_pid_file: str | None = None
        self._steering: LiveProviderSteering | None = None
        self._started_at: float | None = None

    def steering_state(self) -> ProviderSteeringState:
        with self._lock:
            steering = self._steering
        if steering is None:
            return ProviderSteeringState(False, "No live provider process owns this attempt.")
        return steering.state()

    def steer(
        self, expected_turn_id: str, message_id: str, text: str
    ) -> Future[ProviderSteerReceipt]:
        with self._lock:
            steering = self._steering
            loop = self._loop
            if steering is not None and loop is not None and not loop.is_closed():
                return asyncio.run_coroutine_threadsafe(
                    steering.send(expected_turn_id, message_id, text), loop
                )
        refused: Future[ProviderSteerReceipt] = Future()
        refused.set_result(
            ProviderSteerReceipt("refused", "No live provider process owns this attempt.")
        )
        return refused

    def attach_steering(self, steering: LiveProviderSteering) -> None:
        with self._lock:
            self._steering = steering

    def configure_remote_termination(self, host: str, pid_file: str) -> None:
        with self._lock:
            self._remote_host = host
            self._remote_pid_file = pid_file

    def request_pause(self) -> None:
        self.pause_requested.set()
        with self._lock:
            loop = self._loop
            process = self._process
            remote_host = self._remote_host
            remote_pid_file = self._remote_pid_file
            started_at = self._started_at
        if remote_host and remote_pid_file:
            threading.Thread(
                target=self._terminate_remote_after_hold,
                args=(remote_host, remote_pid_file, started_at),
                name="rcp-remote-pause",
                daemon=True,
            ).start()
        if (
            loop is not None
            and process is not None
            and started_at is not None
            and not loop.is_closed()
        ):
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._terminate(process, started_at))
            )

    def attach(self, process: asyncio.subprocess.Process) -> None:
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._process = process
            self._started_at = time.monotonic()
            started_at = self._started_at
        if self.pause_requested.is_set():
            asyncio.create_task(self._terminate(process, started_at))

    def restart_hold(self, started_at: float) -> None:
        """The remote provider started later than its SSH client; hold from then."""

        with self._lock:
            if self._process is not None:
                self._started_at = started_at

    def detach(self, process: asyncio.subprocess.Process) -> None:
        with self._lock:
            if self._process is process:
                self._steering = None
                self._process = None
                self._loop = None

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process, started_at: float) -> None:
        """Stop the local process group, never inside the startup hold.

        Every termination path passes the time the process was spawned: a
        provider signalled while it refreshes its login spends the single-use
        refresh token, so a young process is left alone until the hold has passed.
        """

        if process.returncode is not None:
            return
        if (remaining := remaining_startup_hold(started_at)) > 0:
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=remaining)
        if process.returncode is not None:
            return
        # A reaped child's pid can already belong to someone else, and signalling
        # a group that is no longer ours fails with EPERM rather than ESRCH.
        # Both mean this process is gone; killing the stranger would be worse.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        except TimeoutError:
            pass
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()

    @staticmethod
    def remote_stopped(
        host: str,
        pid_file: str,
        *,
        raise_unreachable: bool = False,
        absent_is_stopped: bool = False,
    ) -> bool | None:
        """Observe the exact remote process group; unavailable is not stopped.

        With `absent_is_stopped`, a host reporting no pidfile inside a standing
        stage is stopped rather than unknown: the wrapper writes that file before
        it execs anything and nothing in RCP ever removes one, so its absence
        says this pass started no process. Only a caller that knows the launch is
        over may ask for that. While a launch is still in flight the pidfile may
        simply not have been written yet, and reading that as a stop would let a
        provider start immediately after RCP decided nothing was running.

        Deliberately on the shared connection, not the run's. This has to reach
        the host at the moment the run's own connection may be what died, and a
        shared path is the only one OpenSSH reopens by itself. Giving it the
        run's partition would leave the provider running with nothing able to
        stop it. `test_provider_turn_rides_the_master_of_its_own_run` fails if
        this or `_terminate_remote` ever takes one.
        """
        stopped, _identity = AgentProcessControl.remote_process_state(
            host,
            pid_file,
            raise_unreachable=raise_unreachable,
            absent_is_stopped=absent_is_stopped,
        )
        return stopped

    @staticmethod
    def remote_process_state(
        host: str,
        pid_file: str,
        *,
        raise_unreachable: bool = False,
        absent_is_stopped: bool = False,
    ) -> tuple[bool | None, str | None]:
        """Observe absence and, for a live supervised group, its process identity.

        `None` covers every way the probe could not answer. With
        `raise_unreachable`, the one case ssh itself reports, exit 255, raises
        `StateUnreachable` instead, so a caller that fails a task on it can
        name the lost link rather than an unverifiable process.
        """

        command = [
            "python3",
            "-c",
            _remote_script("remote_terminate_provider.py"),
            "--probe",
            pid_file,
        ]
        try:
            result = subprocess.run(
                ssh_arguments(host, shlex.join(command)),
                capture_output=True,
                text=True,
                timeout=REMOTE_PROVIDER_STOP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        if raise_unreachable and result.returncode == 255:
            raise StateUnreachable(
                f"{host} is unreachable, so the previous provider call could not be checked."
            )
        if result.returncode == REMOTE_PROBE_ABSENT:
            # The wrapper writes its pidfile before it execs anything, so a host
            # that can see there is no pidfile is telling RCP no process was ever
            # started here. Reading that as "unknown" is what turned one failed
            # launch into a conversation that could never run again -- but only a
            # caller that knows the launch is over may read it that way.
            return (True, None) if absent_is_stopped else (None, None)
        stopped = {0: True, 1: False}.get(result.returncode)
        identity = None
        if stopped is False:
            with suppress(json.JSONDecodeError, TypeError, ValueError):
                payload = json.loads(result.stdout)
                if isinstance(payload, dict) and isinstance(payload.get("identity"), str):
                    identity = payload["identity"]
        return stopped, identity

    @staticmethod
    def _confirm_remote_stopped(
        host: str, pid_file: str, started_at: float, *, launch_ended: bool = False
    ) -> bool:
        """Settle this newly spawned pass before allowing another runtime or turn.

        `launch_ended` says the local SSH process has already exited, which is
        what makes a missing pidfile mean the wrapper never wrote one. While the
        launch is still in flight it may only be late, so absence stays unknown.
        """
        return AgentProcessControl.remote_stopped(
            host, pid_file, absent_is_stopped=launch_ended
        ) is True or (
            AgentProcessControl._terminate_remote_after_hold(
                host, pid_file, started_at, absent_is_stopped=launch_ended
            )
        )

    @classmethod
    def _terminate_remote_after_hold(
        cls,
        host: str,
        pid_file: str,
        started_at: float | None,
        *,
        absent_is_stopped: bool = False,
    ) -> bool:
        """The remote counterpart of `_terminate`; `None` means nothing was spawned yet."""

        if started_at is not None and (remaining := remaining_startup_hold(started_at)) > 0:
            time.sleep(remaining)
        return cls._terminate_remote(host, pid_file, absent_is_stopped=absent_is_stopped)

    @classmethod
    def stop_remote_process(
        cls,
        host: str,
        pid_file: str,
        *,
        expected_identity: str,
    ) -> bool:
        """Stop a detached group only while it is still the one just observed."""

        if not expected_identity:
            return False
        return cls._terminate_remote(host, pid_file, expect_identity=expected_identity)

    @staticmethod
    def _terminate_remote(
        host: str,
        pid_file: str,
        expect_identity: str | None = None,
        *,
        absent_is_stopped: bool = False,
    ) -> bool:
        # Shared connection on purpose; see `remote_stopped`.
        command = [
            "python3",
            "-c",
            _remote_script("remote_terminate_provider.py"),
            pid_file,
            str(REMOTE_PROVIDER_PID_WAIT_SECONDS),
            str(REMOTE_PROVIDER_TERM_WAIT_SECONDS),
            str(REMOTE_PROVIDER_KILL_WAIT_SECONDS),
            str(REMOTE_PROVIDER_STOP_POLL_SECONDS),
        ]
        if expect_identity is not None:
            command.append(expect_identity)
        try:
            result = subprocess.run(
                ssh_arguments(host, shlex.join(command)),
                capture_output=True,
                text=True,
                timeout=REMOTE_PROVIDER_STOP_TIMEOUT_SECONDS,
                check=False,
            )
            # An active stop only counts a confirmed stop. A pidfile that has
            # not appeared yet is not a pass that never started.
            settled = {0, REMOTE_PROBE_ABSENT} if absent_is_stopped else {0}
            return result.returncode in settled
        except (OSError, subprocess.TimeoutExpired):
            return False


class ProviderReadinessSnapshots(Protocol):
    """The durable readiness answers the launcher reuses; `AppStore` implements it."""

    def provider_readiness_snapshot(
        self, provider: str, host: str, binary: str
    ) -> ProviderReadinessSnapshotRecord | None: ...

    def save_provider_readiness_snapshot(self, record: ProviderReadinessSnapshotRecord) -> None: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class _ReadinessProbe:
    """One process-local probe shared by concurrent callers."""

    completed: threading.Event = field(default_factory=threading.Event)
    result: ProviderReadiness | None = None
    error: BaseException | None = None


class _PrePromptRuntimeFailure(RuntimeError):
    """A provider runtime ended before it could have accepted RCP's prompt."""


def _discover_local_provider(provider: str) -> str | None:
    discovered = shutil.which(provider)
    if discovered:
        # Keep the command path stable across provider-native updates. Native
        # installers commonly replace a symlink target with a versioned binary;
        # persisting the resolved target would pin RCP to the old version.
        return str(Path(discovered))
    try:
        account_home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    except KeyError:
        return None
    candidate = account_home / ".local" / "bin" / provider
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


class _ProbeNoVerdict(subprocess.CompletedProcess):
    """A probe ssh gave no verdict on: it could not start, or RCP stopped waiting.

    Its 255 is RCP's own, so the probe reads as failed everywhere without ever
    being taken for ssh's word that the link is gone.
    """


def _link_lost(result: subprocess.CompletedProcess[str]) -> bool:
    """Whether ssh itself ran to completion and exited 255: the one code that names a lost link."""

    return result.returncode == 255 and not isinstance(result, _ProbeNoVerdict)


def _unreachable_reason(probe: subprocess.CompletedProcess[str], *, host: str, checked: str) -> str:
    if _link_lost(probe):
        return f"{host} is unreachable, so {checked} could not be checked."
    return f"{checked} on {host} could not be checked: " + (probe.stderr.strip() or "unknown error")


def _unreachable_readiness(
    provider: str,
    probe: subprocess.CompletedProcess[str],
    *,
    host: str,
    binary_path: str | None = None,
) -> ProviderReadiness:
    """The answer when a remote probe of one readiness check exited 255.

    Discovery, version, auth, catalog, and Work probes can each be the one that
    finds the link gone. They all say so the same way, and only a probe ssh ran
    to a verdict marks the loss a reattempt may fix; one that could not start,
    or hung on a live link, is a failure the same reattempt would meet again.
    """

    return ProviderReadiness(
        provider=provider,
        label=profile_for(provider).label,
        installed=False,
        authenticated=False,
        binary_path=binary_path,
        path_state="unreachable",
        link_lost=_link_lost(probe),
        reason=_unreachable_reason(probe, host=host, checked=binary_path or provider),
    )


def _native_binary_matches(pid: int, binary: str) -> bool:
    """Bind Herdr's foreground group to the executable RCP checked."""

    if not sys.platform.startswith("linux"):
        return True
    executable = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    expected = Path(binary).resolve()
    if executable == expected:
        return True
    # The npm Codex launcher is a Node script; Herdr's foreground group is
    # led by Node, while the native Codex binary runs inside that group.
    if executable.name == "node":
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return len(argv) > 1 and Path(os.fsdecode(argv[1])).resolve() == expected
    return False


class AgentLauncher:
    # Consume pipes in small chunks so asyncio never has to buffer one complete
    # provider event. Final graph patches may be large, but tool/read events
    # beyond the explicit per-event bound are diagnostic noise and are drained.
    _STREAM_LIMIT = 64 * 1024
    _MAX_EVENT_BYTES = 16 * 1024 * 1024
    _MAX_STDERR_BYTES = 1024 * 1024

    def __init__(
        self,
        login_state: Callable[[str, str], ProviderLoginStateRecord] | None = None,
        *,
        credentials: ProviderCredentialStore | None = None,
        readiness_snapshots: ProviderReadinessSnapshots | None = None,
        accounts: ProviderAccounts | None = None,
    ) -> None:
        #: The account owner shared with sign-in and skill probing. Given, it
        #: answers refusals and classifies failures; without it the launcher
        #: knows only the raw login row and whatever credential store it got.
        self.accounts = accounts
        if accounts is not None:
            login_state = login_state or accounts.store.provider_login_state
            credentials = accounts.credentials
        self.login_state = login_state
        #: Where a Claude setup token lives; None means every provider inherits
        #: RCP's own environment, as before a token was ever pasted.
        self.credentials = credentials
        #: Durable credential-touching readiness answers, keyed by exact
        #: executable and version, so a restart re-probes nothing unchanged.
        self.readiness_snapshots = readiness_snapshots
        self._readiness_lock = threading.Lock()
        self._readiness_cache: dict[tuple[str, str, str | None], ProviderReadiness] = {}
        self._readiness_probes: dict[tuple[str, str, str | None, bool], _ReadinessProbe] = {}
        self._readiness_generations: dict[tuple[str, str, str | None], int] = {}
        #: Shared so every process that can rotate this login is staggered,
        #: not only task turns.
        self.credential_gate = ProviderCredentialGate()

    def process_environment(self, provider: str, host: str) -> ProviderProcessEnvironment:
        """The environment for one provider process; every Claude start goes through it."""

        if self.credentials is None:
            environment = ProviderProcessEnvironment()
            return (
                environment.with_claude_foreground_tasks(remote=bool(host))
                if provider == "claude"
                else environment
            )
        return profile_for(provider).authentication.process_environment(self.credentials, host)

    def _login_refusal(self, provider: str, host: str) -> str | None:
        if self.accounts is not None:
            return self.accounts.refusal(provider, host)
        state = self.login_state(provider, host) if self.login_state is not None else None
        if state is None or state.state != "signed_out":
            return None
        return (
            f"{profile_for(provider).label} was signed out at {state.changed_at}: "
            f"{state.detail or 'The provider rejected its login'}. "
            "Open Settings, Provider logins to sign in and verify."
        )

    def _observe_probe_failure(
        self, provider: str, host: str, result: subprocess.CompletedProcess[str], generation: int
    ) -> bool:
        evidence = profile_for(provider).probe_failure_evidence(result)
        if self.accounts is not None:
            return self.accounts.observe_failure(
                provider, host, generation=generation, evidence=evidence, source="probe"
            )
        return profile_for(provider).credential_failure(evidence)

    def _with_login_state(self, readiness: ProviderReadiness, host: str) -> ProviderReadiness:
        reason = self._login_refusal(readiness.provider, host)
        if reason is not None:
            return readiness.model_copy(update={"authenticated": False, "reason": reason})
        return readiness

    def readiness(
        self,
        provider: str,
        *,
        host: str = "",
        binary: str | None = None,
        refresh: bool = False,
    ) -> ProviderReadiness:
        """Return one app-scoped capability, probing only when it is not known.

        Configured capabilities are keyed by their exact executable. Discovery
        without a configured path is a separate entry; an installed and
        authenticated discovered executable is still launchable, while the
        ``unconfigured`` state tells settings that no stable path is saved yet.
        """

        key = (provider, host, binary)
        with self._readiness_lock:
            if not refresh and (cached := self._readiness_cache.get(key)) is not None:
                return self._with_login_state(cached.model_copy(deep=True), host)
            forced_key = (*key, True)
            probe_key = forced_key if refresh else (*key, False)
            # An ordinary caller can use a forced probe already in flight. A
            # forced caller must never inherit an ordinary warm-up generation.
            probe = self._readiness_probes.get(forced_key)
            if not refresh and probe is None:
                probe = self._readiness_probes.get(probe_key)
            owner = probe is None
            if probe is None:
                probe = _ReadinessProbe()
                if refresh:
                    self._readiness_cache.pop(key, None)
                    self._readiness_generations[key] = self._readiness_generations.get(key, 0) + 1
                self._readiness_probes[probe_key] = probe
            generation = self._readiness_generations.get(key, 0)

        if not owner:
            probe.completed.wait()
            if probe.error is not None:
                raise probe.error
            assert probe.result is not None
            return self._with_login_state(probe.result.model_copy(deep=True), host)

        try:
            result = self._readiness_uncached(provider, host=host, binary=binary, refresh=refresh)
        except BaseException as exc:
            with self._readiness_lock:
                if self._readiness_generations.get(key, 0) == generation:
                    self._readiness_cache.pop(key, None)
                self._readiness_probes.pop(probe_key, None)
                probe.error = exc
                probe.completed.set()
            raise

        with self._readiness_lock:
            # A host that did not answer is a fact about one moment, not about
            # the capability. Cached, it would fail every later launch from
            # memory, an automatic reattempt included, without asking the host.
            if (
                self._readiness_generations.get(key, 0) == generation
                and result.path_state != "unreachable"
            ):
                self._readiness_cache[key] = result.model_copy(deep=True)
            probe.result = result.model_copy(deep=True)
            self._readiness_probes.pop(probe_key, None)
            probe.completed.set()
        return self._with_login_state(result, host)

    def cached_readiness(
        self,
        provider: str,
        *,
        host: str = "",
        binary: str | None = None,
    ) -> ProviderReadiness | None:
        """Return one already-probed capability, or None rather than probing."""

        with self._readiness_lock:
            cached = self._readiness_cache.get((provider, host, binary))
        return (
            None if cached is None else self._with_login_state(cached.model_copy(deep=True), host)
        )

    def invalidate_readiness(
        self,
        provider: str,
        *,
        host: str = "",
        binary: str | None = None,
    ) -> None:
        """Forget one exact capability without disturbing other projects."""

        with self._readiness_lock:
            key = (provider, host, binary)
            self._readiness_cache.pop(key, None)
            self._readiness_generations[key] = self._readiness_generations.get(key, 0) + 1

    def execution_account(self, *, host: str = "") -> ProviderExecutionAccount:
        """Resolve the exact OS account reached by the same local or SSH route as launches."""

        if not host:
            try:
                account = pwd.getpwuid(os.geteuid()).pw_name
            except (KeyError, OSError):
                return ProviderExecutionAccount(
                    host="",
                    reachable=False,
                    reason="The local provider execution account could not be resolved.",
                )
            return ProviderExecutionAccount(host="", reachable=True, os_account=account)
        result = self._probe(host, ["id", "-un"], login_shell=False)
        if result.returncode != 0:
            return ProviderExecutionAccount(
                host=host,
                reachable=False,
                reason=f"The configured SSH route to {host} is unavailable.",
            )
        lines = result.stdout.strip().splitlines()
        account = lines[-1].strip() if len(lines) == 1 else ""
        if _EXECUTION_ACCOUNT.fullmatch(account) is None:
            return ProviderExecutionAccount(
                host=host,
                reachable=False,
                reason=f"The configured SSH route to {host} did not report one safe OS account.",
            )
        return ProviderExecutionAccount(host=host, reachable=True, os_account=account)

    def _readiness_uncached(
        self,
        provider: str,
        *,
        host: str,
        binary: str | None,
        refresh: bool = False,
    ) -> ProviderReadiness:
        profile = profile_for(provider)
        configured = binary is not None
        candidate = binary
        if configured:
            path_state, path_problem, link_lost = self._configured_path_state(binary, host=host)
            if path_state != "resolved":
                return ProviderReadiness(
                    provider=provider,
                    label=profile.label,
                    installed=False,
                    authenticated=False,
                    binary_path=binary,
                    path_state=path_state,
                    link_lost=link_lost,
                    reason=path_problem,
                )
            installed = True
        elif host:
            installed_probe = self._probe(host, ["command", "-v", provider])
            if installed_probe.returncode == 255:
                return _unreachable_readiness(provider, installed_probe, host=host)
            discovered = installed_probe.stdout.strip().splitlines()
            candidate = discovered[-1] if installed_probe.returncode == 0 and discovered else None
            installed = bool(candidate and PurePosixPath(candidate).is_absolute())
        else:
            candidate = _discover_local_provider(provider)
            installed = candidate is not None
        if not installed or candidate is None:
            where = f" on {host}" if host else ""
            reason = (
                f"No {provider} executable is recorded; the CLI is not installed "
                f"or discoverable{where}."
            )
            return ProviderReadiness(
                provider=provider,
                label=profile.label,
                installed=False,
                authenticated=False,
                path_state="unconfigured",
                reason=reason,
            )
        # `--version` needs no model request. Prepare its provider environment
        # under the account gate too, then reuse unchanged credential-touching answers.
        with self.credential_gate.hold_blocking(provider, host):
            version_environment = self.process_environment(provider, host)
            version_result = self._probe(
                host, [candidate, "--version"], environment=version_environment
            )
        if host and version_result.returncode == 255:
            return _unreachable_readiness(
                provider, version_result, host=host, binary_path=candidate
            )
        version_lines = (version_result.stdout or version_result.stderr).strip().splitlines()
        version = version_lines[-1] if version_result.returncode == 0 and version_lines else None
        path_state: ProviderPathState = "resolved" if configured else "unconfigured"
        if not refresh and version is not None and self.readiness_snapshots is not None:
            snapshot = self.readiness_snapshots.provider_readiness_snapshot(
                provider, host, candidate
            )
            if snapshot is not None and snapshot.version == version:
                stored = ProviderReadiness.model_validate_json(snapshot.readiness_json)
                return stored.model_copy(
                    update={"version": version, "binary_path": candidate, "path_state": path_state}
                )
        # Every probe below reads the login and can rotate the same token a turn
        # does. One hold covers the sequence rather than handing the credential
        # back between probes that belong to a single readiness answer.
        with self.credential_gate.hold_blocking(provider, host):
            login_reason = self._login_refusal(provider, host)
            generation = self.login_state(provider, host).generation if self.login_state else 0
            environment = self.process_environment(provider, host)
            authenticated = False
            if login_reason is None:
                auth = self._probe(host, profile.auth_command(candidate), environment=environment)
                if host and auth.returncode == 255:
                    return _unreachable_readiness(provider, auth, host=host, binary_path=candidate)
                authenticated = profile.is_authenticated(auth)
                if self._observe_probe_failure(provider, host, auth, generation):
                    authenticated = False
                    login_reason = (
                        self._login_refusal(provider, host) or "Provider sign-in is required."
                    )
            # Enumerate only once the CLI is known to answer. An unauthenticated
            # catalog probe just costs a subprocess to learn what auth already said.
            catalog_command = profile.catalog_command(candidate) if authenticated else None
            catalog = (
                self._probe(host, catalog_command, environment=environment)
                if catalog_command
                else None
            )
            if catalog is not None and host and catalog.returncode == 255:
                return _unreachable_readiness(provider, catalog, host=host, binary_path=candidate)
            if catalog is not None and self._observe_probe_failure(
                provider, host, catalog, generation
            ):
                authenticated = False
                login_reason = (
                    self._login_refusal(provider, host) or "Provider sign-in is required."
                )
            work_like_available = None
            work_like_reason = None
            work_command = profile.work_like_probe_command(candidate) if authenticated else None
            if work_command is not None:
                work_probe = self._probe(host, work_command, environment=environment)
                if host and work_probe.returncode == 255:
                    return _unreachable_readiness(
                        provider, work_probe, host=host, binary_path=candidate
                    )
                if self._observe_probe_failure(provider, host, work_probe, generation):
                    authenticated = False
                    work_like_available = False
                    login_reason = (
                        self._login_refusal(provider, host) or "Provider sign-in is required."
                    )
                    work_like_reason = login_reason
                elif work_probe.returncode == 255:
                    where = f" on {host}" if host else ""
                    work_like_reason = (
                        f"{profile.label} Work readiness could not be checked{where}: "
                        + (_meaningful_stderr(work_probe.stderr) or "provider probe unavailable.")
                    )
                else:
                    work_like_available = work_probe.returncode == 0
                    if not work_like_available:
                        work_like_reason = (
                            _meaningful_stderr(work_probe.stderr)
                            or work_probe.stdout.strip()
                            or f"{profile.label} Work readiness probe exited {work_probe.returncode}."
                        )
        result = ProviderReadiness(
            provider=provider,
            label=profile.label,
            installed=True,
            authenticated=authenticated,
            work_like_available=work_like_available,
            work_like_reason=work_like_reason,
            version=version,
            binary_path=candidate,
            path_state=path_state,
            reason=login_reason
            or (
                f"{provider} was found at {candidate}; using the discovered path until a saved path is provided."
                if authenticated and not configured
                else (
                    None
                    if authenticated
                    else f"{provider} CLI is not authenticated{f' on {host}' if host else ''}."
                )
            ),
            models=profile.models(catalog) if authenticated else [],
        )
        # A durable sign-out is folded in at read time by `_with_login_state`;
        # the snapshot keeps what the probes themselves said.
        if version is not None and self.readiness_snapshots is not None and login_reason is None:
            self.readiness_snapshots.save_provider_readiness_snapshot(
                ProviderReadinessSnapshotRecord(
                    provider=provider,
                    host=host,
                    binary=candidate,
                    version=version,
                    readiness_json=result.model_dump_json(),
                    probed_at=_utc_now(),
                )
            )
        return result

    def _configured_path_state(
        self,
        binary: str,
        *,
        host: str,
    ) -> tuple[ProviderPathState, str | None, bool]:
        where = f" on {host}" if host else ""
        if host:
            probe = self._probe(host, ["python3", "-c", _REMOTE_PATH_PROBE, binary])
            if probe.returncode == 0:
                return "resolved", None, False
            if probe.returncode == 255:
                reason = _unreachable_reason(probe, host=host, checked=binary)
                return "unreachable", reason, _link_lost(probe)
            if probe.returncode == _REMOTE_PATH_MISSING:
                return "missing", f"The recorded executable {binary}{where} does not exist.", False
            if probe.returncode == _REMOTE_PATH_NOT_FILE:
                return (
                    "denied",
                    f"The recorded executable {binary}{where} is not a regular file.",
                    False,
                )
            if probe.returncode == _REMOTE_PATH_NOT_EXECUTABLE:
                return (
                    "denied",
                    f"The recorded executable {binary}{where} is not executable.",
                    False,
                )
            if probe.returncode == _REMOTE_PATH_DENIED:
                return "denied", f"Execute access to {binary}{where} was denied.", False
            return (
                "denied",
                f"The recorded executable {binary}{where} could not be inspected.",
                False,
            )

        try:
            mode = Path(binary).stat().st_mode
        except FileNotFoundError:
            return "missing", f"The recorded executable {binary} does not exist.", False
        except PermissionError:
            return "denied", f"Access to the recorded executable {binary} was denied.", False
        except OSError as exc:
            return (
                "denied",
                f"The recorded executable {binary} could not be inspected: {exc}.",
                False,
            )
        if not stat.S_ISREG(mode):
            return "denied", f"The recorded executable {binary} is not a regular file.", False
        if not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            return "denied", f"The recorded executable {binary} is not executable.", False
        if not os.access(binary, os.X_OK):
            return "denied", f"Execute access to {binary} was denied.", False
        return "resolved", None, False

    async def stream(
        self,
        provider: str,
        prompt: str,
        *,
        cwd: Path,
        model: str | None = None,
        reasoning: str | None = None,
        session_id: str | None = None,
        read_dirs: list[Path] | None = None,
        write_dirs: list[Path] | None = None,
        write_scope: ProjectWriteScope | None = None,
        host: str = "",
        control: AgentProcessControl | None = None,
        remote_pid_file: str | None = None,
        transport_partition: str | None = None,
        invocation_gate: ProviderInvocationGate | None = None,
        capability: AgentCapability,
        binary: str | None = None,
        runtime_id: str | None = None,
        before_start: Callable[[], Awaitable[None]] | None = None,
        supervise_remote: bool = False,
        supervisor_path: str | None = None,
        operation_id: str | None = None,
        git_access: ProviderGitAccess | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the preferred provider runtime, falling back only before prompt delivery.

        `before_start` runs once the credential gate is held and the provider is
        certain to start: the moment a caller may read the login generation this
        process will run under, since a Verify cannot change it while the gate is
        held.
        """

        runtimes = profile_for(provider).runtime_candidates(runtime_id)
        last_failure: _PrePromptRuntimeFailure | None = None
        for index, runtime in enumerate(runtimes):
            try:
                async with aclosing(
                    self._stream_runtime(
                        provider,
                        prompt,
                        cwd=cwd,
                        model=model,
                        reasoning=reasoning,
                        session_id=session_id,
                        read_dirs=read_dirs,
                        write_dirs=write_dirs,
                        write_scope=write_scope,
                        host=host,
                        control=control,
                        remote_pid_file=(
                            f"{remote_pid_file}.{index}"
                            if remote_pid_file and index
                            else remote_pid_file
                        ),
                        transport_partition=transport_partition,
                        invocation_gate=invocation_gate,
                        capability=capability,
                        binary=binary,
                        runtime_id=runtime.id,
                        before_start=before_start,
                        supervise_remote=supervise_remote,
                        supervisor_path=supervisor_path,
                        operation_id=operation_id,
                        git_access=git_access,
                    )
                ) as stream:
                    async for event in stream:
                        yield event
                return
            except _PrePromptRuntimeFailure as exc:
                last_failure = exc
                if index + 1 < len(runtimes):
                    # The next candidate will succeed silently, so this is the
                    # only place the reason the human's chosen runtime was not
                    # used can still be recorded.
                    yield AgentEvent(
                        event="runtime_fallback",
                        text=json.dumps(
                            {"runtime_id": runtime.id, "detail": str(exc)},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
        assert last_failure is not None
        yield AgentEvent(event="error", text=str(last_failure))

    async def _stream_runtime(
        self,
        provider: str,
        prompt: str,
        *,
        cwd: Path,
        model: str | None = None,
        reasoning: str | None = None,
        session_id: str | None = None,
        read_dirs: list[Path] | None = None,
        write_dirs: list[Path] | None = None,
        write_scope: ProjectWriteScope | None = None,
        host: str = "",
        control: AgentProcessControl | None = None,
        remote_pid_file: str | None = None,
        transport_partition: str | None = None,
        invocation_gate: ProviderInvocationGate | None = None,
        capability: AgentCapability,
        binary: str | None = None,
        runtime_id: str,
        before_start: Callable[[], Awaitable[None]] | None = None,
        supervise_remote: bool = False,
        supervisor_path: str | None = None,
        operation_id: str | None = None,
        git_access: ProviderGitAccess | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if control is not None and control.pause_requested.is_set():
            yield AgentEvent(event="paused", text="Paused before the provider started.")
            return
        readiness_kwargs: dict[str, str] = {"host": host}
        if binary is not None:
            readiness_kwargs["binary"] = binary
        readiness = await asyncio.to_thread(
            self.readiness,
            provider,
            **readiness_kwargs,
        )
        discovered_path_is_usable = (
            binary is None
            and getattr(readiness, "path_state", "resolved") == "unconfigured"
            and bool(getattr(readiness, "binary_path", None))
        )
        if (
            not (
                getattr(readiness, "path_state", "resolved") == "resolved"
                or discovered_path_is_usable
            )
            or not readiness.installed
            or not readiness.authenticated
        ):
            yield AgentEvent(
                event="error",
                text=readiness.reason or "Provider is unavailable.",
                # Set only when a probe ssh actually ran exited 255: the probe's
                # own word, not a reading of its text or of `unreachable`, which
                # a local ssh that could not start also reports.
                failure_kind=(
                    "transport_lost" if host and getattr(readiness, "link_lost", False) else None
                ),
            )
            return

        if write_scope is not None:
            if str(cwd) != write_scope.workspace_root:
                yield AgentEvent(
                    event="error",
                    text="Provider workspace does not match the resolved project write scope.",
                )
                return
            if host != write_scope.execution_host:
                yield AgentEvent(
                    event="error",
                    text="Provider execution host does not match the resolved project write scope.",
                )
                return

        profile = profile_for(provider)
        work_problem = (
            work_like_launch_problem(readiness)
            if capability in {"work_auto", "orchestrate"}
            else None
        )
        if work_problem is not None:
            yield AgentEvent(event="error", text=work_problem)
            return
        runtime = profile.runtime(runtime_id)
        resolved_binary = getattr(readiness, "binary_path", None) or binary or provider
        if runtime.id.endswith(".herdr-native.v1"):
            async for event in self._stream_herdr_native(
                provider,
                prompt,
                cwd=cwd,
                model=model,
                reasoning=reasoning,
                session_id=session_id,
                read_dirs=read_dirs or [],
                write_dirs=write_dirs or [],
                write_scope=write_scope,
                host=host,
                control=control,
                invocation_gate=invocation_gate,
                capability=capability,
                binary=resolved_binary,
                runtime_id=runtime.id,
                provider_version=getattr(readiness, "version", None),
                before_start=before_start,
                git_access=git_access,
                operation_id=operation_id,
            ):
                yield event
            return
        legacy_command = (
            self._command(
                provider,
                prompt,
                binary=resolved_binary,
                cwd=cwd,
                model=model,
                reasoning=reasoning,
                session_id=session_id,
                read_dirs=read_dirs or [],
                write_dirs=write_dirs or [],
                write_scope=write_scope,
                capability=capability,
                provider_version=getattr(readiness, "version", None),
            )
            if runtime.id == profile.legacy_runtime_id
            else None
        )
        try:
            turn = runtime.turn(
                ProviderTurnRequest(
                    prompt=prompt,
                    binary=resolved_binary,
                    cwd=cwd,
                    model=model,
                    reasoning=reasoning,
                    session_id=session_id,
                    read_dirs=read_dirs or [],
                    write_dirs=write_dirs or [],
                    write_scope=write_scope,
                    capability=capability,
                    provider_version=getattr(readiness, "version", None),
                    legacy_command=legacy_command,
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise _PrePromptRuntimeFailure(str(exc)) from exc
        command = turn.command
        if invocation_gate is not None:
            command = invocation_gate.wrap_command(command)
        if supervise_remote:
            if not host or remote_pid_file is None:
                raise ValueError("A supervised provider turn requires a remote pidfile.")
            if not supervisor_path:
                raise ValueError("A supervised provider turn requires its staged supervisor.")
            command = _supervised_remote_turn_command(
                command,
                supervisor_path=supervisor_path,
                pid_file=remote_pid_file,
                provider=provider,
                runtime_id=runtime.id,
                provider_version=getattr(readiness, "version", None),
                patch_path=str(cwd / "patch.json"),
                watch_path=str(cwd / "watch.json"),
                experiment_watch_glob=str(cwd / EXPERIMENT_WATCH_OUTPUT_GLOB),
                close_input_after_initial=turn.close_input_after_initial,
            )
        if control is not None and control.pause_requested.is_set():
            yield AgentEvent(event="paused", text="Paused before the provider started.")
            return
        # Held until this provider speaks and the minimum stagger passes, so
        # two turns cannot rotate one credential's refresh token together.
        credential_hold = await self.credential_gate.hold(provider, host)
        if control is not None and control.pause_requested.is_set():
            # The pre-launch check ran before this wait, which can be long.
            credential_hold.release()
            yield AgentEvent(event="paused", text="Paused before the provider started.")
            return
        if before_start is not None:
            try:
                await before_start()
            except BaseException:
                credential_hold.release()
                raise
        try:
            if reason := self._login_refusal(provider, host):
                raise ValueError(reason)
            environment = self.process_environment(provider, host)
            if git_access is not None:
                if git_access.host != host:
                    raise ValueError("Git access does not match the provider execution host.")
                environment, notices = await git_access.prepare(environment)
                for notice in notices:
                    yield AgentEvent(event="message", text=notice)
            local_cwd: str | None = str(cwd)
            if host:
                command = ssh_arguments(
                    host,
                    self._remote_login_command(
                        command,
                        pid_file=remote_pid_file,
                        cwd=cwd,
                        prefix=environment.remote_prefix,
                    ),
                    # This turn is the longest-lived call of its run, so it holds
                    # the run's own master rather than whichever short probe
                    # happened to open the host first.
                    partition=transport_partition,
                )
                local_cwd = None
                if control is not None and remote_pid_file:
                    control.configure_remote_termination(host, remote_pid_file)
        except BaseException:
            credential_hold.release()
            raise
        # Declared only once this turn is certain to launch. Announcing a remote
        # pass and then pausing would leave a live pass nothing ever closes.
        if host and remote_pid_file:
            try:
                yield AgentEvent(event="remote_process_start", text=remote_pid_file)
            except BaseException:
                # A consumer closing here, or failing to persist the pass, throws
                # into this yield: outside the subprocess arm and the stream's
                # own finally, so nothing else would give the credential back.
                credential_hold.release()
                raise
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=local_cwd,
                env=environment.local_env if not host else None,
                limit=self._STREAM_LIMIT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except BaseException as exc:
            # Cancellation here would otherwise skip both the arm below and the
            # stream's own finally, leaving the credential held.
            credential_hold.release()
            if not isinstance(exc, OSError):
                raise
            if host and remote_pid_file:
                yield AgentEvent(event="remote_process_stop", text=remote_pid_file)
            if runtime.id == profile.legacy_runtime_id:
                self.invalidate_readiness(provider, host=host, binary=binary)
            logger.warning(
                "provider process failed to start provider=%s capability=%s runtime=%s "
                "host=%s executable=%s operation=%s error=%s",
                provider,
                capability,
                runtime.id,
                host or "local",
                resolved_binary,
                operation_id or "-",
                type(exc).__name__,
            )
            raise _PrePromptRuntimeFailure(str(exc)) from exc
        # Every stop of this process, local or remote, honours the startup hold
        # measured from here, not only an explicit Pause.
        started_at = time.monotonic()
        launched_at = started_at
        # The one trace of this process outside the task row. Identifiers only:
        # provider output can carry token-shaped values and never reaches the
        # journal (docs/server.md, "Inspect and stop the service").
        logger.info(
            "provider process started provider=%s capability=%s runtime=%s host=%s "
            "executable=%s pid=%s%s operation=%s",
            provider,
            capability,
            runtime.id,
            host or "local",
            resolved_binary,
            process.pid,
            f" remote_pid_file={remote_pid_file}" if host and remote_pid_file else "",
            operation_id or "-",
        )
        if control is not None:
            control.attach(process)
        steering = LiveProviderSteering(
            process, turn, control.pause_requested if control is not None else threading.Event()
        )
        if control is not None:
            control.attach_steering(steering)
        stdin_task: asyncio.Task[None] | None = None
        stderr_task: asyncio.Task[str] | None = None
        stdout_task: asyncio.Task[tuple[bytes | None, int]] | None = None
        stdout_lines = None
        remote_stopped: bool | None = None
        remote_result_pending = False
        prompt_delivered = False
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            prompt_bytes = turn.initial_input()
            if invocation_gate is not None:
                prompt_bytes = invocation_gate.bootstrap(prompt_bytes)
            prompt_delivered = False
            pre_prompt_error = ""
            if turn.initial_input_delivers_prompt:
                yield AgentEvent(event="runtime", text=runtime.id)
                # From this point a write may be partial even if drain raises;
                # retrying through another runtime could duplicate the turn.
                prompt_delivered = True
            stdin_task = asyncio.create_task(
                _feed_stdin(
                    process.stdin,
                    prompt_bytes,
                    close=turn.close_input_after_initial,
                )
            )
            stderr_task = (
                asyncio.create_task(
                    _read_bounded_text(
                        process.stderr,
                        max_bytes=self._MAX_STDERR_BYTES,
                        chunk_bytes=self._STREAM_LIMIT,
                    )
                )
                if process.stderr is not None
                else None
            )
            stdout_lines = _read_bounded_lines(
                process.stdout,
                max_line_bytes=self._MAX_EVENT_BYTES,
                chunk_bytes=self._STREAM_LIMIT,
            )
            stdout_task = asyncio.create_task(anext(stdout_lines))
            stdin_pending = True
            stderr_pending = stderr_task is not None
            stderr = ""
            provider_failed = False
            protocol_complete = False
            event_counts: dict[str, int] = {}
            explicit_terminal_event = False
            stopped_at_result = False
            completion_stop_failed = False
            while stdout_task is not None:
                monitored: set[asyncio.Task[object]] = {stdout_task}
                if stdin_pending:
                    monitored.add(stdin_task)
                if stderr_pending:
                    assert stderr_task is not None
                    monitored.add(stderr_task)
                done, _ = await asyncio.wait(
                    monitored,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stdin_pending and stdin_task in done:
                    await stdin_task
                    stdin_pending = False
                if stderr_pending and stderr_task in done:
                    stderr = await stderr_task
                    stderr_pending = False
                if stdout_task not in done:
                    continue
                try:
                    raw_line, omitted_bytes = stdout_task.result()
                except StopAsyncIteration:
                    stdout_task = None
                    break
                stdout_task = asyncio.create_task(anext(stdout_lines))
                if omitted_bytes:
                    event = AgentEvent(
                        event="raw",
                        text=(
                            "Omitted oversized provider event "
                            f"({omitted_bytes} bytes; limit {self._MAX_EVENT_BYTES} bytes)."
                        ),
                    )
                    event_counts[event.event] = event_counts.get(event.event, 0) + 1
                    credential_hold.release()
                    if prompt_delivered:
                        yield event
                    continue
                assert raw_line is not None
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                if invocation_gate is not None and line == invocation_gate.ready_line:
                    # The broker prints this straight after spawning, before the
                    # provider authenticates, so it does not end the hold.
                    continue
                if host and line == REMOTE_PROVIDER_START_LINE:
                    # The SSH handshake before this line was not provider time:
                    # the stagger and every later stop are measured from here.
                    started_at = time.monotonic()
                    credential_hold.restart_minimum()
                    if control is not None:
                        control.restart_hold(started_at)
                    continue
                # A line the provider itself wrote: it is past its own auth
                # initialization and the next startup may begin.
                credential_hold.release()
                if stdin_pending:
                    await stdin_task
                    stdin_pending = False
                step = turn.receive_line(line)
                steering.observe(step)
                if step.stop_process:
                    # Claude can interpret stdin as another turn after result.
                    # Fence delivery and stop before yielding any result event.
                    stopped_at_result = True
                    process.stdin.close()
                    if host and remote_pid_file:
                        stopped_remote = await asyncio.to_thread(
                            AgentProcessControl._terminate_remote_after_hold,
                            host,
                            remote_pid_file,
                            started_at,
                        )
                        completion_stop_failed = not stopped_remote
                    elif host:
                        completion_stop_failed = True
                    await AgentProcessControl._terminate(process, started_at)
                if step.delivers_prompt:
                    if prompt_delivered:
                        raise RuntimeError(
                            f"{provider} attempted to deliver one prompt more than once."
                        )
                    yield AgentEvent(event="runtime", text=runtime.id)
                    # Mark this before the actual write: a partial JSON-RPC
                    # request is already beyond the safe fallback boundary.
                    prompt_delivered = True
                for outgoing in step.outgoing:
                    await _write_stdin(process.stdin, outgoing)
                for decoded in step.events:
                    event = AgentEvent(
                        event=decoded.event,
                        text=decoded.text,
                        session_id=decoded.session_id,
                        usage=decoded.usage,
                    )
                    event_counts[event.event] = event_counts.get(event.event, 0) + 1
                    if event.event == "error":
                        # Consumers stop at the first error. Capture the diagnostic
                        # before yielding it, including when a result already stopped
                        # the process and bypasses the nonzero-exit branch below.
                        process.stdin.close()
                        if stderr_pending:
                            assert stderr_task is not None
                            try:
                                # Other protocols can finish their error response on
                                # EOF. Give them a bounded graceful exit before TERM.
                                stderr = await asyncio.wait_for(
                                    asyncio.shield(stderr_task),
                                    timeout=PROVIDER_STDERR_DRAIN_TIMEOUT_SECONDS,
                                )
                            except TimeoutError:
                                if not step.stop_process:
                                    if host and remote_pid_file:
                                        await asyncio.to_thread(
                                            AgentProcessControl._terminate_remote_after_hold,
                                            host,
                                            remote_pid_file,
                                            started_at,
                                        )
                                    await AgentProcessControl._terminate(process, started_at)
                                try:
                                    stderr = await asyncio.wait_for(
                                        stderr_task,
                                        timeout=PROVIDER_STDERR_DRAIN_TIMEOUT_SECONDS,
                                    )
                                except TimeoutError:
                                    stderr = "Provider stderr did not close after termination."
                            stderr_pending = False
                        detail = _meaningful_stderr(stderr)
                        if detail and detail not in event.text:
                            event.text = "\n".join(part for part in (event.text, detail) if part)
                        if host and remote_pid_file:
                            remote_stopped = await asyncio.to_thread(
                                AgentProcessControl._confirm_remote_stopped,
                                host,
                                remote_pid_file,
                                started_at,
                            )
                            completion_stop_failed = not remote_stopped
                            if prompt_delivered and remote_stopped:
                                # Consumers may close on the first error, before
                                # provider_exit can settle the durable pass.
                                yield AgentEvent(event="remote_process_stop", text=remote_pid_file)
                        provider_failed = True
                        if not prompt_delivered and not pre_prompt_error:
                            pre_prompt_error = event.text
                    if prompt_delivered:
                        yield event
                explicit_terminal_event = explicit_terminal_event or step.explicit_terminal
                protocol_complete = protocol_complete or step.complete
                if step.complete and not process.stdin.is_closing():
                    process.stdin.close()
                if stopped_at_result:
                    break
            if stdin_pending:
                await stdin_task
            return_code = await process.wait()
            if stderr_pending:
                assert stderr_task is not None
                stderr = await stderr_task
            stderr = _meaningful_stderr(stderr)
            remote_result_pending = bool(
                supervise_remote and prompt_delivered and transport_failure(return_code, host)
            )
            if host and remote_pid_file and not remote_result_pending:
                remote_stopped = await asyncio.to_thread(
                    partial(
                        AgentProcessControl._confirm_remote_stopped,
                        host,
                        remote_pid_file,
                        started_at,
                        launch_ended=True,
                    )
                )
                completion_stop_failed = not remote_stopped
                if not prompt_delivered and remote_stopped:
                    yield AgentEvent(event="remote_process_stop", text=remote_pid_file)
            if not prompt_delivered and not (
                control is not None and control.pause_requested.is_set()
            ):
                detail = (
                    pre_prompt_error
                    or stderr
                    or (
                        _exit_reason(provider, return_code, host)
                        if return_code
                        else f"{provider} closed its provider runtime before accepting the turn."
                    )
                )
                if completion_stop_failed:
                    # Why the launch failed is the human's first question, and
                    # this branch used to answer a second one instead. The stop
                    # RCP could not confirm is why no other runtime may follow;
                    # it is not what went wrong.
                    yield AgentEvent(
                        event="error",
                        text="\n".join(
                            (
                                detail,
                                "RCP could not confirm that the remote provider process "
                                "stopped, so runtime fallback is blocked.",
                            )
                        ),
                    )
                    return
                raise _PrePromptRuntimeFailure(detail)
            paused = control is not None and control.pause_requested.is_set()
            turn_failed = bool(
                completion_stop_failed
                or provider_failed
                or (return_code and not stopped_at_result)
                or (turn.requires_protocol_completion and not protocol_complete)
            )
            # A provider that succeeded can still have dropped part of the
            # launch. Its stderr says so, but stderr itself is the vendor's
            # channel; the profile turns it into one sentence RCP owns. Only a
            # turn that finished gets the note: a failed or paused turn already
            # tells the human why it stopped, and saying how it ran would
            # compete with that rather than add to it.
            degradation = (
                None
                if paused or turn_failed
                else profile.launch_degradation(stderr, requested_reasoning=reasoning)
            )
            yield AgentEvent(
                event="provider_exit",
                text=json.dumps(
                    {
                        "return_code": return_code,
                        "event_counts": event_counts,
                        "explicit_terminal_event": explicit_terminal_event,
                        **(
                            {"remote_process_stopped": remote_stopped}
                            if host and remote_pid_file
                            else {}
                        ),
                        **({"delivery_lost": True} if remote_result_pending else {}),
                        **({"stopped_at_result": True} if stopped_at_result else {}),
                        **({"degradation": degradation} if degradation else {}),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            if remote_result_pending:
                yield AgentEvent(
                    event="remote_result_pending",
                    text="The connection ended after the remote host accepted this turn.",
                )
            elif paused:
                yield AgentEvent(event="paused", text="Provider process paused.")
            elif completion_stop_failed:
                yield AgentEvent(
                    event="error",
                    text="RCP could not confirm that the remote provider process stopped. Recovery is blocked until its process state can be verified.",
                )
            elif provider_failed:
                # The first error already includes stderr. A forced stop must
                # not invent a second failure from our own termination signal.
                self.invalidate_readiness(provider, host=host, binary=binary)
            elif return_code and not stopped_at_result:
                self.invalidate_readiness(provider, host=host, binary=binary)
                detail = turn.last_error or stderr or _exit_reason(provider, return_code, host)
                yield AgentEvent(event="error", text=detail)
            elif turn.requires_protocol_completion and not protocol_complete:
                self.invalidate_readiness(provider, host=host, binary=binary)
                yield AgentEvent(
                    event="error",
                    text=f"{provider} closed its provider protocol before the turn completed.",
                )
            else:
                yield AgentEvent(event="done")
        finally:
            credential_hold.release()
            steering.close()

            async def cleanup() -> None:
                try:
                    if (
                        host
                        and remote_pid_file
                        and remote_stopped is not True
                        and not remote_result_pending
                    ):
                        await asyncio.to_thread(
                            AgentProcessControl._confirm_remote_stopped,
                            host,
                            remote_pid_file,
                            started_at,
                        )
                finally:
                    try:
                        await _cleanup_provider_process(
                            process,
                            started_at=started_at,
                            stdin_task=stdin_task,
                            stdout_task=stdout_task,
                            stdout_lines=stdout_lines,
                            stderr_task=stderr_task,
                        )
                    finally:
                        _log_provider_exit(
                            provider,
                            capability=capability,
                            runtime_id=runtime.id,
                            host=host,
                            executable=resolved_binary,
                            pid=process.pid,
                            return_code=process.returncode,
                            duration_seconds=time.monotonic() - launched_at,
                            operation_id=operation_id,
                        )

            cleanup_task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise
            finally:
                if control is not None:
                    control.detach(process)

    async def _stream_herdr_native(
        self,
        provider: str,
        prompt: str,
        *,
        cwd: Path,
        model: str | None,
        reasoning: str | None,
        session_id: str | None,
        read_dirs: list[Path],
        write_dirs: list[Path],
        write_scope: ProjectWriteScope | None,
        host: str,
        control: AgentProcessControl | None,
        invocation_gate: ProviderInvocationGate | None,
        capability: AgentCapability,
        binary: str,
        runtime_id: str,
        provider_version: str | None,
        before_start: Callable[[], Awaitable[None]] | None,
        git_access: ProviderGitAccess | None,
        operation_id: str | None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one native interactive turn with a provider-authored receipt.

        The pane is owned by this invocation. RCP closes it before reporting a
        terminal event so no later unrecorded turn can inherit Work authority.
        """

        from rcp.agents.herdr_bridge import (
            HerdrNativeAdapter,
            build_native_agent_args,
            cleanup_isolated_codex_home,
            isolated_codex_home,
        )
        from rcp.agents.herdr_receipts import (
            claude_turn_receipt,
            codex_transcript_inventory,
            codex_turn_receipt,
            find_native_transcript,
            find_new_codex_transcript,
        )

        if host:
            yield AgentEvent(event="error", text="Herdr native execution is local only.")
            return
        if capability not in {"discuss", "work_auto"}:
            yield AgentEvent(
                event="error", text=f"Herdr native execution does not support {capability}."
            )
            return
        if capability == "work_auto" and invocation_gate is None:
            yield AgentEvent(
                event="error", text="Herdr Work requires its process-bound command broker."
            )
            return
        parent_pane_id = os.environ.get("HERDR_PANE_ID", "")
        if os.environ.get("HERDR_ENV") != "1" or not parent_pane_id:
            yield AgentEvent(
                event="error", text="RCP must run inside a Herdr pane for native execution."
            )
            return
        adapter = HerdrNativeAdapter()
        if session_id:
            try:
                active = await adapter.session_active(provider, session_id, cwd=cwd)
            except (OSError, RuntimeError, ValueError) as exc:
                yield AgentEvent(event="error", text=str(exc))
                return
            if active is not False:
                yield AgentEvent(
                    event="error",
                    text="The saved native session may still be live in Herdr; close its previous pane before continuing.",
                )
                return
        request = ProviderTurnRequest(
            prompt=prompt,
            binary=binary,
            cwd=cwd,
            model=model,
            reasoning=reasoning,
            session_id=session_id,
            read_dirs=read_dirs,
            write_dirs=write_dirs,
            write_scope=write_scope,
            capability=capability,
            provider_version=provider_version,
        )
        fresh_claude_id = str(uuid.uuid4()) if provider == "claude" and not session_id else None
        try:
            args = build_native_agent_args(provider, request, fresh_session_id=fresh_claude_id)
        except (OSError, RuntimeError, ValueError) as exc:
            yield AgentEvent(event="error", text=str(exc))
            return
        hold = await self.credential_gate.hold(provider, "")
        agent = None
        agent_started_at: float | None = None
        closed = False
        binding: dict[str, object] | None = None
        native_home: Path | None = None
        try:
            if control is not None and control.pause_requested.is_set():
                yield AgentEvent(event="paused", text="Paused before the Herdr agent started.")
                return
            if before_start is not None:
                await before_start()
            if reason := self._login_refusal(provider, ""):
                yield AgentEvent(event="error", text=reason)
                return
            environment = self.process_environment(provider, "")
            if git_access is not None:
                environment, notices = await git_access.prepare(environment)
                for notice in notices:
                    yield AgentEvent(event="message", text=notice)
            pane_env = {
                **{
                    key: value
                    for key, value in (environment.local_env or {}).items()
                    if not key.startswith("HERDR_")
                },
                "PATH": f"{Path(binary).parent}:{os.environ.get('PATH', '')}",
            }
            if provider == "codex":
                native_home = isolated_codex_home(cwd)
                pane_env["CODEX_HOME"] = str(native_home)
                if sys.platform.startswith("linux"):
                    pane_env["TMPDIR"] = "/tmp"
                previous_codex_transcripts = codex_transcript_inventory()
            agent = await adapter.start(
                parent_pane_id=parent_pane_id,
                cwd=cwd,
                provider=provider,
                name=f"rcp{secrets.token_hex(6)}",
                args=args,
                env=pane_env,
            )
            agent_started_at = time.monotonic()
            hold.restart_minimum()
            native_id = session_id or fresh_claude_id
            transcript = find_native_transcript(provider, native_id, cwd) if native_id else None
            offset = transcript.stat().st_size if transcript is not None else 0
            process_identity = await adapter.process_info(agent)
            if not _native_binary_matches(process_identity.group_leader_pid, binary):
                raise RuntimeError(
                    "Herdr started a different provider executable than RCP validated."
                )
            binding = {
                "pane_id": agent.pane_id,
                "agent_name": agent.name,
                "provider": provider,
                "native_session_id": native_id,
                "process_group_id": process_identity.foreground_process_group_id,
                "runtime_id": runtime_id,
                "stage_root": str(cwd),
            }
            if provider == "codex":
                binding["codex_home"] = pane_env["CODEX_HOME"]
            yield AgentEvent(event="herdr_binding_start", text=json.dumps(binding))
            if native_id is not None:
                yield AgentEvent(event="session", session_id=native_id)
            async with AsyncExitStack() as stack:
                if invocation_gate is not None:
                    await stack.enter_async_context(
                        invocation_gate.serve_external_provider(process_identity.group_leader_pid)
                    )
                if control is not None and control.pause_requested.is_set():
                    await asyncio.sleep(remaining_startup_hold(agent_started_at))
                    await adapter.close(agent)
                    closed = True
                    yield AgentEvent(event="herdr_binding_stop", text=json.dumps(binding))
                    yield AgentEvent(event="paused", text="Paused before the Herdr prompt.")
                    return
                yield AgentEvent(event="runtime", text=runtime_id)
                # Submission can be ambiguous on socket loss. Never resend.
                await adapter.prompt(agent, prompt)
                receipt = None
                # The prompt API acknowledged delivery; a fast turn may be
                # idle again before the first poll sees its working state.
                saw_activity = provider != "codex"
                prompted_at = time.monotonic()
                settled_at = None
                while receipt is None:
                    if control is not None and control.pause_requested.is_set():
                        await asyncio.sleep(remaining_startup_hold(agent_started_at))
                        await adapter.close(agent)
                        closed = True
                        yield AgentEvent(event="herdr_binding_stop", text=json.dumps(binding))
                        yield AgentEvent(event="paused", text="Herdr native turn was paused.")
                        return
                    observation = await adapter.get(agent)
                    if native_id and observation.session_id and observation.session_id != native_id:
                        raise RuntimeError("Herdr agent switched native sessions during the turn.")
                    if observation.state in {"working", "blocked"}:
                        saw_activity = True
                        settled_at = None
                    elif observation.state in {"idle", "done"} and saw_activity:
                        settled_at = settled_at or time.monotonic()
                    if provider == "codex" and native_id is None:
                        native = find_new_codex_transcript(cwd, previous_codex_transcripts)
                        if native is not None:
                            native_id, transcript = native
                            offset = 0
                            saw_activity = True
                            yield AgentEvent(event="session", session_id=native_id)
                    if transcript is None and native_id is not None:
                        transcript = find_native_transcript(provider, native_id, cwd)
                    if transcript is not None:
                        reader = codex_turn_receipt if provider == "codex" else claude_turn_receipt
                        receipt = reader(
                            transcript, offset=offset, session_id=native_id, prompt=prompt
                        )
                        if transcript.stat().st_size > offset:
                            hold.release()
                    if receipt is not None:
                        break
                    if (
                        not saw_activity
                        and time.monotonic() - prompted_at
                        > HERDR_NATIVE_PROMPT_START_TIMEOUT_SECONDS
                    ):
                        raise RuntimeError("Herdr did not start the Codex prompt in time.")
                    if settled_at is not None and time.monotonic() - settled_at > (
                        30 if provider == "codex" else 5
                    ):
                        raise RuntimeError(
                            "Herdr became idle without a matching provider completion receipt."
                        )
                    await asyncio.sleep(HERDR_NATIVE_RECEIPT_POLL_SECONDS)
            await adapter.close(agent)
            closed = True
            yield AgentEvent(event="herdr_binding_stop", text=json.dumps(binding))
            yield AgentEvent(
                event="provider_exit",
                text=json.dumps(
                    {
                        "return_code": 0,
                        "event_counts": {"session": 1, "answer": 1},
                        "explicit_terminal_event": True,
                        "herdr_pane_closed": True,
                    }
                ),
            )
            yield AgentEvent(event="answer", text=receipt.answer, session_id=native_id)
            yield AgentEvent(event="done")
        except (OSError, RuntimeError, ValueError) as exc:
            if agent is not None and not closed:
                with suppress(OSError, RuntimeError, ValueError):
                    if agent_started_at is not None:
                        await asyncio.sleep(remaining_startup_hold(agent_started_at))
                    await adapter.close(agent)
                    closed = True
                    if binding is not None:
                        yield AgentEvent(event="herdr_binding_stop", text=json.dumps(binding))
            yield AgentEvent(event="error", text=str(exc))
        finally:
            hold.release()
            if agent is not None and not closed:
                with suppress(OSError, RuntimeError, ValueError):
                    if agent_started_at is not None:
                        await asyncio.sleep(remaining_startup_hold(agent_started_at))
                    await adapter.close(agent)
                    closed = True
            if native_home is not None and (agent is None or closed):
                cleanup_isolated_codex_home(str(native_home))

    @staticmethod
    def _command(
        provider: str,
        prompt: str,
        *,
        binary: str | None = None,
        cwd: Path,
        model: str | None,
        reasoning: str | None,
        session_id: str | None,
        read_dirs: list[Path],
        write_dirs: list[Path] | None = None,
        write_scope: ProjectWriteScope | None = None,
        capability: AgentCapability,
        provider_version: str | None = None,
    ) -> list[str]:
        return profile_for(provider).command(
            prompt,
            binary=binary or provider,
            cwd=cwd,
            model=model,
            reasoning=reasoning,
            session_id=session_id,
            read_dirs=read_dirs,
            write_dirs=write_dirs or [],
            write_scope=write_scope,
            capability=capability,
            provider_version=provider_version,
        )

    @staticmethod
    def _probe(
        host: str,
        command: list[str],
        *,
        login_shell: bool = True,
        timeout: float = 10,
        environment: ProviderProcessEnvironment | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = command
        if host:
            remote = (
                AgentLauncher._remote_login_command(
                    command, prefix=environment.remote_prefix if environment else None
                )
                if login_shell
                else shlex.join(command)
            )
            arguments = ssh_arguments(host, remote)
        try:
            return subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                input="",
                # A timeout kills the probe; never inside the credential hold.
                timeout=max(timeout, PROVIDER_CREDENTIAL_STARTUP_MIN_HOLD_SECONDS),
                check=False,
                env=environment.local_env if environment and not host else None,
            )
        except subprocess.TimeoutExpired:
            # ssh connects within its own shorter timeout, so this is a remote
            # command that hung on a live link, not a link that dropped.
            return _ProbeNoVerdict(
                arguments, 255, "", f"the probe gave no answer within {timeout:g}s"
            )
        except OSError as exc:
            return _ProbeNoVerdict(arguments, 255, "", f"ssh could not start: {exc}")

    @staticmethod
    def _remote_login_command(
        command: list[str],
        *,
        pid_file: str | None = None,
        cwd: Path | None = None,
        prefix: str | None = None,
    ) -> str:
        # Provider CLIs are commonly installed by nvm or a shell installer and
        # therefore exist only on the user's login-shell PATH. Interactive mode
        # is intentional here; state transport commands do not use this wrapper.
        command_payload = shlex.join(command)
        if pid_file:
            # `exec` must apply to the provider, not to the `cd` shell builtin.
            # `exec cd <cwd> && provider` exits successfully after changing the
            # directory and silently never launches the provider.
            provider = f"exec {command_payload}"
            if cwd is not None:
                provider = f"cd {shlex.quote(str(cwd))} && {provider}"
            # The start line anchors the startup hold to the provider itself,
            # not to the local SSH client that spawned this shell.
            child = (
                f"echo $$ > {shlex.quote(pid_file)}; "
                f"echo {shlex.quote(REMOTE_PROVIDER_START_LINE)}; {provider}"
            )
            # Interactive bash can make setsid a process-group leader, forcing
            # setsid to fork. Wait for that child so SSH owns the provider's
            # lifetime and exit status rather than the short-lived wrapper.
            payload = shlex.join(["setsid", "--wait", "sh", "-c", child])
        elif cwd is not None:
            # asyncio's cwd= only reaches the local ssh client, so a remote run
            # would otherwise start in $HOME. Codex is additionally pinned by
            # --cd; Claude has no equivalent flag and depends on this entirely.
            payload = f"cd {shlex.quote(str(cwd))} && {command_payload}"
        else:
            payload = command_payload
        if prefix:
            # The provider's environment is prepared inside the same login shell,
            # so the credential is read on the remote account and never travels
            # in this command line.
            payload = f"{prefix}; {payload}"
        return shlex.join(["bash", "-lic", payload])


#: The remote wrapper prints this line just before it execs the provider, so
#: the launcher can tell provider time from the SSH handshake before it.
REMOTE_PROVIDER_START_LINE = "rcp-remote-provider-start"

# `_remote_login_command` runs the provider under `bash -lic`, and interactive
# bash on a non-tty always writes these two lines to stderr. They are emitted by
# every remote run, including successful ones, so treating them as a failure
# reason replaces the real cause with noise: a connection dropped mid-run was
# reported to the human as "cannot set terminal process group" (found running
# S14 on 2026-07-30).
_SIGNALS = {item.value for item in signal.Signals}

_BASH_TTY_NOISE = (
    "cannot set terminal process group",
    "no job control in this shell",
)


def _meaningful_stderr(stderr: str) -> str:
    kept = [
        line
        for line in stderr.strip().splitlines()
        if not any(noise in line for noise in _BASH_TTY_NOISE)
    ]
    return "\n".join(kept).strip()


def _log_provider_exit(
    provider: str,
    *,
    capability: AgentCapability,
    runtime_id: str,
    host: str,
    executable: str,
    pid: int,
    return_code: int | None,
    duration_seconds: float,
    operation_id: str | None,
) -> None:
    """One journal line per provider process end, without any provider output.

    The exit code and RCP's own reading of it are the whole diagnostic here; a
    provider's stderr can print token-shaped values and stays on the task row.
    """
    detail = ""
    if return_code:
        detail = f" reason={_exit_reason(provider, return_code, host)!r}"
    logger.log(
        logging.INFO if return_code == 0 else logging.WARNING,
        "provider process exited provider=%s capability=%s runtime=%s host=%s "
        "executable=%s pid=%s return_code=%s duration_seconds=%.1f operation=%s%s",
        provider,
        capability,
        runtime_id,
        host or "local",
        executable,
        pid,
        return_code,
        duration_seconds,
        operation_id or "-",
        detail,
    )


def _exit_reason(provider: str, return_code: int, host: str) -> str:
    """What to say when the provider died without explaining itself."""
    where = f" on {host}" if host else ""
    # `transport_failure` is the one place that decides what a lost link looks
    # like; this function only chooses the wording for each shape of one.
    if transport_failure(return_code, host) and return_code == 255:
        return f"The connection to {host} was lost before {provider} finished."
    if return_code < 0:
        # asyncio reports a signalled child as the negated signal number. For a
        # remote run the signalled process is the ssh client, so the run ended
        # with the link, not with anything the provider decided.
        name = signal.Signals(-return_code).name if -return_code in _SIGNALS else str(-return_code)
        if host:
            return f"The connection to {host} ended ({name}) before {provider} finished."
        return f"{provider} was stopped by {name}."
    return f"{provider} exited {return_code}{where}."


async def _write_stdin(stream, data: bytes) -> None:
    try:
        stream.write(data)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass


async def _feed_stdin(stream, data: bytes, *, close: bool = True) -> None:
    await _write_stdin(stream, data)
    if close:
        stream.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await stream.wait_closed()


async def _cleanup_provider_process(
    process: asyncio.subprocess.Process,
    *,
    started_at: float,
    stdin_task: asyncio.Task[None] | None,
    stdout_task: asyncio.Task[tuple[bytes | None, int]] | None,
    stdout_lines,
    stderr_task: asyncio.Task[str] | None,
) -> None:
    if process.stdin is not None:
        process.stdin.close()
    if stdin_task is not None and not stdin_task.done():
        stdin_task.cancel()

    stdout_drain_task = (
        asyncio.create_task(_drain_remaining_lines(stdout_task, stdout_lines))
        if stdout_lines is not None
        else (
            asyncio.create_task(_drain_stream(process.stdout))
            if process.stdout is not None
            else None
        )
    )
    stderr_drain_task = (
        asyncio.create_task(_drain_stream(process.stderr))
        if stderr_task is None and process.stderr is not None
        else None
    )

    tasks = [
        task
        for task in (stdin_task, stdout_task, stdout_drain_task, stderr_task, stderr_drain_task)
        if task is not None
    ]
    try:
        await AgentProcessControl._terminate(process, started_at)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if process.stdin is not None:
            with suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()


async def _drain_remaining_lines(current_task, lines) -> None:
    if current_task is not None:
        try:
            await current_task
        except (StopAsyncIteration, asyncio.CancelledError):
            return
        except Exception:
            return
    try:
        async for _ in lines:
            pass
    except Exception:
        pass


async def _drain_stream(stream) -> None:
    try:
        while await stream.read(AgentLauncher._STREAM_LIMIT):
            pass
    except Exception:
        pass


async def _read_bounded_lines(
    stream,
    *,
    max_line_bytes: int,
    chunk_bytes: int,
) -> AsyncIterator[tuple[bytes | None, int]]:
    pending = bytearray()
    discarded = 0
    while True:
        chunk = await stream.read(chunk_bytes)
        if not chunk:
            break
        pieces = chunk.split(b"\n")
        for index, piece in enumerate(pieces):
            terminated = index < len(pieces) - 1
            if discarded:
                discarded += len(piece)
            elif len(pending) + len(piece) > max_line_bytes:
                discarded = len(pending) + len(piece)
                pending.clear()
            else:
                pending.extend(piece)
            if terminated:
                if discarded:
                    yield None, discarded
                else:
                    yield bytes(pending).rstrip(b"\r"), 0
                pending.clear()
                discarded = 0
    if discarded:
        yield None, discarded
    elif pending:
        yield bytes(pending).rstrip(b"\r"), 0


async def _read_bounded_text(
    stream,
    *,
    max_bytes: int,
    chunk_bytes: int,
) -> str:
    captured = bytearray()
    total = 0
    while True:
        chunk = await stream.read(chunk_bytes)
        if not chunk:
            break
        total += len(chunk)
        remaining = max(0, max_bytes - len(captured))
        if remaining:
            captured.extend(chunk[:remaining])
    text = captured.decode("utf-8", errors="replace")
    if total > len(captured):
        text += f"\n[stderr truncated; {total - len(captured)} bytes omitted]"
    return text
