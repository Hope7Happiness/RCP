"""Read-only, explicitly imported provider messages kept outside RCP chats."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from rcp.core.transition_models import GraphTargetRef
from rcp.storage.models import AgentTaskAdmissionConflict, AgentTaskRecord

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ProviderHistoryStoreMixin:
    @staticmethod
    def _require_codex_continuation_task(
        connection: sqlite3.Connection, record: AgentTaskRecord
    ) -> None:
        session_id = record.request.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        claim = connection.execute(
            "SELECT * FROM codex_continuations WHERE native_session_id = ?",
            (session_id,),
        ).fetchone()
        if claim is None:
            if (
                record.request.get("provider") == "codex"
                and connection.execute(
                    "SELECT 1 FROM provider_history_imports WHERE provider = 'codex' "
                    "AND session_id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
                and not connection.execute(
                    "SELECT 1 FROM graph_runs WHERE native_session_id = ? "
                    "AND kind IN ('node_chat', 'project_chat') AND history_only = 0 LIMIT 1",
                    (session_id,),
                ).fetchone()
            ):
                raise AgentTaskAdmissionConflict(
                    "An imported Codex session requires explicit continuation admission"
                )
            return
        if (
            record.kind != "project_chat"
            or record.project_id != claim["project_id"]
            or record.graph_target != GraphTargetRef()
            or record.request.get("chat_id") != claim["chat_id"]
            or record.request.get("chat_scope") != "project"
            or record.request.get("provider") != "codex"
            or record.request.get("run_on") != claim["execution_machine"]
            or record.request.get("run_truth_scope") != [claim["repository_alias"]]
        ):
            raise AgentTaskAdmissionConflict(
                "The imported Codex session belongs to a different project chat binding"
            )
        if record.operation_id == claim["first_operation_id"]:
            if record.request.get("mode") != claim["initial_mode"]:
                raise AgentTaskAdmissionConflict(
                    "The first Codex continuation mode changed after admission"
                )
            return
        if (
            connection.execute(
                "SELECT 1 FROM graph_runs WHERE operation_id = ? LIMIT 1",
                (claim["first_operation_id"],),
            ).fetchone()
            is None
        ):
            raise AgentTaskAdmissionConflict(
                "The imported Codex session's first RCP turn has not been admitted"
            )

    def codex_continuation(self, session_id: str) -> dict[str, Any] | None:
        """Read the exclusive, durable owner of an imported native session."""

        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM codex_continuations WHERE native_session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def claim_codex_continuation(
        self,
        *,
        project_id: str,
        session_id: str,
        chat_id: str,
        first_operation_id: str,
        source_path_sha256: str,
        source_sha256: str,
        source_bytes: int,
        source_cwd: str,
        repository_alias: str,
        execution_machine: str,
        initial_mode: str,
        first_message_sha256: str,
    ) -> dict[str, Any]:
        """Bind one imported session to one main-graph project chat exactly once.

        A duplicate first-turn request receives the original chat and operation
        identities. Different prompts or bindings cannot take over that owner.
        """

        for name, value in (
            ("session_id", session_id),
            ("chat_id", chat_id),
            ("first_operation_id", first_operation_id),
        ):
            if str(uuid.UUID(value)) != value:
                raise ValueError(f"{name} must be a canonical UUID")
        if initial_mode not in {"discuss", "work"}:
            raise ValueError("Codex continuation mode must be discuss or work")
        if any(
            not _SHA256.fullmatch(value)
            for value in (source_path_sha256, source_sha256, first_message_sha256)
        ):
            raise ValueError("Codex continuation requires exact SHA-256 identities")
        if not isinstance(source_bytes, int) or source_bytes <= 0:
            raise ValueError("Codex continuation requires its imported source byte length")
        if not source_cwd.startswith("/") or not repository_alias or not execution_machine:
            raise ValueError("Codex continuation requires an absolute source directory")
        now = self.now()
        expected = {
            "project_id": project_id,
            "native_session_id": session_id,
            "source_path_sha256": source_path_sha256,
            "source_sha256": source_sha256,
            "source_bytes": source_bytes,
            "source_cwd": source_cwd,
            "repository_alias": repository_alias,
            "execution_machine": execution_machine,
            "graph_target_json": GraphTargetRef().model_dump_json(),
            "initial_mode": initial_mode,
            "first_message_sha256": first_message_sha256,
        }
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            imported = connection.execute(
                "SELECT source_path_sha256, source_sha256, source_bytes, repository_alias "
                "FROM provider_history_imports WHERE project_id = ? AND provider = 'codex' "
                "AND session_id = ?",
                (project_id, session_id),
            ).fetchone()
            if imported is None or any(
                imported[key] != expected[key] for key in ("source_path_sha256", "repository_alias")
            ):
                raise ValueError("The imported Codex session identity changed or is unavailable")
            row = connection.execute(
                "SELECT * FROM codex_continuations WHERE native_session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None:
                if any(row[key] != value for key, value in expected.items()):
                    raise ValueError("This Codex session already has a different RCP continuation")
                return dict(row)
            if any(imported[key] != expected[key] for key in ("source_sha256", "source_bytes")):
                raise ValueError("The imported Codex session content changed during admission")
            if (
                connection.execute(
                    "SELECT 1 FROM chat_session_contexts WHERE provider = 'codex' "
                    "AND native_session_id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
                or connection.execute(
                    "SELECT 1 FROM graph_runs WHERE native_session_id = ? "
                    "AND kind IN ('node_chat', 'project_chat') AND history_only = 0 LIMIT 1",
                    (session_id,),
                ).fetchone()
            ):
                raise ValueError("This Codex session is already owned by an RCP chat")
            try:
                connection.execute(
                    "INSERT INTO codex_continuations ("
                    "native_session_id, project_id, chat_id, first_operation_id, "
                    "source_path_sha256, source_sha256, source_bytes, source_cwd, "
                    "repository_alias, "
                    "execution_machine, "
                    "graph_target_json, initial_mode, first_message_sha256, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        project_id,
                        chat_id,
                        first_operation_id,
                        source_path_sha256,
                        source_sha256,
                        source_bytes,
                        source_cwd,
                        repository_alias,
                        execution_machine,
                        expected["graph_target_json"],
                        initial_mode,
                        first_message_sha256,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("This chat or task already owns another Codex session") from exc
        claimed = self.codex_continuation(session_id)
        assert claimed is not None
        return claimed

    def save_provider_history(
        self,
        project_id: str,
        *,
        provider: str,
        session_id: str,
        source_path_sha256: str,
        source_sha256: str,
        source_bytes: int,
        repository_alias: str,
        first_timestamp: str | None,
        last_timestamp: str | None,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        existing = self.provider_history(project_id, provider, session_id)
        if existing is not None and existing["source_path_sha256"] != source_path_sha256:
            raise ValueError("This session is already bound to a different source file.")
        if existing is not None and existing["source_sha256"] == source_sha256:
            return existing
        imported_at = self.now()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO provider_history_imports (
                    project_id, provider, session_id, source_path_sha256, source_sha256,
                    source_bytes, repository_alias, first_timestamp, last_timestamp,
                    imported_at, messages_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, provider, session_id) DO UPDATE SET
                    source_sha256 = excluded.source_sha256,
                    source_bytes = excluded.source_bytes,
                    repository_alias = excluded.repository_alias,
                    first_timestamp = excluded.first_timestamp,
                    last_timestamp = excluded.last_timestamp,
                    imported_at = excluded.imported_at,
                    messages_json = excluded.messages_json""",
                (
                    project_id,
                    provider,
                    session_id,
                    source_path_sha256,
                    source_sha256,
                    source_bytes,
                    repository_alias,
                    first_timestamp,
                    last_timestamp,
                    imported_at,
                    json.dumps(messages, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        result = self.provider_history(project_id, provider, session_id)
        assert result is not None
        return result

    def provider_history(
        self, project_id: str, provider: str, session_id: str
    ) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM provider_history_imports WHERE project_id = ? "
                "AND provider = ? AND session_id = ?",
                (project_id, provider, session_id),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["messages"] = json.loads(result.pop("messages_json"))
        return result

    def provider_histories(self, project_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT provider, session_id, source_sha256, source_bytes, repository_alias, "
                "first_timestamp, last_timestamp, imported_at, messages_json "
                "FROM provider_history_imports WHERE project_id = ? "
                "ORDER BY imported_at DESC, session_id",
                (project_id,),
            ).fetchall()
        return [
            {
                "provider": row["provider"],
                "session_id": row["session_id"],
                "source_sha256": row["source_sha256"],
                "source_bytes": row["source_bytes"],
                "repository_alias": row["repository_alias"],
                "first_timestamp": row["first_timestamp"],
                "last_timestamp": row["last_timestamp"],
                "imported_at": row["imported_at"],
                "message_count": len(json.loads(row["messages_json"])),
            }
            for row in rows
        ]
