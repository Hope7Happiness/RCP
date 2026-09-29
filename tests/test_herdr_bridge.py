from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from rcp.agents.herdr_bridge import (
    HerdrBridgeError,
    HerdrNativeAdapter,
    HerdrNativeAgent,
    build_native_agent_args,
    cleanup_isolated_codex_home,
    isolated_codex_home,
)
from rcp.agents.write_scope import ProjectWriteScope, WritableRepositoryRoot
from rcp.providers import ProviderTurnRequest


def _request(
    tmp_path: Path,
    capability: str,
    scope: ProjectWriteScope | None = None,
    provider: str = "codex",
):
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    return ProviderTurnRequest(
        prompt="Investigate the result.",
        binary=shutil.which(provider) or provider,
        cwd=stage,
        model="selected-model",
        reasoning="high",
        session_id=None,
        read_dirs=[],
        write_dirs=[Path(path) for path in scope.repository_roots] if scope else [],
        write_scope=scope,
        capability=capability,
        provider_version="9.9.9",
    )


def _scope(tmp_path: Path) -> ProjectWriteScope:
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    repo = tmp_path / "repository"
    repo.mkdir(exist_ok=True)
    return ProjectWriteScope.create(
        project_id="project",
        execution_machine="local",
        execution_host="",
        capability="work_auto",
        stage_root=str(stage),
        workspace_root=str(stage),
        repositories=[WritableRepositoryRoot(alias="source", machine="local", path=str(repo))],
        protected_write_paths=[str(repo / ".research")],
    )


def test_native_work_args_preserve_exact_provider_scope(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    claude = build_native_agent_args("claude", _request(tmp_path, "work_auto", scope, "claude"))
    settings = json.loads(claude[claude.index("--settings") + 1])
    assert settings["permissions"]["defaultMode"] == "dontAsk"
    assert any(str(scope.repository_roots[0]) in item for item in settings["permissions"]["allow"])
    assert any(
        str(scope.protected_write_paths[0]) in item for item in settings["permissions"]["deny"]
    )
    assert claude[claude.index("--mcp-config") + 1] == '{"mcpServers":{}}'


def test_native_args_refuse_unsupported_or_unscoped_launch(tmp_path: Path) -> None:
    request = _request(tmp_path, "work_auto")
    with pytest.raises(ValueError, match="resolved project write scope"):
        build_native_agent_args("codex", request)
    with pytest.raises(ValueError, match="resolved project write scope"):
        build_native_agent_args("claude", _request(tmp_path, "work_auto", provider="claude"))
    with pytest.raises(ValueError, match="no Herdr native-agent contract"):
        build_native_agent_args("claude", _request(tmp_path, "orchestrate", provider="claude"))
    assert "acceptEdits" in build_native_agent_args(
        "claude", _request(tmp_path, "discuss", provider="claude")
    )


def test_codex_native_args_use_exact_scope_and_no_bypass(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    args = build_native_agent_args("codex", _request(tmp_path, "work_auto", scope))
    assert "--no-daemon" in args
    assert "--strict-config" in args
    assert 'default_permissions="rcp_project"' in args
    assert any(str(scope.repository_roots[0]) in arg for arg in args)
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    assert "--sandbox" not in args
    discuss = build_native_agent_args("codex", _request(tmp_path, "discuss"))
    assert discuss[discuss.index("--sandbox") + 1] == "read-only"
    resumed = build_native_agent_args(
        "codex", replace(_request(tmp_path, "discuss"), session_id="session-1")
    )
    assert resumed[-2:] == ["resume", "session-1"]


def test_codex_native_home_hides_ambient_config_and_keeps_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original-home"
    source.mkdir()
    (source / "sessions").mkdir()
    (source / "auth.json").write_text("credential fixture")
    (source / "config.toml").write_text('sandbox_mode = "danger-full-access"')
    (source / "rules").mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = isolated_codex_home(workspace)
    try:
        assert (home / "auth.json").resolve() == source / "auth.json"
        assert (home / "sessions").resolve() == source / "sessions"
        assert not (home / "rules").exists()
        config = (home / "config.toml").read_text()
        assert "danger-full-access" not in config
        assert str(workspace) in config
    finally:
        cleanup_isolated_codex_home(str(home))
    assert not home.exists()


def test_recovered_codex_home_cleanup_is_bounded(tmp_path: Path) -> None:
    home = Path(tempfile.mkdtemp(prefix="rcp-codex-home-", dir="/tmp"))
    (home / "config.toml").write_text("temporary")
    cleanup_isolated_codex_home(str(home))
    cleanup_isolated_codex_home(str(home))
    assert not home.exists()
    with pytest.raises(ValueError, match="invalid Codex home"):
        cleanup_isolated_codex_home(str(tmp_path))


def test_native_resume_preserves_scope_and_rejects_wrong_binary(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    claude_request = replace(
        _request(tmp_path, "work_auto", scope, "claude"), session_id="session-1"
    )
    claude = build_native_agent_args("claude", claude_request)
    assert claude[-2:] == ["--resume", "session-1"]
    with pytest.raises(ValueError, match="canonical provider executable differs"):
        build_native_agent_args("claude", replace(claude_request, binary="/other/claude"))
    fresh = build_native_agent_args(
        "claude",
        _request(tmp_path, "discuss", provider="claude"),
        fresh_session_id="123e4567-e89b-12d3-a456-426614174000",
    )
    assert fresh[-2:] == ["--session-id", "123e4567-e89b-12d3-a456-426614174000"]


class _FakeHerdr(HerdrNativeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, ...]] = []
        self.state = "idle"
        self.name = "rcpworker"
        self.unknown_cwd = "/other/workspace"

    async def _api(
        self, method: str, params: dict[str, object], *, timeout_seconds: float = 35
    ) -> dict[str, object]:
        del timeout_seconds
        self.calls.append((method, json.dumps(params, sort_keys=True)))
        if method == "pane.split":
            return {"pane": {"pane_id": "w1:p2"}}
        if method == "agent.get":
            return {
                "agent": {
                    "pane_id": "w1:p2",
                    "agent": "codex",
                    "name": self.name,
                    "agent_status": self.state,
                    "revision": 3,
                    "state_change_seq": 4,
                    "agent_session": {
                        "kind": "id",
                        "source": "provider",
                        "agent": "codex",
                        "value": "session-1",
                    },
                }
            }
        if method == "pane.process_info":
            return {
                "process_info": {
                    "pane_id": "w1:p2",
                    "foreground_process_group_id": 123,
                    "foreground_processes": [{"pid": 123, "name": "codex"}],
                }
            }
        if method == "agent.list":
            return {
                "agents": [
                    {
                        "agent": "codex",
                        "cwd": "/other/workspace",
                        "agent_session": {"kind": "id", "value": "session-1"},
                    },
                    {"agent": "codex", "cwd": self.unknown_cwd},
                ]
            }
        if method == "pane.close":
            return {"type": "ok"}
        return {}


@pytest.mark.asyncio
async def test_start_uses_explicit_sibling_and_prompt_is_only_delivery(tmp_path: Path) -> None:
    herdr = _FakeHerdr()
    agent = await herdr.start(
        parent_pane_id="w1:p1",
        cwd=tmp_path,
        provider="codex",
        name="rcpworker",
        args=["--model", "selected-model"],
        env={"EXAMPLE_TOKEN": "secret-value"},
    )
    assert agent == HerdrNativeAgent("w1:p2", "codex", "rcpworker")
    split = herdr.calls[0]
    assert split[0] == "pane.split"
    assert json.loads(split[1]) == {
        "target_pane_id": "w1:p1",
        "direction": "right",
        "cwd": str(tmp_path),
        "focus": False,
        "env": {"EXAMPLE_TOKEN": "secret-value"},
    }
    assert herdr.calls[1][0] == "pane.send_text"
    assert json.loads(herdr.calls[1][1]) == {
        "pane_id": "w1:p2",
        "text": "unalias codex claude 2>/dev/null || true; "
        "unset -f codex claude 2>/dev/null || true; "
        "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n",
    }
    assert herdr.calls[2][0] == "agent.start"
    assert json.loads(herdr.calls[2][1]) == {
        "name": "rcpworker",
        "kind": "codex",
        "pane_id": "w1:p2",
        "args": ["--model", "selected-model"],
    }
    observation = await herdr.prompt(agent, "Investigate.")
    assert (
        "agent.prompt",
        json.dumps({"target": "w1:p2", "text": "Investigate."}, sort_keys=True),
    ) in herdr.calls
    assert observation.session_id == "session-1"
    assert observation.state == "idle"  # This observation is not an RCP result.


@pytest.mark.asyncio
async def test_blocked_native_start_closes_its_owned_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    herdr = _FakeHerdr()
    herdr.state = "blocked"
    monkeypatch.setattr("rcp.agents.herdr_bridge.remaining_startup_hold", lambda *_args: 0)
    with pytest.raises(HerdrBridgeError, match="was closed"):
        await herdr.start(
            parent_pane_id="w1:p1",
            cwd=tmp_path,
            provider="claude",
            name="rcpworker",
            args=[],
        )
    assert herdr.calls[-1][0] == "pane.close"


@pytest.mark.asyncio
async def test_changed_occupant_and_blocked_agent_refuse_prompt() -> None:
    herdr = _FakeHerdr()
    agent = HerdrNativeAgent("w1:p2", "codex", "rcpworker")
    herdr.name = "other-agent"
    with pytest.raises(HerdrBridgeError, match="different agent"):
        await herdr.prompt(agent, "Investigate.")
    herdr.name = "rcpworker"
    herdr.state = "blocked"
    with pytest.raises(HerdrBridgeError, match="not ready"):
        await herdr.prompt(agent, "Investigate.")
    assert not any(call[0] == "agent.prompt" for call in herdr.calls)


@pytest.mark.asyncio
async def test_process_identity_session_fence_and_close() -> None:
    herdr = _FakeHerdr()
    agent = HerdrNativeAgent("w1:p2", "codex", "rcpworker")
    identity = await herdr.process_info(agent)
    assert identity.group_leader_pid == 123
    assert await herdr.session_active("codex", "session-1", cwd=Path("/stage")) is True
    assert await herdr.session_active("codex", "other-session", cwd=Path("/stage")) is False
    herdr.unknown_cwd = "/stage"
    assert await herdr.session_active("codex", "other-session", cwd=Path("/stage")) is None
    await herdr.close(agent)
    assert herdr.calls[-1][0] == "pane.close"
