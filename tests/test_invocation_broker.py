from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import pytest

from rcp.agents.invocation_broker import ProviderInvocationGate


class _Stdin:
    def __init__(self) -> None:
        self.closed = False
        self.wait_closed_calls = 0

    def write(self, _value: bytes) -> None:
        return None

    async def drain(self) -> None:
        raise BrokenPipeError("broker exited before bootstrap")

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_calls += 1


class _Stdout:
    async def readline(self) -> bytes:
        raise AssertionError("readiness must not be read after bootstrap failure")


class _Process:
    def __init__(self, *, first_wait_times_out: bool = False, kill_races: bool = False) -> None:
        self.stdin = _Stdin()
        self.stdout = _Stdout()
        self.stderr = None
        self.first_wait_times_out = first_wait_times_out
        self.kill_races = kill_races
        self.wait_calls = 0
        self.kill_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.first_wait_times_out and self.wait_calls == 1:
            raise TimeoutError
        return 0

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_races:
            raise ProcessLookupError


def _gate(tmp_path: Path) -> ProviderInvocationGate:
    return ProviderInvocationGate(
        mailbox_id="mailbox",
        broker_path="/tmp/broker.py",
        socket_path="/tmp/broker.sock",
        workspace=str(tmp_path),
        response_timeout_seconds=5.0,
        _token="secret",
    )


@pytest.mark.asyncio
async def test_broker_bootstrap_failure_still_reaps_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    process = _Process()

    async def create_process(*_args: object, **_kwargs: object) -> _Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(BrokenPipeError):
        async with _gate(tmp_path).serve_current_session():
            raise AssertionError("broker session should not become ready")

    assert process.stdin.closed is True
    assert process.stdin.wait_closed_calls == 1
    assert process.wait_calls == 1
    assert process.kill_calls == 0


@pytest.mark.asyncio
async def test_broker_exit_race_does_not_replace_bootstrap_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    process = _Process(first_wait_times_out=True, kill_races=True)

    async def create_process(*_args: object, **_kwargs: object) -> _Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(BrokenPipeError):
        async with _gate(tmp_path).serve_current_session():
            raise AssertionError("broker session should not become ready")

    assert process.stdin.closed is True
    assert process.stdin.wait_closed_calls == 1
    assert process.wait_calls == 2
    assert process.kill_calls == 1


@pytest.mark.asyncio
async def test_external_provider_broker_lives_only_for_bound_process(tmp_path: Path) -> None:
    mailbox_id = secrets.token_hex(16)
    socket_path = f"/tmp/rcp-command-{mailbox_id}.sock"
    broker_path = Path(__file__).resolve().parents[1] / "src/rcp/agents/staged_command_broker.py"
    gate = ProviderInvocationGate(
        mailbox_id=mailbox_id,
        broker_path=str(broker_path),
        socket_path=socket_path,
        workspace=str(tmp_path),
        response_timeout_seconds=2.0,
        _token=secrets.token_hex(32),
    )
    async with gate.serve_external_provider(os.getpid()):
        assert Path(socket_path).is_socket()
    assert not Path(socket_path).exists()
