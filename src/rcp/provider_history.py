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


def read_codex_history(manifest: Manifest, session_id: str) -> dict[str, Any]:
    """Read one complete native-file prefix and retain only visible messages."""

    session_id = _canonical_session_id(session_id)
    path = _session_file(manifest, session_id)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > PROVIDER_HISTORY_SOURCE_MAX_BYTES:
            raise ValueError("The Codex session file is unavailable or exceeds the import limit.")
        digest = hashlib.sha256()
        messages: list[dict[str, Any]] = []
        session_meta: dict[str, Any] | None = None
        total_chars = 0
        consumed = 0
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            for line_number, line in enumerate(source, start=1):
                if consumed + len(line) > before.st_size:
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
    if not messages:
        raise ValueError("The Codex session has no importable user or assistant messages.")
    return {
        "provider": "codex",
        "session_id": session_id,
        "source_path_sha256": hashlib.sha256(os.fsencode(path)).hexdigest(),
        "source_sha256": digest.hexdigest(),
        "source_bytes": consumed,
        "repository_alias": _repository_alias(manifest, session_meta.get("cwd", "")),
        "first_timestamp": messages[0]["timestamp"],
        "last_timestamp": messages[-1]["timestamp"],
        "messages": messages,
    }
