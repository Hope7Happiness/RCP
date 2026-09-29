from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rcp.provider_history import read_codex_history

from .helpers import create_named_app


def _session_file(manifest, session_id: str, *, cwd: str | None = None) -> Path:
    root = Path(manifest.sources.codex_roots[0]) / "2026" / "09" / "29"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-09-29T00-00-00-{session_id}.jsonl"
    records = [
        {
            "type": "session_meta",
            "timestamp": "2026-09-29T00:00:00Z",
            "payload": {
                "id": session_id,
                "cwd": cwd or manifest.repository_map["repo-b"].path,
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-29T00:00:01Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Earlier question"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-29T00:00:02Z",
            "payload": {
                "type": "function_call",
                "name": "shell",
                "arguments": "private tool input",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-29T00:00:03Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Earlier answer"}],
            },
        },
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    return path


def test_codex_history_reads_only_messages_from_exact_repository_session(manifest, tmp_path):
    session_id = str(uuid.uuid4())
    path = _session_file(manifest, session_id)
    imported = read_codex_history(manifest, session_id)
    assert imported["repository_alias"] == "repo-b"
    assert [(item["role"], item["phase"], item["text"]) for item in imported["messages"]] == [
        ("user", None, "Earlier question"),
        ("assistant", "final_answer", "Earlier answer"),
    ]
    assert imported["source_bytes"] == path.stat().st_size
    assert "private tool input" not in json.dumps(imported)

    path.write_text(path.read_text() + '{"type":"response_item"', encoding="utf-8")
    assert read_codex_history(manifest, session_id)["messages"] == imported["messages"]

    with pytest.raises(ValueError, match="exactly one local project repository"):
        _session_file(manifest, session_id, cwd=str(tmp_path / "elsewhere"))
        read_codex_history(manifest, session_id)


def test_imported_history_is_idempotent_read_only_and_refreshable(manifest, tmp_path):
    session_id = str(uuid.uuid4())
    path = _session_file(manifest, session_id)
    app = create_named_app(str(manifest.path), data_dir=tmp_path / "data")
    project_id = app.state.default_project_id
    base = f"/api/projects/{project_id}/provider-history"

    with TestClient(app) as client:
        first = client.post(f"{base}/codex", json={"session_id": session_id})
        assert first.status_code == 200, first.text
        assert first.json()["message_count"] == 2
        imported_at = first.json()["imported_at"]
        assert (
            client.post(f"{base}/codex", json={"session_id": session_id}).json()["imported_at"]
            == imported_at
        )
        assert len(client.get(base).json()) == 1
        page = client.get(f"{base}/codex/{session_id}?offset=1&limit=1")
        assert page.status_code == 200
        assert [item["text"] for item in page.json()["messages"]] == ["Earlier answer"]
        assert client.get(f"/api/projects/{project_id}/chats").json()["total"] == 0

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "response_item",
                        "timestamp": "2026-09-29T00:00:04Z",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Later question"}],
                        },
                    }
                )
                + "\n"
            )
        assert (
            client.post(f"{base}/codex", json={"session_id": session_id}).json()["message_count"]
            == 3
        )
        assert (
            client.get(f"{base}/codex/{session_id}").json()["messages"][-1]["text"]
            == "Later question"
        )
