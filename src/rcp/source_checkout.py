"""Lifetime coordination between source servers and the source updater."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def source_checkout_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    marker = root / ".git"
    return root if marker.is_dir() or marker.is_file() else None


@contextmanager
def source_checkout_lock() -> Iterator[None]:
    """Keep all source backends out of an exclusive source update."""
    root = source_checkout_root()
    if root is None:
        yield
        return
    with (root / ".rcp-serve.lock").open("a") as lock:
        # Never wait: a server that queued behind an update would resume with
        # the old modules it already imported against the new build.
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(
                f"An update of {root} is running; start RCP again when it finishes."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
