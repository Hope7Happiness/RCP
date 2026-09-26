from __future__ import annotations

import fcntl
import runpy
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update-from-source"


@pytest.fixture
def updater(tmp_path, monkeypatch):
    module = SimpleNamespace(**runpy.run_path(str(SCRIPT)))
    (tmp_path / ".git").mkdir()
    calls = []
    state = {"branch": "feature", "dirty": "", "fail": None, "fail_once": False}

    def execute(args, **kwargs):
        calls.append(args)
        if args == state["fail"]:
            if state["fail_once"]:
                state["fail"] = None
            raise subprocess.CalledProcessError(1, args)
        output = ""
        if args[1:2] == ["status"]:
            output = state["dirty"]
        elif args[1:] == ["rev-parse", "HEAD"]:
            output = "a" * 40
        elif args[1:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            output = state["branch"]
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(module.subprocess, "run", execute)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/tools/{name}")
    return module, tmp_path, calls, state


@pytest.mark.parametrize("branch", ["HEAD", "feature", "v0.4.3"])
@pytest.mark.parametrize("desktop", [False, True])
def test_exact_tag_and_build_order(updater, branch, desktop):
    module, root, calls, state = updater
    state["branch"] = branch
    module.update(root, "v0.4.3", desktop)
    start = calls.index(["git", "fetch", "origin", "refs/tags/v0.4.3:refs/tags/v0.4.3"])
    expected = [
        ["git", "checkout", "--detach", "refs/tags/v0.4.3"],
        ["npm", "--prefix", "web", "ci"],
        ["npm", "--prefix", "web", "run", "build"],
        ["uv", "sync"],
    ]
    if desktop:
        expected.append(["npm", "--prefix", "web", "run", "desktop:build-dev"])
    assert calls[start + 1 :] == expected


@pytest.mark.parametrize("reason", ["dirty", "rust", "tag", "leading_zero", "lock"])
def test_preflight_refuses_before_mutations(updater, monkeypatch, reason):
    module, root, calls, state = updater
    state["dirty"] = "?? new-file" if reason == "dirty" else ""
    if reason == "rust":
        monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "rustc" else name)
    with (root / ".rcp-serve.lock").open("a") as lock:
        if reason == "lock":
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(module.UpdateError):
            tag = {"tag": "bad", "leading_zero": "v0.04.3"}.get(reason, "v0.4.3")
            module.update(root, tag, True)
    assert not any(args[0] in {"npm", "uv"} or args[1] in {"fetch", "checkout"} for args in calls)


@pytest.mark.parametrize("branch", ["feature", "HEAD"])
@pytest.mark.parametrize(
    "failed", [["uv", "sync"], ["npm", "--prefix", "web", "run", "desktop:build-dev"]]
)
@pytest.mark.parametrize("restore_fails", [False, True])
def test_failed_update_restores_the_start_and_its_build(
    updater, capsys, branch, failed, restore_fails
):
    module, root, calls, state = updater
    state.update(branch=branch, fail=failed, fail_once=not restore_fails)
    with pytest.raises(module.UpdateError):
        module.update(root, "v0.4.3", True)
    recovery = (
        ["git", "checkout", "--detach", "a" * 40] if branch == "HEAD" else ["git", "switch", branch]
    )
    after = calls[calls.index(failed) + 1 :]
    build = [args for _, args in module.BUILD_STEPS]
    assert after == [recovery, *build]
    if restore_fails and failed == ["uv", "sync"]:
        # The restore stops at the same step and lists every remaining command.
        err = capsys.readouterr().err
        assert all(shlex.join(args) in err for args in [recovery, *build])
    with (root / ".rcp-serve.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
