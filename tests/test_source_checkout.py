from __future__ import annotations

import fcntl

import pytest

from rcp import source_checkout


@pytest.mark.parametrize("marker", ["directory", "file", None])
def test_checkout_identity_comes_from_package_root(tmp_path, monkeypatch, marker) -> None:
    monkeypatch.setattr(source_checkout, "__file__", str(tmp_path / "src/rcp/source_checkout.py"))
    if marker == "directory":
        (tmp_path / ".git").mkdir()
    elif marker == "file":
        (tmp_path / ".git").write_text("gitdir: elsewhere\n")
    assert source_checkout.source_checkout_root() == (tmp_path if marker else None)


def test_shared_checkout_owners_both_exclude_updates_until_exit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(source_checkout, "source_checkout_root", lambda: tmp_path)
    with (tmp_path / ".rcp-serve.lock").open("a") as updater:
        with source_checkout.source_checkout_lock():
            with source_checkout.source_checkout_lock(), pytest.raises(BlockingIOError):
                fcntl.flock(updater, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                fcntl.flock(updater, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(updater, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_server_refuses_instead_of_waiting_behind_an_update(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(source_checkout, "source_checkout_root", lambda: tmp_path)
    with (tmp_path / ".rcp-serve.lock").open("a") as updater:
        fcntl.flock(updater, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit), source_checkout.source_checkout_lock():
            pass
