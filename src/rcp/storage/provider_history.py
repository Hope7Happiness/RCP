"""Read-only, explicitly imported provider messages kept outside RCP chats."""

from __future__ import annotations

import json
from typing import Any


class ProviderHistoryStoreMixin:
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
