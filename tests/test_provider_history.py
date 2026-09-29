from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rcp.provider_history import read_codex_history, reprove_codex_history

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
        status_url = f"{base}/codex/{session_id}/source-status"
        assert client.get(status_url).json() == {
            "source_bytes": path.stat().st_size,
            "imported_bytes": path.stat().st_size,
        }
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
        source_status = client.get(status_url).json()
        assert source_status["source_bytes"] > source_status["imported_bytes"]
        assert (
            client.post(f"{base}/codex", json={"session_id": session_id}).json()["message_count"]
            == 3
        )
        refreshed_status = client.get(status_url).json()
        assert refreshed_status["source_bytes"] == refreshed_status["imported_bytes"]
        assert (
            client.get(f"{base}/codex/{session_id}").json()["messages"][-1]["text"]
            == "Later question"
        )


def test_codex_continuation_claim_is_exclusive_and_survives_restart(manifest, tmp_path):
    session_id = str(uuid.uuid4())
    path = _session_file(manifest, session_id)
    app = create_named_app(str(manifest.path), data_dir=tmp_path / "data")
    store = app.state.background_tasks.store
    project_id = app.state.default_project_id
    source = read_codex_history(manifest, session_id)
    store.save_provider_history(
        project_id, **{key: value for key, value in source.items() if key != "source_cwd"}
    )
    message_sha = "a" * 64
    first_chat = str(uuid.uuid4())
    first_operation = str(uuid.uuid4())

    def claim(chat_id: str, operation_id: str, *, message: str = message_sha):
        return store.claim_codex_continuation(
            project_id=project_id,
            session_id=session_id,
            chat_id=chat_id,
            first_operation_id=operation_id,
            source_path_sha256=source["source_path_sha256"],
            source_sha256=source["source_sha256"],
            source_bytes=source["source_bytes"],
            source_cwd=source["source_cwd"],
            repository_alias=source["repository_alias"],
            execution_machine="laptop",
            initial_mode="work",
            first_message_sha256=message,
        )

    initial = claim(first_chat, first_operation)
    assert initial["chat_id"] == first_chat
    assert claim(str(uuid.uuid4()), str(uuid.uuid4())) == initial
    with pytest.raises(ValueError, match="different RCP continuation"):
        claim(str(uuid.uuid4()), str(uuid.uuid4()), message="b" * 64)
    assert reprove_codex_history(manifest, store.provider_history(project_id, "codex", session_id))[
        "source_cwd"
    ] == str(Path(manifest.repository_map["repo-b"].path).resolve())

    from rcp.storage import AppStore

    assert AppStore(store.path).codex_continuation(session_id) == initial
    path.write_text(path.read_text().replace("Earlier answer", "Changed answer"), encoding="utf-8")
    with pytest.raises(ValueError, match="source prefix changed"):
        reprove_codex_history(manifest, store.provider_history(project_id, "codex", session_id))


def test_codex_continuation_route_pins_exact_import_and_reuses_claim(
    manifest, tmp_path, monkeypatch
):
    session_id = str(uuid.uuid4())
    path = _session_file(manifest, session_id)
    app = create_named_app(str(manifest.path), data_dir=tmp_path / "data")
    project_id = app.state.default_project_id
    service = app.state.service
    surfaces = ("seed", "refresh", "node_chat", "project_chat", "paper_coach")
    profiles = {surface: service.manifest.agent_profile(surface) for surface in surfaces}
    profiles["project_chat"] = profiles["project_chat"].model_copy(
        update={"runtime": "herdr-native"}
    )
    service.history.update_agent_settings(service.manifest.agent.default_run_truth_scope, profiles)
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_start(_project_id, _kind, body, _request, **kwargs):
        calls.append((kwargs["operation_id_override"], body))
        return {"operation_id": kwargs["operation_id_override"]}

    monkeypatch.setattr("rcp.api.provider_history._start_agent_task", fake_start)
    monkeypatch.setattr(
        "rcp.agents.herdr_bridge.require_codex_session_quiescent",
        lambda *_args: None,
        raising=False,
    )
    base = f"/api/projects/{project_id}/provider-history/codex/{session_id}"
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/projects/{project_id}/provider-history/codex",
                json={"session_id": session_id},
            ).status_code
            == 200
        )
        unclaimed = client.post(
            f"/api/projects/{project_id}/tasks/project_chat",
            json={
                "chat_id": str(uuid.uuid4()),
                "session_id": session_id,
                "message": "Skip the continuation handoff",
                "mode": "work",
                "run_truth_scope": ["repo-b"],
            },
        )
        assert unclaimed.status_code == 409, unclaimed.text
        assert "explicit continuation admission" in unclaimed.text
        first = client.post(f"{base}/continue", json={"message": "Do this", "mode": "work"})
        assert first.status_code == 202, first.text
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "response_item",
                        "timestamp": "2026-09-29T00:00:04Z",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Later message"}],
                        },
                    }
                )
                + "\n"
            )
        assert (
            client.post(
                f"/api/projects/{project_id}/provider-history/codex",
                json={"session_id": session_id},
            ).status_code
            == 200
        )
        retry = client.post(f"{base}/continue", json={"message": "Do this", "mode": "work"})
        assert retry.status_code == 202, retry.text
        assert retry.json() == first.json()
        assert [call[0] for call in calls] == [first.json()["task"]["operation_id"]] * 2
        assert all(call[1]["run_truth_scope"] == ["repo-b"] for call in calls)
        ordinary = client.post(
            f"/api/projects/{project_id}/tasks/project_chat",
            json={
                "chat_id": first.json()["chat_id"],
                "session_id": session_id,
                "message": "Race the first turn",
                "mode": "work",
                "run_truth_scope": ["repo-b"],
            },
        )
        assert ordinary.status_code == 409, ordinary.text
        assert "first RCP turn" in ordinary.text
        different = client.post(f"{base}/continue", json={"message": "Different", "mode": "work"})
        assert different.status_code == 409


def test_codex_continuation_refuses_live_external_pane(manifest, tmp_path, monkeypatch):
    session_id = str(uuid.uuid4())
    _session_file(manifest, session_id)
    app = create_named_app(str(manifest.path), data_dir=tmp_path / "data")
    project_id = app.state.default_project_id
    service = app.state.service
    surfaces = ("seed", "refresh", "node_chat", "project_chat", "paper_coach")
    profiles = {surface: service.manifest.agent_profile(surface) for surface in surfaces}
    profiles["project_chat"] = profiles["project_chat"].model_copy(
        update={"runtime": "herdr-native"}
    )
    service.history.update_agent_settings(service.manifest.agent.default_run_truth_scope, profiles)

    def active_pane(*_args):
        raise ValueError("Codex session is active in Herdr pane wP:p42")

    monkeypatch.setattr(
        "rcp.agents.herdr_bridge.require_codex_session_quiescent",
        active_pane,
    )
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/projects/{project_id}/provider-history/codex",
                json={"session_id": session_id},
            ).status_code
            == 200
        )
        response = client.post(
            f"/api/projects/{project_id}/provider-history/codex/{session_id}/continue",
            json={"message": "Continue this", "mode": "work"},
        )
        assert response.status_code == 409
        assert "wP:p42" in response.text
        assert app.state.background_tasks.store.codex_continuation(session_id) is None
