from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from rcp.agents.herdr_receipts import (
    claude_turn_receipt,
    codex_turn_receipt,
    find_native_transcript,
)


def _append(path: Path, *records: dict[str, object]) -> None:
    with path.open("a") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")


def test_codex_requires_matching_user_and_terminal_turn(tmp_path: Path) -> None:
    transcript = tmp_path / "codex.jsonl"
    _append(transcript, {"type": "session_meta", "payload": {"id": "session"}})
    offset = transcript.stat().st_size
    _append(
        transcript,
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "do work"}],
            },
        },
    )
    assert (
        codex_turn_receipt(transcript, offset=offset, session_id="session", prompt="do work")
        is None
    )
    _append(
        transcript,
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn",
                "last_agent_message": "Finished.",
            },
        },
    )
    receipt = codex_turn_receipt(transcript, offset=offset, session_id="session", prompt="do work")
    assert receipt is not None
    assert (receipt.answer, receipt.turn_id) == ("Finished.", "turn")


def test_codex_tui_context_is_not_a_human_turn(tmp_path: Path) -> None:
    transcript = tmp_path / "codex.jsonl"
    _append(
        transcript,
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<environment_context>\n<cwd>/stage</cwd>\n</environment_context>",
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "do work"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn",
                "last_agent_message": "Finished.",
            },
        },
    )
    receipt = codex_turn_receipt(transcript, offset=0, session_id="session", prompt="do work")
    assert receipt is not None and receipt.answer == "Finished."


def test_codex_resumed_turn_accepts_provider_instruction_preamble(tmp_path: Path) -> None:
    transcript = tmp_path / "codex.jsonl"
    _append(
        transcript,
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "# AGENTS.md instructions\n\n<INSTRUCTIONS>\n"
                        "The previously provided AGENTS.md instructions no longer apply.\n"
                        "</INSTRUCTIONS>",
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<environment_context>\n<cwd>/stage</cwd>\n</environment_context>",
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "do work"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn",
                "last_agent_message": "Finished.",
            },
        },
    )
    receipt = codex_turn_receipt(transcript, offset=0, session_id="session", prompt="do work")
    assert receipt is not None and receipt.answer == "Finished."


def test_imported_codex_transcript_requires_original_cwd_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    session_id = "123e4567-e89b-12d3-a456-426614174000"
    original = tmp_path / "repository"
    original.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    transcript = sessions / f"rollout-2026-09-29T00-00-00-{session_id}.jsonl"
    _append(
        transcript, {"type": "session_meta", "payload": {"id": session_id, "cwd": str(original)}}
    )
    digest = hashlib.sha256(os.fsencode(transcript)).hexdigest()
    assert (
        find_native_transcript(
            "codex",
            session_id,
            stage,
            account_home=tmp_path,
            origin_cwd=original,
            source_path_sha256=digest,
        )
        == transcript
    )
    with pytest.raises(ValueError, match="different stage"):
        find_native_transcript("codex", session_id, stage, account_home=tmp_path)
    with pytest.raises(ValueError, match="source identity"):
        find_native_transcript(
            "codex",
            session_id,
            stage,
            account_home=tmp_path,
            origin_cwd=original,
            source_path_sha256="0" * 64,
        )


def test_imported_codex_transcript_accepts_symlinked_home_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    session_id = "123e4567-e89b-12d3-a456-426614174000"
    original = tmp_path / "repository"
    original.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    canonical_home = tmp_path / "canonical-home"
    sessions = canonical_home / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    transcript = sessions / f"rollout-2026-09-29T00-00-00-{session_id}.jsonl"
    _append(
        transcript, {"type": "session_meta", "payload": {"id": session_id, "cwd": str(original)}}
    )
    alias_home = tmp_path / "alias-home"
    alias_home.symlink_to(canonical_home, target_is_directory=True)
    digest = hashlib.sha256(os.fsencode(transcript)).hexdigest()

    assert (
        find_native_transcript(
            "codex",
            session_id,
            stage,
            account_home=alias_home,
            origin_cwd=original,
            source_path_sha256=digest,
        ).resolve()
        == transcript
    )


def test_codex_refuses_another_turn_or_wrong_completion(tmp_path: Path) -> None:
    transcript = tmp_path / "codex.jsonl"
    _append(
        transcript,
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "do work"}],
            },
        },
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "other"}},
    )
    with pytest.raises(ValueError, match="does not match"):
        codex_turn_receipt(transcript, offset=0, session_id="session", prompt="do work")


def test_claude_requires_final_assistant_and_turn_duration(tmp_path: Path) -> None:
    transcript = tmp_path / "claude.jsonl"
    _append(
        transcript,
        {"type": "user", "message": {"role": "user", "content": "do work"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Finished."}],
            },
        },
    )
    assert claude_turn_receipt(transcript, offset=0, session_id="session", prompt="do work") is None
    _append(transcript, {"type": "system", "subtype": "turn_duration"})
    receipt = claude_turn_receipt(transcript, offset=0, session_id="session", prompt="do work")
    assert receipt is not None and receipt.answer == "Finished."


def test_claude_refuses_mismatched_prompt(tmp_path: Path) -> None:
    transcript = tmp_path / "claude.jsonl"
    _append(transcript, {"type": "user", "message": {"content": "unrelated"}})
    with pytest.raises(ValueError, match="did not start"):
        claude_turn_receipt(transcript, offset=0, session_id="session", prompt="do work")
