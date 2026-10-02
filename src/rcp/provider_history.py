"""Explicit snapshots of local Codex messages for read-only project display.

An imported provider message is never an RCP chat turn, task, answer, or Patch.
Only the native file named by the requested session id is considered, and its
recorded working directory must belong to the receiving project's repositories.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rcp.config import Manifest
from rcp.limits import (
    PROVIDER_HISTORY_MAX_MESSAGES,
    PROVIDER_HISTORY_MESSAGE_MAX_CHARS,
    PROVIDER_HISTORY_SOURCE_MAX_BYTES,
    PROVIDER_HISTORY_TOTAL_MAX_CHARS,
)
from rcp.sources.record_parsing import extract_text


def _canonical_session_id(value: str) -> str:
    try:
        result = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError("session_id must be a canonical UUID") from exc
    if result != value:
        raise ValueError("session_id must be a canonical UUID")
    return result


def _session_file(manifest: Manifest, session_id: str) -> Path:
    candidates: set[Path] = set()
    for raw_root in manifest.sources.codex_roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.is_dir():
            continue
        for path in root.rglob(f"*{session_id}.jsonl"):
            resolved = path.resolve()
            if (
                resolved.is_relative_to(root)
                and resolved.name.endswith(f"-{session_id}.jsonl")
                and path == resolved
            ):
                candidates.add(resolved)
    if len(candidates) != 1:
        raise ValueError(
            "The Codex session must resolve to exactly one local file in the configured roots."
        )
    return candidates.pop()


def _repository_alias(manifest: Manifest, cwd: str) -> str:
    if not isinstance(cwd, str):
        raise ValueError("The Codex session has no working directory.")
    working = Path(cwd)
    if not working.is_absolute():
        raise ValueError("The Codex session has no absolute working directory.")
    working = working.resolve()
    matches = [
        repository.alias
        for repository in manifest.repositories
        if not manifest.machine_map[repository.machine].host
        and working.is_relative_to(Path(repository.path).resolve())
    ]
    if len(matches) != 1:
        raise ValueError("The Codex session must match exactly one local project repository.")
    return matches[0]


def read_codex_history(
    manifest: Manifest, session_id: str, *, prefix_bytes: int | None = None
) -> dict[str, Any]:
    """Read one complete native-file prefix and retain only visible messages."""

    session_id = _canonical_session_id(session_id)
    path = _session_file(manifest, session_id)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        source_bytes = before.st_size if prefix_bytes is None else prefix_bytes
        if (
            not stat.S_ISREG(before.st_mode)
            or source_bytes <= 0
            or source_bytes > PROVIDER_HISTORY_SOURCE_MAX_BYTES
            or before.st_size < source_bytes
        ):
            raise ValueError("The Codex session file is unavailable or exceeds the import limit.")
        digest = hashlib.sha256()
        messages: list[dict[str, Any]] = []
        session_meta: dict[str, Any] | None = None
        total_chars = 0
        consumed = 0
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            for line_number, line in enumerate(source, start=1):
                if consumed + len(line) > source_bytes:
                    break
                if not line.endswith(b"\n"):
                    break
                consumed += len(line)
                digest.update(line)
                try:
                    raw = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "The Codex session contains an invalid complete record."
                    ) from exc
                payload = raw.get("payload") if isinstance(raw, dict) else None
                if not isinstance(payload, dict):
                    continue
                if raw.get("type") == "session_meta":
                    if session_meta is not None:
                        raise ValueError("The Codex session has duplicate identity records.")
                    session_meta = payload
                    continue
                if raw.get("type") != "response_item" or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = extract_text(payload.get("content"))
                if not text:
                    continue
                if len(text) > PROVIDER_HISTORY_MESSAGE_MAX_CHARS:
                    raise ValueError("A Codex message exceeds the import limit.")
                total_chars += len(text)
                if total_chars > PROVIDER_HISTORY_TOTAL_MAX_CHARS:
                    raise ValueError("The Codex messages exceed the import limit.")
                timestamp = raw.get("timestamp")
                if not isinstance(timestamp, str):
                    raise ValueError("A Codex message has no timestamp.")
                try:
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("A Codex message has an invalid timestamp.") from exc
                if parsed.tzinfo is None:
                    raise ValueError("A Codex message has no timestamp zone.")
                phase = payload.get("phase") if role == "assistant" else None
                if phase not in {None, "commentary", "final_answer"}:
                    phase = None
                messages.append(
                    {
                        "message_id": str(
                            uuid.uuid5(uuid.NAMESPACE_URL, f"codex:{session_id}:{line_number}")
                        ),
                        "role": role,
                        "phase": phase,
                        "timestamp": timestamp,
                        "text": text,
                    }
                )
                if len(messages) > PROVIDER_HISTORY_MAX_MESSAGES:
                    raise ValueError("The Codex session has too many messages to import.")
            after = os.fstat(source.fileno())
        if (after.st_dev, after.st_ino) != (
            before.st_dev,
            before.st_ino,
        ) or after.st_size < before.st_size:
            raise ValueError("The Codex session changed identity during import.")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if session_meta is None or session_meta.get("id") != session_id:
        raise ValueError("The Codex session identity does not match the requested id.")
    if prefix_bytes is not None and consumed != prefix_bytes:
        raise ValueError("The imported Codex source prefix is unavailable")
    if not messages:
        raise ValueError("The Codex session has no importable user or assistant messages.")
    source_cwd = session_meta.get("cwd")
    repository_alias = _repository_alias(manifest, source_cwd)
    return {
        "provider": "codex",
        "session_id": session_id,
        "source_path_sha256": hashlib.sha256(os.fsencode(path)).hexdigest(),
        "source_sha256": digest.hexdigest(),
        "source_bytes": consumed,
        "repository_alias": repository_alias,
        # Codex resume compares the original session metadata; preserve its
        # literal absolute cwd even if it names a symlink into the repository.
        "source_cwd": source_cwd,
        "first_timestamp": messages[0]["timestamp"],
        "last_timestamp": messages[-1]["timestamp"],
        "messages": messages,
    }


def reprove_codex_history(manifest: Manifest, stored: dict[str, Any]) -> dict[str, Any]:
    """Prove that an imported transcript remains an exact prefix of its native file."""

    session_id = _canonical_session_id(stored["session_id"])
    path = _session_file(manifest, session_id)
    if hashlib.sha256(os.fsencode(path)).hexdigest() != stored["source_path_sha256"]:
        raise ValueError("The imported Codex source path changed")
    prefix_bytes = stored["source_bytes"]
    if not isinstance(prefix_bytes, int) or prefix_bytes <= 0:
        raise ValueError("The imported Codex source byte length is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < prefix_bytes:
            raise ValueError("The imported Codex source was truncated or replaced")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            remaining = prefix_bytes
            while remaining:
                part = source.read(min(remaining, 1024 * 1024))
                if not part:
                    raise ValueError("The imported Codex source prefix is unavailable")
                digest.update(part)
                remaining -= len(part)
            after = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("The imported Codex source changed identity")
        if digest.hexdigest() != stored["source_sha256"]:
            raise ValueError("The imported Codex source prefix changed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    current = read_codex_history(manifest, session_id)
    if current["repository_alias"] != stored["repository_alias"]:
        raise ValueError("The imported Codex repository binding changed")
    return current


def codex_history_source_size(manifest: Manifest, stored: dict[str, Any]) -> int:
    """Read only the bound file's size for cheap append polling."""

    path = _session_file(manifest, _canonical_session_id(stored["session_id"]))
    if hashlib.sha256(os.fsencode(path)).hexdigest() != stored["source_path_sha256"]:
        raise ValueError("The imported Codex source path changed")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        identity = os.fstat(descriptor)
        if not stat.S_ISREG(identity.st_mode) or identity.st_uid != os.geteuid():
            raise ValueError("The imported Codex source identity is invalid")
        if identity.st_size < stored["source_bytes"]:
            raise ValueError("The imported Codex source was truncated")
        return identity.st_size
    finally:
        os.close(descriptor)
