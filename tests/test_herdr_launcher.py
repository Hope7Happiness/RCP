from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from rcp.agents.herdr_bridge import (
    HerdrAgentObservation,
    HerdrNativeAgent,
    HerdrProcessIdentity,
)
from rcp.agents.launcher import AgentLauncher, ProviderReadiness
from rcp.background import BackgroundAgentTasks
from tests.test_agent_task_lifecycle import _prepare_task


@pytest.mark.asyncio
async def test_native_herdr_turn_uses_provider_completion_not_ui_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = str(uuid.uuid4())
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text("")
    observed: list[str] = []

    class FakeHerdr:
        def __init__(self) -> None:
            self.prompted = False

        async def session_active(self, *_args, **_kwargs):
            return False

        async def start(self, **_kwargs):
            observed.append("start")
            return HerdrNativeAgent("w1:p9", "claude", "rcpworker")

        async def get(self, agent):
            return HerdrAgentObservation(
                agent.pane_id,
                "claude",
                agent.name,
                "working" if self.prompted else "idle",
                1,
                1,
                session_id,
            )

        async def process_info(self, agent):
            return HerdrProcessIdentity(agent.pane_id, 1234, 1234)

        async def prompt(self, _agent, prompt):
            self.prompted = True
            observed.append("prompt")
            with transcript.open("a") as stream:
                for record in (
                    {"type": "user", "message": {"content": prompt}},
                    {
                        "type": "assistant",
                        "message": {
                            "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": "Verified answer"}],
                        },
                    },
                    {"type": "system", "subtype": "turn_duration"},
                ):
                    stream.write(json.dumps(record) + "\n")

        async def close(self, _agent):
            observed.append("close")

    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setattr("rcp.agents.launcher._native_binary_matches", lambda *_args: True)
    monkeypatch.setattr("rcp.agents.herdr_bridge.HerdrNativeAdapter", FakeHerdr)
    monkeypatch.setattr(
        "rcp.agents.herdr_receipts.find_native_transcript",
        lambda *_args, **_kwargs: transcript,
    )
    launcher = AgentLauncher()
    binary = shutil.which("claude")
    assert binary is not None
    monkeypatch.setattr(
        launcher,
        "readiness",
        lambda *_args, **_kwargs: ProviderReadiness(
            provider="claude",
            installed=True,
            authenticated=True,
            binary_path=binary,
            version="2.1.284",
        ),
    )
    events = [
        event
        async for event in launcher.stream(
            "claude",
            "Do a bounded task.",
            cwd=tmp_path,
            capability="discuss",
            runtime_id="herdr-native",
            session_id=session_id,
        )
    ]
    assert observed == ["start", "prompt", "close"]
    assert [event.event for event in events] == [
        "herdr_binding_start",
        "session",
        "runtime",
        "herdr_binding_stop",
        "provider_exit",
        "answer",
        "done",
    ]
    assert events[-2].text == "Verified answer"


def test_herdr_binding_survives_receipt_retention_and_stops_once(tmp_path: Path) -> None:
    store, operation_id = _prepare_task(tmp_path, "running")
    binding = {
        "pane_id": "w1:p9",
        "agent_name": "rcpworker",
        "provider": "codex",
        "native_session_id": str(uuid.uuid4()),
        "process_group_id": 1234,
        "runtime_id": "codex.herdr-native.v1",
        "stage_root": str(tmp_path / "stage"),
    }
    store.begin_herdr_binding(operation_id, binding)
    for index in range(80):
        store.record_agent_task_receipt(operation_id, "trace", {"index": index})
    assert store.unresolved_herdr_bindings(binding["stage_root"]) == [(operation_id, binding)]
    with pytest.raises(ValueError, match="previous Herdr agent"):
        store.begin_herdr_binding(operation_id, {**binding, "pane_id": "w1:p10"})
    store.finish_herdr_binding(operation_id, binding)
    store.finish_herdr_binding(operation_id, binding)
    assert store.unresolved_herdr_bindings(binding["stage_root"]) == []


def test_startup_closes_only_matching_durable_herdr_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, operation_id = _prepare_task(tmp_path, "running")
    binding = {
        "pane_id": "w1:p9",
        "agent_name": "rcpworker",
        "provider": "claude",
        "native_session_id": str(uuid.uuid4()),
        "process_group_id": 1234,
        "runtime_id": "claude.herdr-native.v1",
        "stage_root": str(tmp_path / "stage"),
    }
    store.begin_herdr_binding(operation_id, binding)
    closed: list[str] = []

    class FakeHerdr:
        async def get(self, agent):
            return HerdrAgentObservation(agent.pane_id, "claude", agent.name, "idle", 1, 1, None)

        async def process_info(self, agent):
            return HerdrProcessIdentity(agent.pane_id, 1234, 1234)

        async def close(self, agent):
            closed.append(agent.pane_id)

    monkeypatch.setattr("rcp.agents.herdr_bridge.HerdrNativeAdapter", FakeHerdr)
    manager = BackgroundAgentTasks.__new__(BackgroundAgentTasks)
    manager.store = store
    manager._reconcile_herdr_bindings()
    assert closed == ["w1:p9"]
    assert store.unresolved_herdr_bindings() == []
