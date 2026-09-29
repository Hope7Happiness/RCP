"""Explicit local Herdr control for native, visible provider agents.

This module owns only pane placement and agent input. Herdr's lifecycle states
are observations, not RCP provider results or graph authority.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rcp.agents.credential_gate import remaining_startup_hold
from rcp.limits import (
    HERDR_NATIVE_SHELL_READY_TIMEOUT_SECONDS,
    HERDR_NATIVE_SHELL_RETRY_SECONDS,
    HERDR_NATIVE_START_TIMEOUT_SECONDS,
)
from rcp.providers import (
    ProviderTurnRequest,
    _claude_write_settings,
    _codex_permission_profile,
    _require_project_write_scope,
    profile_for,
)

_AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_PANE_ID = re.compile(r"w[A-Za-z0-9]+:p[A-Za-z0-9]+\Z")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SETTLED_STATES = frozenset({"idle", "done", "blocked"})


class HerdrBridgeError(RuntimeError):
    """A Herdr control call failed or returned an unusable receipt."""


@dataclass(frozen=True)
class HerdrAgentObservation:
    pane_id: str
    provider: Literal["codex", "claude"]
    name: str
    state: str
    revision: int
    state_change_seq: int
    session_id: str | None


@dataclass(frozen=True)
class HerdrNativeAgent:
    """A binding to one Herdr pane, not proof of a finished RCP turn."""

    pane_id: str
    provider: Literal["codex", "claude"]
    name: str


@dataclass(frozen=True)
class HerdrProcessIdentity:
    pane_id: str
    foreground_process_group_id: int
    group_leader_pid: int


def _is_codex_process(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name
    if executable == "codex":
        return True
    return executable == "node" and any(Path(arg).stem == "codex" for arg in argv[1:3])


def _codex_process_matches_session(argv: list[str], session_id: str, cwd: Path) -> bool:
    if not _is_codex_process(argv):
        return False
    if any(argv[index : index + 2] == ["resume", session_id] for index in range(len(argv) - 1)):
        return True
    return any(argv[index : index + 2] == ["-C", str(cwd)] for index in range(len(argv) - 1))


def _local_codex_processes(
    session_id: str, cwd: Path, *, excluded_pids: frozenset[int] = frozenset()
) -> list[int]:
    """Find same-user Codex writers the Herdr inventory may not report."""

    if not sys.platform.startswith("linux"):
        raise ValueError("Existing Codex session handoff requires Linux process identity.")
    matches: list[int] = []
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        if int(process.name) in excluded_pids:
            continue
        try:
            if process.stat().st_uid != os.geteuid():
                continue
            argv = [
                os.fsdecode(item)
                for item in (process / "cmdline").read_bytes().split(b"\0")
                if item
            ]
            if not _is_codex_process(argv):
                continue
            if _codex_process_matches_session(argv, session_id, cwd):
                matches.append(int(process.name))
                continue
            if (process / "cwd").resolve() == cwd:
                matches.append(int(process.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue  # The process exited or belongs to another identity.
    return matches


def require_codex_session_quiescent(
    session_id: str, source_cwd: Path, *, owned_pane_id: str | None = None
) -> None:
    """Refuse a second writer until the original native process has exited.

    This is an admission proof, not a lock understood by arbitrary Codex
    processes. The launch path repeats it immediately before a prompt.
    """

    try:
        if str(uuid.UUID(session_id)) != session_id:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Codex session ID must be a canonical UUID.") from exc
    if not source_cwd.is_absolute() or not source_cwd.is_dir():
        raise ValueError("The imported Codex working directory is unavailable.")
    source_cwd = source_cwd.resolve()
    if os.environ.get("HERDR_ENV") != "1":
        raise ValueError("The RCP server is not running inside Herdr.")

    if owned_pane_id is not None and not _PANE_ID.fullmatch(owned_pane_id):
        raise ValueError("The owned Herdr pane identity is invalid.")

    async def inspect_herdr() -> tuple[str | None, frozenset[int]]:
        adapter = HerdrNativeAdapter()
        result = await adapter._api("agent.list", {})
        agents = result.get("agents")
        if not isinstance(agents, list):
            raise HerdrBridgeError("Herdr agent inventory is unavailable.")
        excluded_pids: set[int] = set()
        found_owned = owned_pane_id is None
        for item in agents:
            if not isinstance(item, dict) or item.get("agent") != "codex":
                continue
            pane_id = item.get("pane_id")
            if not isinstance(pane_id, str) or not _PANE_ID.fullmatch(pane_id):
                raise HerdrBridgeError("Herdr returned an invalid Codex pane identity.")
            if pane_id == owned_pane_id:
                found_owned = True
                info = await adapter._api("pane.process_info", {"pane_id": pane_id})
                process_info = info.get("process_info")
                if not isinstance(process_info, dict) or process_info.get("pane_id") != pane_id:
                    raise HerdrBridgeError("The owned Codex pane changed process identity.")
                processes = process_info.get("foreground_processes")
                if not isinstance(processes, list) or not processes:
                    raise HerdrBridgeError("The owned Codex pane has no provider process.")
                for process in processes:
                    if isinstance(process, dict) and isinstance(process.get("pid"), int):
                        excluded_pids.add(process["pid"])
                continue
            session = item.get("agent_session")
            identified = (
                isinstance(session, dict)
                and session.get("kind") == "id"
                and session.get("value") == session_id
            )
            same_cwd = item.get("cwd") == str(source_cwd)
            if not identified and not same_cwd:
                continue
            info = await adapter._api("pane.process_info", {"pane_id": pane_id})
            process_info = info.get("process_info")
            if not isinstance(process_info, dict) or process_info.get("pane_id") != pane_id:
                raise HerdrBridgeError("Herdr returned mismatched Codex process identity.")
            processes = process_info.get("foreground_processes")
            if not isinstance(processes, list):
                raise HerdrBridgeError("Herdr cannot prove the Codex process has stopped.")
            if (
                identified
                or any(
                    isinstance(process, dict)
                    and isinstance(process.get("argv"), list)
                    and _codex_process_matches_session(process["argv"], session_id, source_cwd)
                    for process in processes
                )
                or (same_cwd and processes)
            ):
                return pane_id, frozenset(excluded_pids)
        if not found_owned:
            raise HerdrBridgeError("The owned Codex pane disappeared before prompt delivery.")
        return None, frozenset(excluded_pids)

    try:
        pane_id, excluded_pids = asyncio.run(inspect_herdr())
    except HerdrBridgeError as exc:
        raise ValueError(f"Cannot prove the Codex session has stopped: {exc}") from exc
    if pane_id is not None:
        raise ValueError(
            f"Codex is still active in Herdr pane {pane_id}. Exit that agent in Herdr, "
            "then retry Continue; RCP will resume its native session in a controlled pane."
        )
    owners = _local_codex_processes(session_id, source_cwd, excluded_pids=excluded_pids)
    if owners:
        raise ValueError(
            f"Codex process {owners[0]} still owns this repository or native session. "
            "Exit it before continuing in RCP."
        )


def isolated_codex_home(cwd: Path) -> Path:
    """Hide ambient Codex config and rules while retaining native login/history.

    Its two links expose the provider's own credential and session stores; no config, rule,
    plugin, or skill files from the user's Codex home enter the launch.
    """

    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("A local Codex workspace is required.")
    source = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    source = source.resolve()
    credential = source / "auth.json"
    sessions = source / "sessions"
    if not credential.is_file() or credential.stat().st_uid != os.geteuid():
        raise HerdrBridgeError("The local Codex file login is unavailable.")
    if not sessions.is_dir() or sessions.stat().st_uid != os.geteuid():
        raise HerdrBridgeError("The local Codex session store is unavailable.")
    # Codex installs its sandbox helper beside its temporary home. A shared
    # project TMPDIR may be unsuitable for that executable; use the local
    # host's private temporary filesystem for this process-only home.
    local_tmp = Path("/tmp") if sys.platform.startswith("linux") else Path(tempfile.gettempdir())
    home = Path(tempfile.mkdtemp(prefix="rcp-codex-home-", dir=local_tmp))
    try:
        (home / "auth.json").symlink_to(credential)
        (home / "sessions").symlink_to(sessions, target_is_directory=True)
        (home / "config.toml").write_text(
            "check_for_update_on_startup = false\n"
            f"[projects.{json.dumps(str(cwd))}]\n"
            'trust_level = "trusted"\n'
        )
    except BaseException:
        cleanup_isolated_codex_home(str(home))
        raise
    return home


def cleanup_isolated_codex_home(value: str) -> None:
    """Remove only an RCP-created Codex home after a recovered pane closes."""

    path = Path(value)
    local_tmp = Path("/tmp") if sys.platform.startswith("linux") else Path(tempfile.gettempdir())
    if (
        not path.is_absolute()
        or path.parent != local_tmp
        or not path.name.startswith("rcp-codex-home-")
    ):
        raise ValueError("An unfinished Herdr binding has an invalid Codex home.")
    try:
        identity = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(identity.st_mode) or identity.st_uid != os.geteuid():
        raise ValueError("An unfinished Herdr binding changed Codex home identity.")
    shutil.rmtree(path)


def build_native_agent_args(
    provider_id: Literal["codex", "claude"],
    request: ProviderTurnRequest,
    *,
    fresh_session_id: str | None = None,
) -> list[str]:
    """Render native TUI flags from the same resolved scope as the JSON runtime.

    Deliberately limited to local Discuss and Work sessions. No fallback or
    protocol adaptation is implied by these flags.
    """

    provider = profile_for(provider_id)
    if provider.id not in {"codex", "claude"}:
        raise ValueError("Herdr supports only Codex and Claude native agents.")
    canonical_binary = shutil.which(provider_id)
    if (
        canonical_binary is None
        or Path(canonical_binary).resolve() != Path(request.binary).resolve()
    ):
        raise ValueError("Herdr's canonical provider executable differs from the configured one.")
    if request.capability not in {"discuss", "work_auto"}:
        raise ValueError("This RCP capability has no Herdr native-agent contract.")
    if request.session_id is not None and not _SESSION_ID.fullmatch(request.session_id):
        raise ValueError("Herdr native-session ID is invalid.")
    if fresh_session_id is not None:
        if provider_id != "claude" or request.session_id is not None:
            raise ValueError("Only a fresh Claude Herdr session accepts an assigned session ID.")
        try:
            if str(uuid.UUID(fresh_session_id)) != fresh_session_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Fresh Claude session ID must be a canonical UUID.") from exc
    if not request.cwd.is_absolute():
        raise ValueError("Herdr native-agent cwd must be absolute.")
    if request.write_scope is not None and request.write_scope.execution_host:
        raise ValueError("Remote Herdr native-agent execution is not supported.")
    work = request.capability == "work_auto"
    scope = (
        _require_project_write_scope(
            request.write_scope,
            capability=request.capability,
            write_dirs=request.write_dirs,
        )
        if work
        else None
    )
    if not work and request.write_scope is not None:
        raise ValueError("Discuss cannot carry a project write scope.")
    if scope is not None and str(request.cwd) != scope.workspace_root:
        raise ValueError("Herdr cwd does not match the resolved write scope.")
    provider.validate_readiness_version(request.provider_version, capability=request.capability)

    if provider_id == "codex":
        version = tuple(
            int(item) for item in re.findall(r"\d+", request.provider_version or "")[:3]
        )
        if len(version) != 3 or version < (0, 156, 0):
            raise ValueError("Herdr native Codex requires CLI 0.156.0 or newer.")
        args = ["--no-alt-screen", "--no-daemon", "--strict-config", "-C", str(request.cwd)]
        if work:
            assert scope is not None
            args.extend(
                [
                    "-c",
                    'default_permissions="rcp_project"',
                    "-c",
                    _codex_permission_profile(scope),
                    "-c",
                    'approval_policy="never"',
                ]
            )
        else:
            args.extend(["--sandbox", "read-only", "--ask-for-approval", "never"])
        args.extend(["-c", 'web_search="live"'])
        if request.model:
            args.extend(["--model", request.model])
        if request.reasoning:
            args.extend(["-c", f'model_reasoning_effort="{request.reasoning}"'])
        if request.session_id:
            args.extend(["resume", request.session_id])
        return args

    args = ["--permission-mode", "dontAsk" if work else "acceptEdits"]
    if scope is not None:
        args.extend(
            [
                "--setting-sources",
                "",
                "--settings",
                json.dumps(_claude_write_settings(scope), separators=(",", ":")),
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
            ]
        )
    else:
        args.extend(["--allowedTools", "WebSearch", "WebFetch"])
    directories = [*request.read_dirs, *request.write_dirs]
    if scope is not None:
        directories = [*request.read_dirs, *(Path(item) for item in scope.repository_roots)]
    for directory in dict.fromkeys(str(item) for item in directories):
        args.extend(["--add-dir", directory])
    if request.model:
        args.extend(["--model", request.model])
    if request.reasoning:
        args.extend(["--effort", request.reasoning])
    if request.session_id:
        args.extend(["--resume", request.session_id])
    if fresh_session_id:
        args.extend(["--session-id", fresh_session_id])
    return args


class HerdrNativeAdapter:
    """One-shot Herdr socket API operations using explicit pane identities."""

    def __init__(self, socket_path: str | None = None) -> None:
        self.socket_path = socket_path or os.environ.get("HERDR_SOCKET_PATH")

    async def _api(
        self, method: str, params: dict[str, object], *, timeout_seconds: float = 35
    ) -> dict[str, object]:
        if not self.socket_path:
            raise HerdrBridgeError("Herdr socket path is unavailable.")
        try:
            socket_state = os.lstat(self.socket_path)
        except OSError as exc:
            raise HerdrBridgeError(f"Herdr socket is unavailable: {exc}") from exc
        if (
            not stat.S_ISSOCK(socket_state.st_mode)
            or socket_state.st_uid != os.getuid()
            or socket_state.st_mode & 0o077
        ):
            raise HerdrBridgeError("Herdr socket does not have private current-user ownership.")
        request_id = secrets.token_hex(12)
        request = {"id": request_id, "method": method, "params": params}
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path, limit=8 * 1024 * 1024),
                timeout=timeout_seconds,
            )
            try:
                writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
                await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
                response = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, TimeoutError) as exc:
            # Submission may have reached Herdr before a timeout or link loss.
            # The caller must inspect its exact pane before deciding to retry.
            raise HerdrBridgeError(f"Herdr {method} outcome is unknown: {exc}") from exc
        if not response:
            raise HerdrBridgeError(f"Herdr {method} returned no receipt; outcome is unknown.")
        try:
            body = json.loads(response)
        except ValueError as exc:
            raise HerdrBridgeError("Herdr returned invalid JSON; outcome is unknown.") from exc
        if not isinstance(body, dict) or body.get("id") != request_id:
            raise HerdrBridgeError("Herdr returned a mismatched receipt; outcome is unknown.")
        if "error" in body:
            try:
                detail = body["error"]["message"]
            except (KeyError, TypeError):
                detail = "unknown error"
            raise HerdrBridgeError(f"Herdr {method} failed: {detail}")
        try:
            result = body["result"]
        except KeyError as exc:
            raise HerdrBridgeError("Herdr returned no valid JSON result.") from exc
        if not isinstance(result, dict):
            raise HerdrBridgeError("Herdr result is not an object.")
        return result

    async def start(
        self,
        *,
        parent_pane_id: str,
        cwd: Path,
        provider: Literal["codex", "claude"],
        name: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> HerdrNativeAgent:
        """Create a right sibling without focus and start its native agent."""

        if not _PANE_ID.fullmatch(parent_pane_id):
            raise ValueError("A live explicit Herdr parent pane ID is required.")
        if not _AGENT_NAME.fullmatch(name):
            raise ValueError("Herdr agent name is invalid.")
        if provider not in {"codex", "claude"}:
            raise ValueError("Herdr supports only Codex and Claude native agents.")
        if not cwd.is_absolute() or not cwd.is_dir():
            raise ValueError("Herdr native-agent cwd must be an existing absolute directory.")
        if env is not None and any(
            not _ENV_NAME.fullmatch(key) or not isinstance(value, str) for key, value in env.items()
        ):
            raise ValueError("Herdr pane environment is invalid.")
        split = await self._api(
            "pane.split",
            {
                "target_pane_id": parent_pane_id,
                "direction": "right",
                "cwd": str(cwd),
                "focus": False,
                "env": env or {},
            },
        )
        pane = split.get("pane")
        pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
        if not isinstance(pane_id, str) or not _PANE_ID.fullmatch(pane_id):
            raise HerdrBridgeError("Herdr split returned no valid pane ID.")
        agent_started_at: float | None = None
        try:
            # Herdr starts canonical agent names through the pane's interactive
            # shell. User aliases can silently add bypass-permission flags, so
            # clear them in this newly owned pane before agent.start.
            await self._api(
                "pane.send_text",
                {
                    "pane_id": pane_id,
                    "text": "unalias codex claude 2>/dev/null || true; "
                    "unset -f codex claude 2>/dev/null || true; "
                    "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n",
                },
            )
            deadline = time.monotonic() + HERDR_NATIVE_SHELL_READY_TIMEOUT_SECONDS
            while True:
                try:
                    await self._api(
                        "agent.start",
                        {"name": name, "kind": provider, "pane_id": pane_id, "args": args},
                    )
                    agent_started_at = time.monotonic()
                    break
                except HerdrBridgeError as exc:
                    if "not an available shell" not in str(exc) or time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(HERDR_NATIVE_SHELL_RETRY_SECONDS)
            agent = HerdrNativeAgent(pane_id=pane_id, provider=provider, name=name)
            deadline = time.monotonic() + HERDR_NATIVE_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                result = await self._api("agent.get", {"target": pane_id})
                info = result.get("agent")
                if not isinstance(info, dict) or info.get("pane_id") != pane_id:
                    raise HerdrBridgeError("Herdr startup returned a different pane.")
                if info.get("agent") == provider and info.get("name") == name:
                    if info.get("agent_status") == "blocked":
                        raise HerdrBridgeError(
                            "Herdr agent is blocked during startup; check native "
                            "workspace trust or authentication."
                        )
                    if info.get("agent_status") in {"idle", "done"}:
                        return agent
                if info.get("launch_pending") is not True and info.get("agent") != provider:
                    raise HerdrBridgeError("Herdr native agent exited before becoming ready.")
                await asyncio.sleep(HERDR_NATIVE_SHELL_RETRY_SECONDS)
            raise HerdrBridgeError("Herdr native agent did not become ready in time.")
        except HerdrBridgeError as exc:
            # This is an invocation-owned pane. A blocked trust prompt or a
            # startup failure cannot retain unrecorded execution authority.
            if agent_started_at is not None:
                await asyncio.sleep(remaining_startup_hold(agent_started_at))
            try:
                await self._api("pane.close", {"pane_id": pane_id})
            except HerdrBridgeError as close_exc:
                raise HerdrBridgeError(
                    f"{exc} Created pane {pane_id} could not be closed: {close_exc}"
                ) from exc
            raise HerdrBridgeError(
                f"{exc} Working directory: {cwd}. Pane {pane_id} was closed."
            ) from exc

    async def get(self, agent: HerdrNativeAgent) -> HerdrAgentObservation:
        result = await self._api("agent.get", {"target": agent.pane_id})
        info = result.get("agent")
        if not isinstance(info, dict):
            raise HerdrBridgeError("Herdr returned no agent information.")
        if (
            info.get("pane_id") != agent.pane_id
            or info.get("agent") != agent.provider
            or info.get("name") != agent.name
        ):
            raise HerdrBridgeError("Herdr pane now hosts a different agent.")
        session = info.get("agent_session")
        session_id = None
        if isinstance(session, dict) and session.get("kind") == "id":
            value = session.get("value")
            session_id = value if isinstance(value, str) and value else None
        state = info.get("agent_status")
        if not isinstance(state, str):
            raise HerdrBridgeError("Herdr agent state is missing.")
        revision = info.get("revision")
        seq = info.get("state_change_seq", 0)
        if not isinstance(revision, int) or not isinstance(seq, int):
            raise HerdrBridgeError("Herdr agent revision is invalid.")
        return HerdrAgentObservation(
            pane_id=agent.pane_id,
            provider=agent.provider,
            name=agent.name,
            state=state,
            revision=revision,
            state_change_seq=seq,
            session_id=session_id,
        )

    async def prompt(self, agent: HerdrNativeAgent, text: str) -> HerdrAgentObservation:
        """Submit once. Even a successful response is only a delivery receipt."""

        if not text.strip():
            raise ValueError("Herdr prompt must not be empty.")
        before = await self.get(agent)
        if before.state not in {"idle", "done"}:
            raise HerdrBridgeError(f"Herdr agent is not ready for a prompt ({before.state}).")
        await self._api("agent.prompt", {"target": agent.pane_id, "text": text})
        return await self.get(agent)

    async def wait(self, agent: HerdrNativeAgent, *, timeout_ms: int) -> HerdrAgentObservation:
        """Wait for a settled UI state; never interpret it as provider success."""

        if timeout_ms <= 0:
            raise ValueError("Herdr wait timeout must be positive.")
        await self._api(
            "agent.wait",
            {"target": agent.pane_id, "timeout_ms": timeout_ms},
            timeout_seconds=timeout_ms / 1000 + 5,
        )
        observation = await self.get(agent)
        if observation.state not in _SETTLED_STATES:
            raise HerdrBridgeError("Herdr wait did not establish a settled agent state.")
        return observation

    async def process_info(self, agent: HerdrNativeAgent) -> HerdrProcessIdentity:
        """Identify the current foreground process group, refusing stale panes."""

        await self.get(agent)
        result = await self._api("pane.process_info", {"pane_id": agent.pane_id})
        info = result.get("process_info")
        if not isinstance(info, dict) or info.get("pane_id") != agent.pane_id:
            raise HerdrBridgeError("Herdr returned process info for a different pane.")
        group_id = info.get("foreground_process_group_id")
        processes = info.get("foreground_processes")
        if not isinstance(group_id, int) or group_id <= 0 or not isinstance(processes, list):
            raise HerdrBridgeError("Herdr foreground process group is unavailable.")
        if not any(isinstance(item, dict) and item.get("pid") == group_id for item in processes):
            raise HerdrBridgeError("Herdr foreground process group leader is not visible.")
        await self.get(agent)
        return HerdrProcessIdentity(agent.pane_id, group_id, group_id)

    async def session_active(
        self, provider: Literal["codex", "claude"], session_id: str, *, cwd: Path
    ) -> bool | None:
        """Check live Herdr agents; None means an unreported session may exist."""

        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("Herdr native-session ID is invalid.")
        result = await self._api("agent.list", {})
        agents = result.get("agents")
        if not isinstance(agents, list):
            raise HerdrBridgeError("Herdr agent inventory is unavailable.")
        uncertain = False
        for item in agents:
            if not isinstance(item, dict) or item.get("agent") != provider:
                continue
            session = item.get("agent_session")
            if (
                isinstance(session, dict)
                and session.get("kind") == "id"
                and session.get("value") == session_id
            ):
                return True
            if (not isinstance(session, dict) or session.get("kind") != "id") and item.get(
                "cwd"
            ) == str(cwd):
                uncertain = True
        return None if uncertain else False

    async def close(self, agent: HerdrNativeAgent) -> None:
        """Close only a pane still reporting this exact named agent."""

        await self.get(agent)
        result = await self._api("pane.close", {"pane_id": agent.pane_id})
        if result.get("type") not in {"pane_closed", "ok"}:
            raise HerdrBridgeError("Herdr did not confirm pane closure.")

    async def pane_present(self, pane_id: str) -> bool:
        """Use the workspace inventory to confirm an owned pane is gone."""

        if not _PANE_ID.fullmatch(pane_id):
            raise ValueError("Herdr pane ID is invalid.")
        workspace = pane_id.split(":", 1)[0]
        result = await self._api("pane.list", {"workspace_id": workspace})
        panes = result.get("panes")
        if not isinstance(panes, list):
            raise HerdrBridgeError("Herdr pane inventory is unavailable.")
        return any(isinstance(item, dict) and item.get("pane_id") == pane_id for item in panes)
