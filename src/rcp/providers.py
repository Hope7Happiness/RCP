from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

if TYPE_CHECKING:
    from rcp.agents.write_scope import ProjectWriteScope
    from rcp.provider_auth import ProviderAuthentication

"""The provider registry.

Registering an agent CLI means adding one `ProviderProfile` subclass here and
listing it in `PROVIDERS`. Nothing about a provider belongs anywhere else — not
a `("codex", "claude")` tuple, not a display-name ternary, not an option list in
a React component. Two bugs on 2026-07-30 came from provider facts written from
memory into the frontend: a reasoning list that offered a value the models
reject, and a correct control hidden on a false premise about the launch
command.

Where the CLI can enumerate its own models, the profile probes it and RCP offers
exactly what came back. Where it cannot, the profile declares the lists and
records the CLI version they were read from, so the staleness is visible to
whoever maintains them. A profile may do both: Claude Code cannot enumerate its
models, but `claude --help` does document the accepted `--effort` values, so
that list is probed while the model aliases stay declared.
"""


AgentCapability = Literal[
    "discuss",
    "work_auto",
    "orchestrate",
    "scratch_patch",
    "paper_readonly",
]


class ModelChoice(BaseModel):
    """One model a provider accepts, with the reasoning efforts it supports."""

    id: str
    label: str
    reasoning: list[str] = []
    default_reasoning: str = ""


class ProviderRuntimeChoice(BaseModel):
    """One manifest-selectable way to talk to a provider CLI."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class ProviderSkill(BaseModel):
    """One user-invocable skill reported by a provider CLI."""

    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str
    scope: str | None = None
    path: str | None = None
    enabled: bool = True


class ProviderSkillProbe(BaseModel):
    """The exact provider-owned command and wire protocol used for refresh."""

    command: list[str] = Field(min_length=1)
    protocol: Literal["jsonrpc", "jsonl"]
    messages: tuple[dict[str, object], ...] = ()


class ProviderSkillReference(BaseModel):
    """Immutable per-turn receipt for one provider-native skill invocation."""

    provider: str = Field(min_length=1)
    machine: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    inventory_hash: str = Field(min_length=1)
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str
    stale: bool = False


class ProviderUsage(BaseModel):
    """Provider-normalized usage at one accounting boundary.

    `processed_input_tokens` and `generated_tokens` are the shared accounting
    fields. The reported fields and `provider_fields` preserve what the CLI
    actually emitted, because providers do not use identical cache semantics.
    """

    provider_profile: str
    provider_event_type: str
    dedupe_key: str
    processed_input_tokens: int = Field(ge=0)
    generated_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    cache_write_input_tokens: int = Field(default=0, ge=0)
    reasoning_output_tokens: int = Field(default=0, ge=0)
    reported_input_tokens: int | None = Field(default=None, ge=0)
    reported_output_tokens: int | None = Field(default=None, ge=0)
    reported_total_tokens: int | None = Field(default=None, ge=0)
    provider_fields: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class ProviderStreamEvent:
    event: Literal["session", "message", "answer", "error", "raw"]
    text: str = ""
    session_id: str | None = None
    usage: ProviderUsage | None = None


@dataclass(frozen=True)
class ProviderTurnRequest:
    """One provider-owned runtime invocation after RCP has pinned its policy."""

    prompt: str
    binary: str
    cwd: Path
    model: str | None
    reasoning: str | None
    session_id: str | None
    read_dirs: list[Path]
    write_dirs: list[Path]
    write_scope: ProjectWriteScope | None
    capability: AgentCapability
    provider_version: str | None
    legacy_command: list[str] | None = None


@dataclass(frozen=True)
class ProviderSteerReceipt:
    status: Literal["delivered", "refused", "unknown"]
    reason: str | None = None


@dataclass(frozen=True)
class ProviderSteeringState:
    can_steer: bool
    reason: str | None = None
    turn_id: str | None = None


@dataclass(frozen=True)
class ProviderRuntimeStep:
    """One provider protocol input line normalized for the shared launcher."""

    outgoing: tuple[bytes, ...] = ()
    events: tuple[ProviderStreamEvent, ...] = ()
    complete: bool = False
    explicit_terminal: bool = False
    delivers_prompt: bool = False
    steer_receipts: tuple[tuple[str, ProviderSteerReceipt], ...] = ()
    stop_process: bool = False


class ProviderTurn:
    """Stateful wire conversation for one fresh provider subprocess."""

    command: list[str]
    close_input_after_initial: bool = True
    requires_protocol_completion: bool = False
    initial_input_delivers_prompt: bool = True
    last_error: str = ""

    def initial_input(self) -> bytes:
        raise NotImplementedError

    def receive_line(self, line: str) -> ProviderRuntimeStep:
        raise NotImplementedError

    def steering_state(self) -> ProviderSteeringState:
        return ProviderSteeringState(False, "This runtime does not support live steering.")

    def render_steer(self, expected_turn_id: str, message_id: str, text: str) -> bytes:
        raise ValueError(self.steering_state().reason)

    def adopt_recorded_inputs(
        self, message_ids: list[str], steer_requests: dict[str, object]
    ) -> None:
        """Take on the input identities a recorded pass actually sent.

        Replaying a journal builds a fresh turn, which would otherwise mint its
        own ids and then fail to recognise its own recorded traffic. The host
        wrote these down for exactly this: stdin is the live control channel and
        is never persisted, so the identities travel instead of the bytes.

        A runtime that does not key anything off its inputs has nothing to take
        on, which is why this does nothing by default.
        """


class ProviderRuntime:
    """Provider-owned command and wire protocol hidden behind one RCP boundary."""

    id: str
    #: `inject` puts the message into the turn already running and the provider
    #: confirms it. `queue` names RCP's continuation contract, not a placement
    #: promise: the process may run past its first result while accepted
    #: follow-ups are outstanding. Claude decides placement by timing — a
    #: message that lands during a tool call joins the running turn and is
    #: attributed to its result, otherwise it runs as the next turn.
    steering_behavior: Literal["unsupported", "inject", "queue"] = "unsupported"

    @property
    def supports_steering(self) -> bool:
        return self.steering_behavior != "unsupported"

    @property
    def steer_action_label(self) -> str | None:
        if self.steering_behavior == "queue":
            return "Send to the running turn"
        if self.steering_behavior == "inject":
            return "Steer running turn"
        return None

    def turn(self, request: ProviderTurnRequest) -> ProviderTurn:
        raise NotImplementedError


class _HerdrNativeRuntime(ProviderRuntime):
    """Native Herdr placement; the launcher consumes its provider transcript."""

    def __init__(self, runtime_id: str) -> None:
        self.id = runtime_id

    def turn(self, request: ProviderTurnRequest) -> ProviderTurn:
        raise ValueError("Herdr native turns must use the Herdr launch path.")


class _JsonlProviderTurn(ProviderTurn):
    requires_protocol_completion = True

    def __init__(
        self,
        profile: ProviderProfile,
        request: ProviderTurnRequest,
    ) -> None:
        self._profile = profile
        self._prompt = request.prompt
        self.command = request.legacy_command or profile.command(
            request.prompt,
            binary=request.binary,
            cwd=request.cwd,
            model=request.model,
            reasoning=request.reasoning,
            session_id=request.session_id,
            read_dirs=request.read_dirs,
            write_dirs=request.write_dirs,
            write_scope=request.write_scope,
            capability=request.capability,
            provider_version=request.provider_version,
        )

    def initial_input(self) -> bytes:
        return self._prompt.encode("utf-8")

    def steering_state(self) -> ProviderSteeringState:
        return ProviderSteeringState(
            False,
            f"{self._profile.label} {self._profile.default_runtime} does not support live steering.",
        )

    def receive_line(self, line: str) -> ProviderRuntimeStep:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            event = ProviderStreamEvent(event="raw", text=line)
            return ProviderRuntimeStep(events=(event,))
        event = self._profile.decode_event(value, line)
        if isinstance(value, dict) and value.get("type") == "error":
            self.last_error = event.text
        terminal = event.event == "error" or (
            isinstance(value, dict)
            and value.get("type") in {"turn.completed", "turn.failed", "result"}
        )
        return ProviderRuntimeStep(events=(event,), complete=terminal, explicit_terminal=terminal)


class _ClaudeStreamTurn(_JsonlProviderTurn):
    close_input_after_initial = False
    requires_protocol_completion = True

    def __init__(self, profile: ProviderProfile, request: ProviderTurnRequest) -> None:
        super().__init__(profile, request)
        self.command.extend(["--input-format", "stream-json", "--replay-user-messages"])
        # Claude has no native per-turn precondition. This token identifies only
        # this fresh process's initial input, never a resumable provider session.
        self._turn_id = str(uuid.uuid4())
        self._ready = False
        self._completed = False
        self._pending: set[str] = set()
        self._generated: set[str] = {self._turn_id}
        self._outstanding: set[str] = set()

    @staticmethod
    def _user_input(message_id: str, text: str) -> bytes:
        return (
            json.dumps(
                {
                    "type": "user",
                    "uuid": message_id,
                    "message": {"role": "user", "content": text},
                    "parent_tool_use_id": None,
                    "session_id": "",
                },
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    def initial_input(self) -> bytes:
        return self._user_input(self._turn_id, self._prompt)

    def adopt_recorded_inputs(
        self, message_ids: list[str], steer_requests: dict[str, object]
    ) -> None:
        if not message_ids:
            return
        # The first is the prompt; the rest are steers this turn accepted. A
        # result naming any of them belongs to this turn, and a fresh id would
        # have let the first result end a turn that was still answering.
        self._turn_id = message_ids[0]
        self._generated = set(message_ids)

    def steering_state(self) -> ProviderSteeringState:
        if self._completed:
            return ProviderSteeringState(False, "The provider turn has completed.")
        if not self._ready:
            return ProviderSteeringState(
                False, "Waiting for the provider to acknowledge this turn."
            )
        return ProviderSteeringState(True, turn_id=self._turn_id)

    def render_steer(self, expected_turn_id: str, message_id: str, text: str) -> bytes:
        state = self.steering_state()
        if not state.can_steer:
            raise ValueError(state.reason)
        if expected_turn_id != self._turn_id:
            raise ValueError("The addressed provider turn is no longer active.")
        if message_id in self._generated:
            raise ValueError("This message was already sent to the provider.")
        self._pending.add(message_id)
        self._generated.add(message_id)
        return self._user_input(message_id, text)

    def receive_line(self, line: str) -> ProviderRuntimeStep:
        if self._completed:
            return ProviderRuntimeStep()
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return super().receive_line(line)
        if isinstance(value, dict):
            if value.get("type") == "command_lifecycle":
                message_id = value.get("command_uuid")
                if not isinstance(message_id, str) or message_id not in self._generated:
                    return ProviderRuntimeStep()
                state = value.get("state")
                if state in {"queued", "started"}:
                    self._outstanding.add(message_id)
                elif state == "completed":
                    self._outstanding.discard(message_id)
                if state == "started" and message_id == self._turn_id:
                    self._ready = True
                if state == "queued" and message_id in self._pending:
                    self._pending.remove(message_id)
                    return ProviderRuntimeStep(
                        steer_receipts=((message_id, ProviderSteerReceipt("delivered")),)
                    )
                return ProviderRuntimeStep()
            if value.get("type") == "user" and value.get("isReplay") is True:
                return ProviderRuntimeStep()
            if value.get("type") == "result":
                from rcp.agents.turn_completion import attributed_ids, is_claude_task_notice

                finished = attributed_ids(value)
                self._outstanding.difference_update(finished)
                event = self._profile.decode_event(value, line)
                if is_claude_task_notice(value, self._generated, finished):
                    return ProviderRuntimeStep(
                        events=(ProviderStreamEvent(event="raw", text=line, usage=event.usage),)
                    )
                # A failing result ends the invocation even with a follow-up
                # accepted: the task engine stops at the first error anyway, so
                # continuing would only run a turn whose task has already
                # failed. Ending here keeps the error path terminal, which is
                # what the launcher's stderr drain and stop assume.
                if finished and self._outstanding and event.event != "error":
                    return ProviderRuntimeStep(events=(event,))
                self._completed = True
                receipts = tuple(
                    (message_id, ProviderSteerReceipt("refused", "Turn completed before delivery."))
                    for message_id in self._pending
                )
                self._pending.clear()
                return ProviderRuntimeStep(
                    events=(event,),
                    complete=True,
                    explicit_terminal=True,
                    stop_process=True,
                    steer_receipts=receipts,
                )
        return super().receive_line(line)


class _ClaudeStreamRuntime(ProviderRuntime):
    id = "claude.stream-json.v1"
    steering_behavior = "queue"

    def turn(self, request: ProviderTurnRequest) -> ProviderTurn:
        return _ClaudeStreamTurn(ClaudeProfile(), request)


class _JsonlProviderRuntime(ProviderRuntime):
    def __init__(self, runtime_id: str, profile: ProviderProfile) -> None:
        self.id = runtime_id
        self._profile = profile

    def turn(self, request: ProviderTurnRequest) -> ProviderTurn:
        return _JsonlProviderTurn(self._profile, request)


class ProviderProfile:
    """Everything RCP knows about one agent CLI."""

    @property
    def authentication(self) -> ProviderAuthentication:
        from rcp.provider_auth import ProviderAuthentication

        return ProviderAuthentication()

    id: str
    label: str
    #: The CLI version `declared` was last verified against. Empty when the
    #: profile probes the CLI instead of declaring, which cannot go stale.
    declared_against: str = ""
    #: Models known without asking the CLI. Ignored when `catalog_command`
    #: returns a command that answers.
    declared: tuple[ModelChoice, ...] = ()
    local_session_roots_field: str
    remote_session_roots_field: str
    usage_profile: str = "unknown.v1"
    legacy_runtime_id: str
    default_runtime: str
    runtime_aliases: dict[str, str]
    runtime_choices: tuple[ProviderRuntimeChoice, ...]
    work_like_minimum_version: tuple[int, int, int] | None = None

    def session_roots(self, sources: object, *, remote: bool) -> list[str]:
        """Return this provider's configured native-session roots.

        Keeping the mapping here makes native handoff discovery follow the same
        registry boundary as launch and stream decoding. Adding a provider does
        not require another provider-name branch in the retry assembler.
        """
        field = self.remote_session_roots_field if remote else self.local_session_roots_field
        roots = getattr(sources, field, None)
        if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
            raise ValueError(f"Provider {self.id!r} has no configured session roots")
        return roots

    def auth_command(self, binary: str) -> list[str]:
        """The argv that reports whether this CLI is logged in."""
        raise NotImplementedError

    def login_command(self, binary: str) -> list[str]:
        """The provider-native interactive command an operator runs directly."""
        raise NotImplementedError

    def validate_readiness_version(
        self,
        actual: str | None,
        *,
        capability: AgentCapability,
    ) -> None:
        """Apply the same version floor used by a real launch of this capability."""

        if capability in {"work_auto", "orchestrate"}:
            minimum = self.work_like_minimum_version
            if minimum is not None:
                _require_provider_version(
                    provider=self.label,
                    actual=actual,
                    minimum=minimum,
                )

    def login_probe_command(self, binary: str) -> list[str] | None:
        """One real authenticated request; status output is not proof of sign-in."""
        return None

    def work_like_probe_command(self, binary: str) -> list[str] | None:
        """Zero-model-call startup check; the caller must supply empty stdin."""
        return None

    def is_authenticated(self, result: subprocess.CompletedProcess[str]) -> bool:
        """Whether the CLI reports a stored credential.

        This is a presence check, not a liveness check. Every provider status
        command reads its own credential file and names the auth mode without
        contacting the provider, so a spent refresh token still reports success
        and only a real turn discovers the 401. A truthful result here means the
        launch is worth attempting, never that it will authenticate.
        """

        raise NotImplementedError

    def catalog_command(self, binary: str) -> list[str] | None:
        """The argv that enumerates models, or None when the CLI cannot."""
        return None

    def parse_catalog(self, stdout: str) -> list[ModelChoice]:
        return []

    def skill_probe(self, binary: str) -> ProviderSkillProbe:
        """Return the zero-turn command that enumerates this CLI's loaded skills."""

        raise NotImplementedError

    def parse_skills(self, payload: object) -> list[ProviderSkill]:
        """Normalize one successful provider-owned inventory response."""

        raise NotImplementedError

    def native_skill_token(self, name: str) -> str:
        """Provider-native spelling retained in the structured turn marker."""

        return f"/{name}"

    def models(self, catalog: subprocess.CompletedProcess[str] | None) -> list[ModelChoice]:
        """The models to offer, preferring a live catalog over declared ones."""
        if catalog is not None and catalog.returncode == 0:
            try:
                probed = self.parse_catalog(catalog.stdout)
            except (ValueError, KeyError, TypeError):
                probed = []
            if probed:
                return probed
        return list(self.declared)

    def runtime(self, runtime_id: str) -> ProviderRuntime:
        if runtime_id == self.legacy_runtime_id:
            return _JsonlProviderRuntime(runtime_id, self)
        raise ValueError(f"Provider {self.id!r} does not support runtime {runtime_id!r}.")

    def configured_runtime(self, configured: str | None) -> str:
        """Normalize a manifest value to its provider-owned public name."""

        value = (configured or "").strip()
        if not value:
            return self.default_runtime
        runtime_id = self.runtime_aliases.get(value, value)
        self.runtime(runtime_id)
        for choice in self.runtime_choices:
            if self.runtime_aliases[choice.id] == runtime_id:
                return choice.id
        raise ValueError(f"Provider {self.id!r} runtime {value!r} is not manifest-selectable.")

    def configured_runtime_id(self, configured: str | None) -> str:
        public_name = self.configured_runtime(configured)
        return self.runtime_aliases[public_name]

    def runtime_label(self, runtime_id: str) -> str:
        """Name a durable runtime id for a surface reporting what actually ran."""

        for choice in self.runtime_choices:
            if self.runtime_aliases[choice.id] == runtime_id:
                return choice.label
        # A record can name a runtime this build no longer offers. The stored id
        # is then the only honest answer.
        return runtime_id

    def runtime_candidates(self, configured: str | None) -> tuple[ProviderRuntime, ...]:
        """Preferred runtime followed by its safe pre-prompt fallback, if any."""

        preferred = self.runtime(self.configured_runtime_id(configured))
        if preferred.id == self.legacy_runtime_id or isinstance(preferred, _HerdrNativeRuntime):
            return (preferred,)
        return (preferred, self.runtime(self.legacy_runtime_id))

    def command(
        self,
        prompt: str,
        *,
        binary: str,
        cwd: Path,
        model: str | None,
        reasoning: str | None,
        session_id: str | None,
        read_dirs: list[Path],
        write_dirs: list[Path],
        write_scope: ProjectWriteScope | None,
        capability: AgentCapability,
        provider_version: str | None,
    ) -> list[str]:
        """The argv that runs one turn. `prompt` arrives on stdin."""
        raise NotImplementedError

    def project_write_enforcement_mode(self) -> str:
        raise ValueError(f"Provider {self.id!r} has no project write enforcement mode")

    def launch_degradation(self, stderr: str, *, requested_reasoning: str | None) -> str | None:
        """One RCP-authored sentence when the CLI ignored part of a launch.

        A provider that rejects an unusable launch outright has nothing to add
        here; that failure already reaches the human on the error path. This is
        for a CLI that accepts the launch, silently drops part of it, and then
        succeeds anyway. The sentence is composed from what RCP asked for, never
        from the provider's own diagnostic text, which is unbounded and unowned.
        """

        del stderr, requested_reasoning
        return None

    def probe_failure_evidence(self, result: subprocess.CompletedProcess[str]) -> str:
        """Diagnostics to classify; successful output is provider data, not failure evidence."""

        return result.stderr + (result.stdout if result.returncode else "")

    def credential_failure(self, stderr: str) -> bool:
        """Whether this CLI's diagnostic says its own login is no longer valid.

        A revoked or expired login fails every attempt the same way, so RCP has
        to tell it apart from a dropped connection: one is worth retrying and
        the other is not. The provider owns these signatures because only it
        knows what its CLI prints. A profile that has not had a real revoked
        login observed returns False rather than guessing, because a wrong
        match here would withdraw Retry from a failure Retry would have fixed.
        """

        del stderr
        return False

    def decode_event(self, value: object, raw: str) -> ProviderStreamEvent:
        return ProviderStreamEvent(event="raw", text=raw)

    def decode_usage(self, value: dict[str, object], raw: str) -> ProviderUsage | None:
        return None


class CodexProfile(ProviderProfile):
    @property
    def authentication(self) -> ProviderAuthentication:
        from rcp.provider_auth import CodexAuthentication

        return CodexAuthentication()

    id = "codex"
    label = "Codex"
    usage_profile = "codex.turn.v1"
    local_session_roots_field = "codex_roots"
    remote_session_roots_field = "remote_codex_roots"
    legacy_runtime_id = "codex.exec-json.v1"
    default_runtime = "exec"
    runtime_aliases = {
        "exec": legacy_runtime_id,
        "exec-json": legacy_runtime_id,
        "app-server": "codex.app-server-stdio.v1",
        "herdr-native": "codex.herdr-native.v1",
        legacy_runtime_id: legacy_runtime_id,
        "codex.app-server-stdio.v1": "codex.app-server-stdio.v1",
        "codex.herdr-native.v1": "codex.herdr-native.v1",
    }
    runtime_choices = (
        ProviderRuntimeChoice(id="exec", label="Codex exec"),
        ProviderRuntimeChoice(id="app-server", label="Codex app server"),
        ProviderRuntimeChoice(id="herdr-native", label="Codex in Herdr (local preview)"),
    )
    work_like_minimum_version = (0, 138, 0)

    def runtime(self, runtime_id: str) -> ProviderRuntime:
        if runtime_id == self.legacy_runtime_id:
            return super().runtime(runtime_id)
        if runtime_id == "codex.app-server-stdio.v1":
            # The protocol adapter imports these shared runtime contracts, so
            # load it only after this module and the provider registry exist.
            from rcp.agents.codex_app_server import CodexAppServerRuntime

            return CodexAppServerRuntime()
        if runtime_id == "codex.herdr-native.v1":
            return _HerdrNativeRuntime(runtime_id)
        return super().runtime(runtime_id)

    def auth_command(self, binary: str) -> list[str]:
        return [binary, "login", "status"]

    def login_command(self, binary: str) -> list[str]:
        return [binary, "login"]

    def is_authenticated(self, result: subprocess.CompletedProcess[str]) -> bool:
        if result.returncode != 0:
            return False
        # "Not logged in" contains "logged in", so the negative has to be ruled
        # out first. Today a logged-out `codex login status` also exits non-zero,
        # which hid this; that is the CLI's choice to change, not ours to rely on.
        reported = (result.stdout + result.stderr).lower()
        return "not logged in" not in reported and "logged in" in reported

    def probe_failure_evidence(self, result: subprocess.CompletedProcess[str]) -> str:
        diagnostics = [result.stderr]
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if result.returncode:
                    diagnostics.append(line)
                continue
            if isinstance(value, dict) and (
                "error" in value
                or value.get("method") == "error"
                or value.get("type") == "error"
                or self.decode_event(value, line).event == "error"
            ):
                diagnostics.append(line)
        return "\n".join(diagnostics)

    def credential_failure(self, stderr: str) -> bool:
        # Observed from a real run on 2026-09-12: `codex login status` still
        # reported a healthy login while every turn died on these. The run's
        # own diagnostic is the only trustworthy signal. On the same date a shared
        # login died between turns with refresh_token_reused / already-used text.
        reported = stderr.lower()
        return any(
            signature in reported
            for signature in (
                "refresh_token_reused",
                "refresh token was already used",
                "token_revoked",
                "refresh_token_invalidated",
                "refresh token was revoked",
                "your session has ended. please log in again",
            )
        )

    def login_probe_command(self, binary: str) -> list[str]:
        # Flags probed with codex-cli 0.154.0 on 2026-09-14.
        return [
            binary,
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            "gpt-5.6-luna",
            "Reply with OK only. Do not use tools.",
        ]

    def catalog_command(self, binary: str) -> list[str] | None:
        return [binary, "debug", "models"]

    def parse_catalog(self, stdout: str) -> list[ModelChoice]:
        payload = json.loads(stdout)
        if not isinstance(payload, dict):
            return []
        entries = payload.get("models")
        if not isinstance(entries, list):
            return []
        choices: list[ModelChoice] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # `hide` marks catalog rows Codex itself does not offer a human --
            # internal review models and the like.
            if entry.get("visibility") != "list":
                continue
            slug = entry.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            levels = [
                level["effort"]
                for level in entry.get("supported_reasoning_levels") or []
                if isinstance(level, dict) and isinstance(level.get("effort"), str)
            ]
            choices.append(
                ModelChoice(
                    id=slug,
                    label=entry.get("display_name") or slug,
                    reasoning=levels,
                    default_reasoning=entry.get("default_reasoning_level") or "",
                )
            )
        # Codex orders its own catalog by `priority`; preserve that rather than
        # imposing an alphabetical order the human has not seen anywhere else.
        return choices

    def skill_probe(self, binary: str) -> ProviderSkillProbe:
        return ProviderSkillProbe(
            command=[binary, "app-server"],
            protocol="jsonrpc",
            messages=(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "rcp", "version": "1"},
                        "capabilities": {},
                    },
                },
                {"jsonrpc": "2.0", "method": "initialized", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "skills/list",
                    "params": {"cwds": ["/"], "forceReload": True},
                },
            ),
        )

    def parse_skills(self, payload: object) -> list[ProviderSkill]:
        if not isinstance(payload, dict):
            raise ValueError("Codex skills/list result is not an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Codex skills/list result has no data list")
        normalized: dict[str, ProviderSkill] = {}
        for scope in data:
            if not isinstance(scope, dict) or not isinstance(scope.get("skills"), list):
                continue
            for item in scope["skills"]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name or item.get("enabled") is not True:
                    continue
                interface = item.get("interface")
                display_name = interface.get("displayName") if isinstance(interface, dict) else None
                description = item.get("description")
                normalized[name] = ProviderSkill(
                    name=name,
                    label=display_name if isinstance(display_name, str) and display_name else name,
                    description=description if isinstance(description, str) else "",
                    scope=item.get("scope") if isinstance(item.get("scope"), str) else None,
                    path=item.get("path") if isinstance(item.get("path"), str) else None,
                )
        return list(normalized.values())

    def native_skill_token(self, name: str) -> str:
        return f"${name}"

    def project_write_enforcement_mode(self) -> str:
        return "codex.permission-profile.v1"

    def command(
        self,
        prompt: str,
        *,
        binary: str,
        cwd: Path,
        model: str | None,
        reasoning: str | None,
        session_id: str | None,
        read_dirs: list[Path],
        write_dirs: list[Path],
        write_scope: ProjectWriteScope | None,
        capability: AgentCapability,
        provider_version: str | None,
    ) -> list[str]:
        del prompt, read_dirs
        command = [binary, "exec"]
        if session_id:
            # `codex exec resume` has no --sandbox or --cd; it takes the process
            # working directory and, left alone, codex's own default sandbox --
            # which is read-only. A resumed run must be able to write its patch
            # file, so the mode is set through --config.
            command.append("resume")
        command.extend(
            ["--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"]
        )
        # Live retrieval is a provider tool, independent of whether command
        # execution is read-only or has workspace-write network access.
        command.extend(["--config", 'web_search="live"'])
        if capability in {"work_auto", "orchestrate"}:
            scope = _require_project_write_scope(
                write_scope,
                capability=capability,
                write_dirs=write_dirs,
            )
            self.validate_readiness_version(provider_version, capability=capability)
            command.extend(
                [
                    "--config",
                    'default_permissions="rcp_project"',
                    "--config",
                    _codex_permission_profile(scope),
                ]
            )
        else:
            if write_scope is not None:
                raise ValueError(f"capability {capability!r} cannot carry a project write scope")
            command.extend(["--config", 'approval_policy="never"'])
            sandbox = "read-only" if capability == "paper_readonly" else "workspace-write"
            if session_id:
                command.extend(["--config", f'sandbox_mode="{sandbox}"'])
            else:
                command.extend(["--sandbox", sandbox])
            if capability != "paper_readonly":
                command.extend(["--config", "sandbox_workspace_write.network_access=true"])
        if not session_id:
            command.extend(["--cd", str(cwd)])
        if model:
            command.extend(["--model", model])
        if reasoning:
            command.extend(["--config", f'model_reasoning_effort="{reasoning}"'])
        if session_id:
            command.append(session_id)
        command.append("-")
        return command

    def decode_event(self, value: object, raw: str) -> ProviderStreamEvent:
        if not isinstance(value, dict):
            return ProviderStreamEvent(event="raw", text=raw)
        event_type = value.get("type", "")
        usage = self.decode_usage(value, raw)
        if event_type in {"thread.started", "session.started"}:
            return ProviderStreamEvent(
                event="session",
                session_id=value.get("thread_id") or value.get("session_id"),
                usage=usage,
            )
        if event_type in {"turn.failed", "error"}:
            error = value.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or json.dumps(error, ensure_ascii=False)
            else:
                detail = error or value.get("message") or "Codex turn failed."
            return ProviderStreamEvent(
                event="error" if event_type == "turn.failed" else "message",
                text=str(detail),
                usage=usage,
            )
        item = value.get("item", {})
        if not isinstance(item, dict):
            item = {}
        text = item.get("text") or value.get("message") or ""
        if text:
            if item.get("type") == "agent_message" and event_type != "item.started":
                return ProviderStreamEvent(event="answer", text=str(text), usage=usage)
            return ProviderStreamEvent(event="message", text=str(text), usage=usage)
        return ProviderStreamEvent(event="raw", text=raw, usage=usage)

    def decode_usage(self, value: dict[str, object], raw: str) -> ProviderUsage | None:
        event_type = value.get("type")
        if event_type not in {"turn.completed", "turn.failed"}:
            return None
        usage = value.get("usage")
        if not isinstance(usage, dict):
            return None
        input_tokens = _usage_int(usage.get("input_tokens"))
        output_tokens = _usage_int(usage.get("output_tokens"))
        cached_input_tokens = _usage_int(usage.get("cached_input_tokens"))
        cache_write_input_tokens = _usage_int(usage.get("cache_write_input_tokens"))
        reasoning_output_tokens = _usage_int(usage.get("reasoning_output_tokens"))
        return ProviderUsage(
            provider_profile=self.usage_profile,
            provider_event_type=str(event_type),
            dedupe_key=_usage_dedupe_key(value, raw, "turn_id", "id", "event_id"),
            processed_input_tokens=input_tokens,
            generated_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            reported_input_tokens=input_tokens,
            reported_output_tokens=output_tokens,
            reported_total_tokens=_optional_usage_int(usage.get("total_tokens")),
            provider_fields={str(key): item for key, item in usage.items()},
        )


# Claude Code has no `codex debug models` equivalent. The efforts here are the
# fallback for when the `--help` probe below cannot be read; the aliases are the
# real hand-maintained list, because `--help` documents them only by example.
# Re-read the aliases when bumping the CLI and move `ClaudeProfile.declared_against`
# to the version you read them from.
_CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
# The values follow `--effort` in its own description. Refusing to cross a `--`
# keeps a later option's parenthetical from being read as this option's values.
_CLAUDE_EFFORT_HELP = re.compile(r"--effort <[^>]+>(?:(?!--)[^(])*\(([^)]*)\)")
_CLAUDE_EFFORT_VALUE = re.compile(r"[a-z][a-z0-9_-]*")
_CLAUDE_MODELS = tuple(
    ModelChoice(id=slug, label=label, reasoning=_CLAUDE_EFFORTS, default_reasoning="medium")
    for slug, label in (
        ("opus", "Opus"),
        ("sonnet", "Sonnet"),
        ("haiku", "Haiku"),
        ("fable", "Fable"),
    )
)


class ClaudeProfile(ProviderProfile):
    @property
    def authentication(self) -> ProviderAuthentication:
        from rcp.provider_auth import ClaudeAuthentication

        return ClaudeAuthentication()

    # No credential failure signatures have been observed for Claude.
    id = "claude"
    label = "Claude"
    usage_profile = "claude.query.v1"
    local_session_roots_field = "claude_roots"
    remote_session_roots_field = "remote_claude_roots"
    legacy_runtime_id = "claude.stream-json.v1"
    default_runtime = "stream-json"
    runtime_aliases = {
        "stream-json": legacy_runtime_id,
        "herdr-native": "claude.herdr-native.v1",
        legacy_runtime_id: legacy_runtime_id,
        "claude.herdr-native.v1": "claude.herdr-native.v1",
    }
    runtime_choices = (
        ProviderRuntimeChoice(id="stream-json", label="Claude stream JSON"),
        ProviderRuntimeChoice(id="herdr-native", label="Claude in Herdr (local preview)"),
    )
    work_like_minimum_version = (2, 1, 233)
    #: Only the model aliases are declared; `declared_against` dates them alone.
    declared_against = "2.1.267"
    declared = _CLAUDE_MODELS

    def probe_failure_evidence(self, result: subprocess.CompletedProcess[str]) -> str:
        diagnostics = [result.stderr]
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if result.returncode:
                    diagnostics.append(line)
                continue
            if self.decode_event(value, line).event == "error":
                diagnostics.append(line)
        return "\n".join(diagnostics)

    def credential_failure(self, stderr: str) -> bool:
        # Emitted by this provider's remote environment fence when its managed
        # token disappeared.
        if "RCP managed credential is missing" in stderr:
            return True
        # Observed from Claude Code 2.1.270 on 2026-09-15, verifying a setup
        # token the service rejected: "Failed to authenticate. API Error: 401
        # OAuth access token is invalid." The status code carries the meaning,
        # so the sentence around it may be reworded without breaking this.
        reported = " ".join(stderr.casefold().split())
        return "401" in reported and ("authenticate" in reported or "oauth" in reported)

    def runtime(self, runtime_id: str) -> ProviderRuntime:
        if runtime_id == "claude.herdr-native.v1":
            return _HerdrNativeRuntime(runtime_id)
        if runtime_id == self.legacy_runtime_id:
            return _ClaudeStreamRuntime()
        return super().runtime(runtime_id)

    def auth_command(self, binary: str) -> list[str]:
        return [binary, "auth", "status"]

    def login_command(self, binary: str) -> list[str]:
        return [binary, "auth", "login"]

    def is_authenticated(self, result: subprocess.CompletedProcess[str]) -> bool:
        try:
            return bool(json.loads(result.stdout).get("loggedIn"))
        except (json.JSONDecodeError, AttributeError):
            return False

    def catalog_command(self, binary: str) -> list[str] | None:
        # Claude Code cannot enumerate its models, but `--help` states the exact
        # values `--effort` accepts. Probing beats copying them by hand.
        return [binary, "--help"]

    def parse_catalog(self, stdout: str) -> list[ModelChoice]:
        """Read the accepted `--effort` values and give them to every alias.

        Claude's efforts are provider-wide: the same values are reported for
        every model, and the CLI rejects an unknown one while parsing arguments,
        before a model is chosen. `--help` wraps the values onto a continuation
        line, so the text is flattened before matching.
        """

        match = _CLAUDE_EFFORT_HELP.search(" ".join(stdout.split()))
        if match is None:
            return []
        efforts = [value.strip() for value in match.group(1).split(",") if value.strip()]
        # A parenthesis moving elsewhere in the description would otherwise turn
        # prose into offered efforts. Nothing but a bare word is an effort.
        if not efforts or not all(_CLAUDE_EFFORT_VALUE.fullmatch(value) for value in efforts):
            return []
        default = "medium" if "medium" in efforts else efforts[0]
        return [
            ModelChoice(
                id=model.id, label=model.label, reasoning=efforts, default_reasoning=default
            )
            for model in _CLAUDE_MODELS
        ]

    def launch_degradation(self, stderr: str, *, requested_reasoning: str | None) -> str | None:
        # Claude warns and runs at its default rather than failing, and its
        # stream reports no effort, so this warning is the only signal that the
        # turn did not run the way the human asked.
        if not requested_reasoning or "Unknown --effort value" not in stderr:
            return None
        return (
            f"Claude ignored the requested reasoning effort {requested_reasoning!r} "
            "and ran at its own default."
        )

    def login_probe_command(self, binary: str) -> list[str]:
        # Flags probed with Claude Code 2.1.270 on 2026-09-14.
        return [
            binary,
            "--print",
            "--model",
            "haiku",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--safe-mode",
            "--tools",
            "",
            "--strict-mcp-config",
            "Reply with OK only.",
        ]

    def work_like_probe_command(self, binary: str) -> list[str]:
        return [
            binary,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--input-format",
            "stream-json",
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--settings",
            json.dumps(_claude_write_settings(), separators=(",", ":")),
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
        ]

    def skill_probe(self, binary: str) -> ProviderSkillProbe:
        return ProviderSkillProbe(
            command=[
                binary,
                "--print",
                "/context",
                "--no-session-persistence",
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                "plan",
                "--settings",
                '{"disableAllHooks":true}',
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
            ],
            protocol="jsonl",
        )

    def parse_skills(self, payload: object) -> list[ProviderSkill]:
        if not isinstance(payload, str):
            raise ValueError("Claude skill inventory is not JSONL text")
        init: dict[str, object] | None = None
        for line in payload.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and value.get("type") == "system"
                and value.get("subtype") == "init"
            ):
                init = value
                break
        if init is None or not isinstance(init.get("skills"), list):
            raise ValueError("Claude system/init has no skills list")
        return [
            ProviderSkill(
                name=name,
                label=name,
                description="Claude-native skill loaded by this CLI.",
                scope="plugin" if ":" in name else None,
            )
            for name in dict.fromkeys(init["skills"])
            if isinstance(name, str) and name
        ]

    def project_write_enforcement_mode(self) -> str:
        return "claude.permission-allowlist.v1"

    def command(
        self,
        prompt: str,
        *,
        binary: str,
        cwd: Path,
        model: str | None,
        reasoning: str | None,
        session_id: str | None,
        read_dirs: list[Path],
        write_dirs: list[Path],
        write_scope: ProjectWriteScope | None,
        capability: AgentCapability,
        provider_version: str | None,
    ) -> list[str]:
        # Claude accepts `auto` syntactically but non-interactive `--print`
        # normalizes it to `default` and denies both scratch and repository
        # writes. Work bypasses permission prompts so it can execute unattended;
        # scratch-patch runs retain acceptEdits and the paper coach remains
        # plan-only. Native public-web retrieval is pre-authorized explicitly
        # on non-bypass launches without broadening Bash permissions.
        work_like = capability in {"work_auto", "orchestrate"}
        scope = None
        if work_like:
            scope = _require_project_write_scope(
                write_scope,
                capability=capability,
                write_dirs=write_dirs,
            )
            self.validate_readiness_version(provider_version, capability=capability)
        elif write_scope is not None:
            raise ValueError(f"capability {capability!r} cannot carry a project write scope")
        permission_mode = {
            "discuss": "acceptEdits",
            "work_auto": "dontAsk",
            "orchestrate": "dontAsk",
            "scratch_patch": "acceptEdits",
            "paper_readonly": "plan",
        }[capability]
        command = [
            binary,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            permission_mode,
        ]
        if scope is not None:
            command.extend(
                [
                    "--setting-sources",
                    "",
                    "--settings",
                    json.dumps(_claude_write_settings(scope), separators=(",", ":")),
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                ]
            )
        else:
            command.extend(["--allowedTools", "WebSearch", "WebFetch"])
        if session_id:
            command.extend(["--resume", session_id])
        # Deduplicate while preserving first-seen order: one --add-dir per source
        # session directory previously blew past the argv size limit.
        additional_dirs = [*read_dirs, *write_dirs]
        if scope is not None:
            additional_dirs = [*read_dirs, *(Path(item) for item in scope.repository_roots)]
        for directory in dict.fromkeys(str(item) for item in additional_dirs):
            command.extend(["--add-dir", directory])
        if model:
            command.extend(["--model", model])
        if reasoning:
            command.extend(["--effort", reasoning])
        return command

    def decode_event(self, value: object, raw: str) -> ProviderStreamEvent:
        if not isinstance(value, dict):
            return ProviderStreamEvent(event="raw", text=raw)
        event_type = str(value.get("type") or "")
        subtype = str(value.get("subtype") or "")
        usage = self.decode_usage(value, raw)
        if event_type == "system" and value.get("session_id"):
            return ProviderStreamEvent(
                event="session",
                session_id=str(value["session_id"]),
                usage=usage,
            )
        result = value.get("result")
        detail = _provider_error_text(value)
        terminal_error = (
            value.get("is_error") is True or event_type == "error" or "error" in subtype.casefold()
        )
        if terminal_error:
            return ProviderStreamEvent(
                event="error",
                text=detail or "Claude task failed.",
                usage=usage,
            )
        if isinstance(result, str) and result:
            return ProviderStreamEvent(event="answer", text=result, usage=usage)
        return ProviderStreamEvent(event="raw", text=raw, usage=usage)

    def decode_usage(self, value: dict[str, object], raw: str) -> ProviderUsage | None:
        # Claude's final result is the query-level accounting boundary. Earlier
        # assistant messages may carry step usage and must not be added again.
        if value.get("type") != "result":
            return None
        usage = value.get("usage")
        if not isinstance(usage, dict):
            return None
        reported_input = _usage_int(usage.get("input_tokens"))
        cache_creation = _usage_int(usage.get("cache_creation_input_tokens"))
        cache_read = _usage_int(usage.get("cache_read_input_tokens"))
        reported_output = _usage_int(usage.get("output_tokens"))
        details = usage.get("output_tokens_details")
        thinking = (
            _usage_int(details.get("thinking_tokens"))
            if isinstance(details, dict)
            else _usage_int(usage.get("thinking_tokens"))
        )
        return ProviderUsage(
            provider_profile=self.usage_profile,
            provider_event_type="result",
            dedupe_key=_usage_dedupe_key(value, raw, "message_id", "uuid", "id"),
            processed_input_tokens=reported_input + cache_creation + cache_read,
            generated_tokens=reported_output,
            cached_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
            reasoning_output_tokens=thinking,
            reported_input_tokens=reported_input,
            reported_output_tokens=reported_output,
            reported_total_tokens=_optional_usage_int(usage.get("total_tokens")),
            provider_fields={str(key): item for key, item in usage.items()},
        )


def _provider_error_text(value: dict[str, object]) -> str:
    for candidate in (value.get("result"), value.get("error"), value.get("message")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            message = candidate.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    subtype = value.get("subtype")
    return subtype.strip() if isinstance(subtype, str) else ""


def _usage_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _optional_usage_int(value: object) -> int | None:
    if value is None:
        return None
    return _usage_int(value)


def _usage_dedupe_key(value: dict[str, object], raw: str, *fields: str) -> str:
    for field in fields:
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate:
            return candidate
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_project_write_scope(
    scope: ProjectWriteScope | None,
    *,
    capability: AgentCapability,
    write_dirs: list[Path],
) -> ProjectWriteScope:
    if scope is None:
        raise ValueError(f"{capability} launch requires a resolved project write scope")
    if scope.capability != capability:
        raise ValueError("project write scope capability does not match the provider launch")
    supplied = list(dict.fromkeys(str(item) for item in write_dirs))
    if supplied != scope.repository_roots:
        raise ValueError("provider write directories do not match the resolved project scope")
    return scope


def _require_provider_version(
    *,
    provider: str,
    actual: str | None,
    minimum: tuple[int, int, int],
) -> None:
    parsed = tuple(int(item) for item in re.findall(r"\d+", actual or "")[:3])
    if len(parsed) != 3 or parsed < minimum:
        required = ".".join(str(item) for item in minimum)
        reported = actual or "unknown"
        raise ValueError(
            f"{provider} {reported} cannot enforce the declared project write roots; "
            f"RCP requires {required} or newer"
        )


def _codex_permission_profile(scope: ProjectWriteScope) -> str:
    roots = ",".join(
        f"{json.dumps(path, ensure_ascii=False)}=true" for path in scope.writable_roots
    )
    protected = ",".join(
        f'{json.dumps(path, ensure_ascii=False)}="read"' for path in scope.protected_write_paths
    )
    # Codex protects `.git` separately, so the writable root alone does not let
    # Work run ordinary Git commands such as fetch or pull. `.research` is "read",
    # never "deny": Codex reads `deny` as no access at all, which would also revoke
    # the canonical run context. Invariant 4 protects that state from *writes*.
    return (
        "permissions={rcp_project={workspace_roots={"
        + roots
        + '},filesystem={":root"="read",":workspace_roots"={"."="write",'
        '".git"="write",".research"="read"}'
        + ("," + protected if protected else "")
        + "},network={enabled=true}}}"
    )


def _claude_write_settings(scope: ProjectWriteScope | None = None) -> dict[str, object]:
    # Readiness validates these same settings with no project write authority.
    # Claude's OS sandbox stays off. Its Linux backend always unshares the
    # network namespace and remounts a minimal `/dev`, so a sandboxed Work turn
    # cannot reach a scheduler, a GPU device, or any non-HTTP service on its own
    # execution host. Exact write roots are enforced by Claude's file-permission
    # rules instead: they bound every file-editing tool, and Bash is not bounded.
    writable_roots = scope.writable_roots if scope is not None else []
    protected_write_paths = scope.protected_write_paths if scope is not None else []
    # `Edit(path)` is the only file permission rule Claude matches, and it covers
    # every file-editing tool. A `Write(path)` rule is accepted and then ignored.
    allow_patterns = [f"Edit({_claude_absolute_pattern(path)})" for path in writable_roots]
    deny_patterns = [f"Edit({_claude_absolute_pattern(path)})" for path in protected_write_paths]
    return {
        "disableAllHooks": True,
        "permissions": {
            "defaultMode": "dontAsk",
            "disableAutoMode": "disable",
            "disableBypassPermissionsMode": "disable",
            "allow": ["Bash", "WebSearch", "WebFetch", *allow_patterns],
            "deny": deny_patterns,
        },
        "sandbox": {"enabled": False},
    }


def _claude_absolute_pattern(path: str) -> str:
    return f"//{path.lstrip('/')}/**"


PROVIDERS: dict[str, ProviderProfile] = {
    profile.id: profile for profile in (CodexProfile(), ClaudeProfile())
}
#: Iteration order for every place that walks all providers.
PROVIDER_IDS: tuple[str, ...] = tuple(PROVIDERS)
DEFAULT_PROVIDER = CodexProfile.id


def classify_terminal_error(text: str) -> str:
    """Classify a persisted provider error without depending on a provider id."""
    folded = " ".join(text.casefold().split())
    if any(
        marker in folded
        for marker in (
            "session limit",
            "usage limit",
            "hit your limit",
            "quota exceeded",
            "out of credits",
            "weighted tokens left",
        )
    ):
        return "session_limit"
    # The provider still answers, but the native session RCP asked it to resume
    # is gone. Resuming again cannot work; a fresh session can. Observed from
    # Codex on 2026-09-12 as "collab spawn failed: no thread with id: <uuid>".
    # Only the missing-thread half is the evidence: a spawn that failed for some
    # other reason still has its session, and starting clean would throw away a
    # live checkpoint and repeat the work it holds.
    if "no thread with id" in folded:
        return "stale_session"
    return "provider_error"


def profile_for(provider: str) -> ProviderProfile:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown agent provider: {provider!r}") from None


def legacy_runtime_id(provider: str) -> str:
    """Runtime assigned to records created before runtime identity was durable."""

    return profile_for(provider).legacy_runtime_id


def configured_runtime(provider: str, value: str | None) -> str:
    """Normalize one project-profile runtime without exposing provider internals."""

    return profile_for(provider).configured_runtime(value)


def configured_runtime_id(provider: str, value: str | None) -> str:
    """Resolve one normalized project-profile runtime to its durable identifier."""

    return profile_for(provider).configured_runtime_id(value)


def runtime_label(provider: str, runtime_id: str) -> str:
    """Display name for one durable runtime id, so no surface maps ids itself."""

    return profile_for(provider).runtime_label(runtime_id)


def require_runtime_id(provider: str, runtime_id: str) -> str:
    profile_for(provider).runtime(runtime_id)
    return runtime_id


def project_write_enforcement_mode(provider: str) -> str:
    return profile_for(provider).project_write_enforcement_mode()


def _known_provider(value: str) -> str:
    profile_for(value)
    return value


#: A provider id validated against the registry. Replaces the
#: `Literal["claude", "codex"]` that used to be repeated across the schema
#: layer, so adding a provider does not mean editing every model that names one.
ProviderId = Annotated[str, AfterValidator(_known_provider)]
