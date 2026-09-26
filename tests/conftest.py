from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from rcp.background import BackgroundAgentTasks
from rcp.config import Manifest, load_manifest


@pytest.fixture(autouse=True)
def account_credential_lock_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the cross-process credential lock out of the human's own home.

    A provider launch takes an advisory lock under the account's RCP directory.
    Left alone, every test would contend on one real file and leave state in
    `~/.rcp`, so each test gets its own root.
    """

    monkeypatch.setattr(
        "rcp.agents.credential_gate._DEFAULT_ACCOUNT_LOCK_ROOT",
        tmp_path / "credential-locks",
    )


@pytest.fixture(autouse=True)
def ssh_control_socket_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the mux-socket sweep out of the human's own live connections.

    The SSH control directory is keyed by user account, not by data directory,
    so the developer's own RCP keeps its live masters in the same place a test
    would sweep. Starting an app runs that sweep, which means the whole suite
    reaches it, not one test. Each test gets its own root instead.
    """

    monkeypatch.setattr(
        "rcp.transport.ssh._control_directory_path",
        lambda: tmp_path / "ssh-control",
    )


@pytest.fixture(autouse=True)
def unconfigured_local_providers(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the suite off the machine's installed provider CLIs.

    Discovery is the seam every unconfigured local provider execution passes
    through: readiness runs `--version`, `login status` and `debug models`
    through the path it returns, and a turn's own `codex exec` is built from
    that same path. No fixture configures a binary, so leaving discovery live
    meant a test that dispatched a task prompted the developer's own
    authenticated CLI and billed a real provider turn no assertion ever read.
    Returning nothing makes readiness `unconfigured`, which refuses the launch
    before a command is built.

    Readiness reaches this only for an unconfigured local provider, so an
    explicit `binary=` is unaffected; that is how the env-gated live
    qualification in `test_server_provider_readiness_live.py` still probes a
    real CLI on purpose. A test that needs a configured provider patches
    `AgentLauncher.readiness` or replaces `BackgroundAgentTasks.stream`; one
    that needs a real child process stages its own stub through
    `sys.executable`.

    `real_provider_discovery` opts a test out. It is for the unit tests of the
    helper itself, which already stub `shutil.which` and `pwd.getpwuid`, so
    they reach no installed binary either.
    """

    if request.node.get_closest_marker("real_provider_discovery"):
        return
    monkeypatch.setattr("rcp.agents.launcher._discover_local_provider", lambda provider: None)


@pytest.fixture(autouse=True)
def unprobed_compute_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep app startup from launching real helper and scheduler probe jobs.

    A lifespan and a compute settings save check compute routes, and a helper
    probe starts a real launchd or systemd job. A test of the refresh restores
    the real function and stubs the probe itself.
    """

    for owner in ("rcp.api.app", "rcp.api.project_state"):
        monkeypatch.setattr(f"{owner}.refresh_compute_probes", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def terminated_background_tasks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Stop every provider worker a test started, whether or not it ran a lifespan.

    `shutdown` kills each live provider process group, and the app lifespan is
    the only caller. Most tests build their app with a bare `create_app` or an
    unentered `TestClient`, so no lifespan ever runs; their workers are daemon
    threads, so interpreter exit drops them without unwinding and the staged
    broker plus its provider child are reparented and left running, holding a
    `/tmp/rcp-command-*.sock` for as long as they live. Registering at
    construction covers every engine a test creates, including the ones reached
    through `create_app` and server-operation validation.
    """

    engines: list[BackgroundAgentTasks] = []
    construct = BackgroundAgentTasks.__init__

    def register(self: BackgroundAgentTasks, *args: object, **kwargs: object) -> None:
        construct(self, *args, **kwargs)  # type: ignore[arg-type]
        engines.append(self)

    monkeypatch.setattr(BackgroundAgentTasks, "__init__", register)
    yield
    for engine in engines:
        engine.shutdown()


@pytest.fixture(autouse=True)
def fresh_canonical_lock_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own shutdown fence.

    An app lifespan teardown sets the process-wide fence; without isolation a
    later lock wait in the same worker would abort for no reason.
    """

    monkeypatch.setattr("rcp.transport.state._CANONICAL_LOCK_WAIT_FENCE", threading.Event())


@pytest.fixture(autouse=True)
def fixed_terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the width the console renderers wrap to.

    `_print_wrapped` takes its width from `shutil.get_terminal_size`, so every
    assertion on rendered prose otherwise depends on the ambient terminal. The
    same install plan passes at 100 columns and fails at 80, where a phrase a
    test searches for straddles a line break. 100 is the renderer's own
    fallback, so this pins the value an undetectable terminal already produces.
    """

    monkeypatch.setenv("COLUMNS", "100")


@pytest.fixture
def manifest(tmp_path: Path) -> Manifest:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    research = repo_a / ".research"
    research.mkdir()
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    claude_root.mkdir()
    codex_root.mkdir()
    path = research / "manifest.toml"
    path.write_text(
        f'''name = "test-paper"

[[machines]]
alias = "laptop"
host = ""

[[repositories]]
alias = "repo-a"
machine = "laptop"
path = "{repo_a}"

[[repositories]]
alias = "repo-b"
machine = "laptop"
path = "{repo_b}"

[project]
truth_scope = ["repo-a", "repo-b"]

[state]
repository = "repo-a"

[agent]
default_run_truth_scope = ["repo-a"]

[sources]
claude_roots = ["{claude_root}"]
codex_roots = ["{codex_root}"]

[execution]
run_on = "laptop"

[paper.coach]
default_provider = "codex"
default_model = ""
default_reasoning = "medium"
''',
        encoding="utf-8",
    )
    return load_manifest(path)


@pytest.fixture(autouse=True)
def disabled_release_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test apps never contact GitHub; transport tests opt in against loopback."""
    monkeypatch.setenv("RCP_UPDATE_CHECK", "off")
