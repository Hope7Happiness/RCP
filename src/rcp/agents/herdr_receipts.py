"""Strict provider transcript receipts for a Herdr-hosted native turn.

Herdr's idle/done states are presentation state. They never complete an RCP
task. Only a matching provider-authored terminal record can do that.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_SESSION_ID = re.compile(r"[0-9a-fA-F-]{36}\Z")


@dataclass(frozen=True)
class NativeTurnReceipt:
    session_id: str
    answer: str
    turn_id: str | None = None


def _codex_sessions_root(account_home: Path | None = None) -> Path:
    home = account_home or Path.home()
    return Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "sessions"


def codex_transcript_inventory(*, account_home: Path | None = None) -> set[Path]:
    """Snapshot path names before launch; no unrelated transcript is read."""

    root = _codex_sessions_root(account_home)
    return set(root.rglob("*.jsonl")) if root.is_dir() else set()


def find_new_codex_transcript(
    cwd: Path, before: set[Path], *, account_home: Path | None = None
) -> tuple[str, Path] | None:
    """Find the one newly-created Codex transcript for this exact stage."""

    candidates: list[tuple[str, Path]] = []
    for path in codex_transcript_inventory(account_home=account_home) - before:
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.geteuid():
            raise ValueError("Native Codex transcript ownership is invalid.")
        try:
            with path.open("rb") as stream:
                record = json.loads(stream.readline())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue  # The provider may still be writing its first line.
        payload = record.get("payload") if isinstance(record, dict) else None
        if (
            isinstance(payload, dict)
            and record.get("type") == "session_meta"
            and payload.get("cwd") == str(cwd)
            and isinstance(payload.get("id"), str)
            and _SESSION_ID.fullmatch(payload["id"])
        ):
            candidates.append((payload["id"], path))
    if len(candidates) > 1:
        raise ValueError("Several native Codex sessions appeared in the same stage.")
    return candidates[0] if candidates else None


def find_native_transcript(
    provider: str, session_id: str, cwd: Path, *, account_home: Path | None = None
) -> Path | None:
    """Find only the exact provider session attributed to this local stage.

    A missing transcript is pending. Multiple matches, links, or a wrong owner
    are a refusal, never an opportunity to pick the newest other session.
    """

    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Native provider session ID is malformed.")
    home = account_home or Path.home()
    if provider == "codex":
        root = _codex_sessions_root(account_home)
        pattern = f"rollout-*-{session_id}.jsonl"
    elif provider == "claude":
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude"))) / "projects"
        pattern = f"{session_id}.jsonl"
    else:
        raise ValueError("Native transcript provider is unsupported.")
    if not root.is_dir():
        return None
    matches = list(root.rglob(pattern))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Native provider session transcript is ambiguous.")
    path = matches[0]
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.geteuid():
        raise ValueError("Native provider transcript ownership is invalid.")
    with path.open("rb") as stream:
        header = [stream.readline() for _ in range(20 if provider == "claude" else 1)]
    try:
        records = [json.loads(line) for line in header if line]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Native provider transcript header is invalid.") from exc
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("Native provider transcript header is invalid.")
    if provider == "codex":
        record = records[0]
        payload = record.get("payload")
        bound_cwd = payload.get("cwd") if isinstance(payload, dict) else None
        bound_id = payload.get("id") if isinstance(payload, dict) else None
        if record.get("type") != "session_meta" or bound_id != session_id:
            raise ValueError("Native Codex transcript session identity differs.")
    else:
        if any(
            (record.get("sessionId") or record.get("session_id")) not in (None, session_id)
            for record in records
        ):
            raise ValueError("Native Claude transcript session identity differs.")
        bound_cwd = next((record.get("cwd") for record in records if record.get("cwd")), None)
    if bound_cwd is None and provider == "claude":
        return None
    if bound_cwd != str(cwd):
        raise ValueError("Native provider transcript belongs to a different stage.")
    return path


def _records(path: Path, offset: int) -> list[dict[str, object]]:
    if offset < 0 or path.is_symlink() or not path.is_file():
        raise ValueError("Native provider transcript is unavailable.")
    with path.open("rb") as stream:
        if offset > stream.seek(0, 2):
            raise ValueError("Native provider transcript was replaced or truncated.")
        stream.seek(offset)
        data = stream.read()
    # A writer can be in the middle of its final JSON line. Ignore that line
    # until the next read, but reject a malformed complete line.
    complete = data.rsplit(b"\n", 1)[0] if not data.endswith(b"\n") else data
    result: list[dict[str, object]] = []
    for line in complete.splitlines():
        if not line:
            continue
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Native provider transcript contains an invalid record.") from exc
        if not isinstance(value, dict):
            raise ValueError("Native provider transcript contains an invalid record.")
        result.append(value)
    return result


def _text_parts(content: object, kind: str) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(item["text"])
        for item in content
        if isinstance(item, dict) and item.get("type") == kind and isinstance(item.get("text"), str)
    )


def codex_turn_receipt(
    path: Path, *, offset: int, session_id: str, prompt: str
) -> NativeTurnReceipt | None:
    """Read one exact fresh Codex turn, requiring its user input and completion."""

    started: str | None = None
    saw_prompt = False
    for record in _records(path, offset):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "event_msg" and payload.get("type") == "task_started":
            if started is not None:
                raise ValueError("Another native Codex turn started before RCP's turn completed.")
            value = payload.get("turn_id")
            if not isinstance(value, str) or not value:
                raise ValueError("Native Codex turn has no identity.")
            started = value
        elif record.get("type") == "response_item" and payload.get("type") == "message":
            if payload.get("role") == "user":
                text = _text_parts(payload.get("content"), "input_text")
                if not saw_prompt:
                    if text != prompt or started is None:
                        raise ValueError("Native Codex transcript did not start with RCP's prompt.")
                    saw_prompt = True
                else:
                    raise ValueError("A second user turn entered the native Codex session.")
        elif record.get("type") == "event_msg" and payload.get("type") == "task_complete":
            if not saw_prompt or payload.get("turn_id") != started:
                raise ValueError("Native Codex completion does not match RCP's turn.")
            answer = payload.get("last_agent_message")
            if not isinstance(answer, str):
                raise ValueError("Native Codex completion has no labelled final answer.")
            return NativeTurnReceipt(session_id=session_id, answer=answer, turn_id=started)
    return None


def claude_turn_receipt(
    path: Path, *, offset: int, session_id: str, prompt: str
) -> NativeTurnReceipt | None:
    """Require Claude's matching user, final assistant, and turn duration record."""

    saw_prompt = False
    answer: str | None = None
    for record in _records(path, offset):
        record_type = record.get("type")
        if record_type == "user":
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            text = _text_parts(content, "text")
            if not saw_prompt:
                if text != prompt:
                    raise ValueError("Native Claude transcript did not start with RCP's prompt.")
                saw_prompt = True
            elif text:
                raise ValueError("A second user turn entered the native Claude session.")
        elif record_type == "assistant" and saw_prompt:
            message = record.get("message")
            if isinstance(message, dict) and message.get("stop_reason") == "end_turn":
                answer = _text_parts(message.get("content"), "text")
        elif record_type == "system" and record.get("subtype") == "turn_duration":
            if saw_prompt and answer is not None:
                return NativeTurnReceipt(session_id=session_id, answer=answer)
    return None
