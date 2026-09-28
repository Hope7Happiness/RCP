from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcp.agents.herdr_receipts import claude_turn_receipt, codex_turn_receipt


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
