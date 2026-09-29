from __future__ import annotations

import json
import sqlite3

from rcp.providers import ProviderSkill
from rcp.storage.models import (
    _PROJECT_ID_TABLES,
    ProjectActiveTaskConflict,
    ProjectRecord,
    ProjectStageRecord,
    ProviderSkillInventoryRecord,
    _canonical_uuid4,
)


class ProjectStoreMixin:
    """The project catalog, identity migration, and provider skill inventory."""

    def provider_skill_inventory(
        self,
        provider: str,
        host: str,
        configured_binary: str | None,
    ) -> ProviderSkillInventoryRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_skill_inventories
                WHERE provider = ? AND host = ? AND configured_binary = ?
                """,
                (provider, host, configured_binary or ""),
            ).fetchone()
        if row is None:
            return None
        return ProviderSkillInventoryRecord(
            provider=row["provider"],
            host=row["host"],
            configured_binary=row["configured_binary"],
            resolved_binary=row["resolved_binary"],
            provider_version=row["provider_version"],
            command=json.loads(row["command_json"]),
            protocol=row["protocol"],
            skills=[ProviderSkill.model_validate(item) for item in json.loads(row["skills_json"])],
            inventory_hash=row["inventory_hash"],
            status=row["status"],
            diagnostic=row["diagnostic"],
            refreshed_at=row["refreshed_at"],
            updated_at=row["updated_at"],
        )

    def mark_provider_skill_inventory_refreshing(
        self,
        provider: str,
        host: str,
        configured_binary: str | None,
        *,
        updated_at: str,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_skill_inventories (
                    provider, host, configured_binary, status, updated_at
                ) VALUES (?, ?, ?, 'refreshing', ?)
                ON CONFLICT(provider, host, configured_binary) DO UPDATE SET
                    status = 'refreshing', diagnostic = NULL, updated_at = excluded.updated_at
                """,
                (provider, host, configured_binary or "", updated_at),
            )

    def save_provider_skill_inventory_success(
        self,
        provider: str,
        host: str,
        configured_binary: str | None,
        *,
        resolved_binary: str,
        provider_version: str,
        command: list[str],
        protocol: str,
        skills: list[ProviderSkill],
        inventory_hash: str,
        refreshed_at: str,
    ) -> None:
        skill_payload = [item.model_dump(mode="json") for item in skills]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_skill_inventories (
                    provider, host, configured_binary, resolved_binary,
                    provider_version, command_json, protocol, skills_json,
                    inventory_hash, status, diagnostic, refreshed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'fresh', NULL, ?, ?)
                ON CONFLICT(provider, host, configured_binary) DO UPDATE SET
                    resolved_binary = excluded.resolved_binary,
                    provider_version = excluded.provider_version,
                    command_json = excluded.command_json,
                    protocol = excluded.protocol,
                    skills_json = excluded.skills_json,
                    inventory_hash = excluded.inventory_hash,
                    status = 'fresh',
                    diagnostic = NULL,
                    refreshed_at = excluded.refreshed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    provider,
                    host,
                    configured_binary or "",
                    resolved_binary,
                    provider_version,
                    json.dumps(command, separators=(",", ":")),
                    protocol,
                    json.dumps(skill_payload, sort_keys=True, separators=(",", ":")),
                    inventory_hash,
                    refreshed_at,
                    refreshed_at,
                ),
            )

    def save_provider_skill_inventory_failure(
        self,
        provider: str,
        host: str,
        configured_binary: str | None,
        *,
        diagnostic: str,
        updated_at: str,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_skill_inventories (
                    provider, host, configured_binary, status, diagnostic, updated_at
                ) VALUES (?, ?, ?, 'unavailable', ?, ?)
                ON CONFLICT(provider, host, configured_binary) DO UPDATE SET
                    status = CASE
                        WHEN provider_skill_inventories.refreshed_at IS NULL
                        THEN 'unavailable'
                        ELSE 'stale'
                    END,
                    diagnostic = excluded.diagnostic,
                    updated_at = excluded.updated_at
                """,
                (provider, host, configured_binary or "", diagnostic, updated_at),
            )

    def project_by_locator(self, locator: str) -> ProjectRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE locator = ? AND retired_at IS NULL", (locator,)
            ).fetchone()
        return self._project_record(row) if row else None

    def project(self, project_id: str) -> ProjectRecord | None:
        with self.connection() as connection:
            canonical_project_id = self._resolve_project_id_from_connection(connection, project_id)
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ? AND retired_at IS NULL",
                (canonical_project_id,),
            ).fetchone()
        return self._project_record(row) if row else None

    def retired_project(self, project_id: str) -> ProjectRecord | None:
        with self.connection() as connection:
            canonical_project_id = self._resolve_project_id_from_connection(connection, project_id)
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ? AND retired_at IS NOT NULL",
                (canonical_project_id,),
            ).fetchone()
        return self._project_record(row) if row else None

    def resolve_project_id(self, project_id: str) -> str:
        with self.connection() as connection:
            return self._resolve_project_id_from_connection(connection, project_id)

    def project_aliases(self) -> dict[str, str]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT alias_id, canonical_project_id
                FROM project_aliases
                ORDER BY alias_id
                """
            ).fetchall()
        aliases: dict[str, str] = {}
        for row in rows:
            aliases[str(row["alias_id"])] = _canonical_uuid4(
                row["canonical_project_id"], label="canonical project identity"
            )
        return aliases

    def projects(self) -> list[ProjectRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM projects
                WHERE retired_at IS NULL
                ORDER BY added_at DESC, name COLLATE NOCASE, project_id
                """
            ).fetchall()
        return [self._project_record(row) for row in rows]

    def migrate_project_identity(
        self,
        old_project_id: str,
        canonical_project_id: str,
        home_space_id: str,
    ) -> ProjectRecord:
        try:
            canonical_project_id = _canonical_uuid4(
                canonical_project_id, label="canonical project identity"
            )
            home_space_id = _canonical_uuid4(home_space_id, label="project home space identity")
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                alias = connection.execute(
                    "SELECT canonical_project_id FROM project_aliases WHERE alias_id = ?",
                    (old_project_id,),
                ).fetchone()
                if alias is not None and alias["canonical_project_id"] != canonical_project_id:
                    raise ValueError(
                        f"Project alias {old_project_id!r} already resolves to "
                        f"{alias['canonical_project_id']!r}."
                    )
                canonical_alias = connection.execute(
                    "SELECT canonical_project_id FROM project_aliases WHERE alias_id = ?",
                    (canonical_project_id,),
                ).fetchone()
                if canonical_alias is not None:
                    raise ValueError(
                        f"Canonical project id {canonical_project_id!r} is already an alias."
                    )

                old_row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (old_project_id,)
                ).fetchone()
                canonical_row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (canonical_project_id,)
                ).fetchone()

                if old_project_id == canonical_project_id:
                    if old_row is None:
                        raise KeyError(old_project_id)
                    stored_home = old_row["home_space_id"]
                    if stored_home is not None and stored_home != home_space_id:
                        raise ValueError(
                            f"Project {canonical_project_id!r} already belongs to {stored_home!r}."
                        )
                    if stored_home is None:
                        connection.execute(
                            "UPDATE projects SET home_space_id = ? WHERE project_id = ?",
                            (home_space_id, canonical_project_id),
                        )
                    row = connection.execute(
                        "SELECT * FROM projects WHERE project_id = ?", (canonical_project_id,)
                    ).fetchone()
                    assert row is not None
                    return self._project_record(row)

                if old_row is None:
                    if alias is None:
                        if canonical_row is not None:
                            raise ValueError(
                                f"Project identity destination {canonical_project_id!r} "
                                "already exists without the requested alias."
                            )
                        raise KeyError(old_project_id)
                    if canonical_row is None:
                        raise KeyError(canonical_project_id)
                    if canonical_row["home_space_id"] != home_space_id:
                        raise ValueError(
                            f"Project {canonical_project_id!r} already belongs to "
                            f"{canonical_row['home_space_id']!r}."
                        )
                    for table in _PROJECT_ID_TABLES:
                        if (
                            connection.execute(
                                f"SELECT 1 FROM {table} WHERE project_id = ? LIMIT 1",
                                (old_project_id,),
                            ).fetchone()
                            is not None
                        ):
                            raise RuntimeError(
                                f"Project alias {old_project_id!r} still has rows in {table}."
                            )
                    return self._project_record(canonical_row)

                if canonical_row is not None:
                    raise ValueError(
                        f"Project identity destination {canonical_project_id!r} "
                        "already contains a project registration."
                    )
                for table in _PROJECT_ID_TABLES[1:]:
                    if (
                        connection.execute(
                            f"SELECT 1 FROM {table} WHERE project_id = ? LIMIT 1",
                            (canonical_project_id,),
                        ).fetchone()
                        is not None
                    ):
                        raise ValueError(
                            f"Project identity destination {canonical_project_id!r} "
                            f"already contains rows in {table}."
                        )

                connection.execute(
                    """
                    UPDATE projects
                    SET project_id = ?, home_space_id = ?
                    WHERE project_id = ?
                    """,
                    (canonical_project_id, home_space_id, old_project_id),
                )
                for table in _PROJECT_ID_TABLES[1:]:
                    connection.execute(
                        f"UPDATE {table} SET project_id = ? WHERE project_id = ?",
                        (canonical_project_id, old_project_id),
                    )
                connection.execute(
                    "UPDATE conversation_worktrees "
                    "SET binding_json = json_set(binding_json, '$.project_id', ?) "
                    "WHERE project_id = ?",
                    (canonical_project_id, canonical_project_id),
                )
                if alias is None:
                    connection.execute(
                        """
                        INSERT INTO project_aliases(alias_id, canonical_project_id)
                        VALUES (?, ?)
                        """,
                        (old_project_id, canonical_project_id),
                    )
                row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (canonical_project_id,)
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "Canonical project registration disappeared during migration."
                    )
                return self._project_record(row)
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError(
                    f"Project identity migration to {canonical_project_id!r} conflicted."
                ) from exc
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _resolve_project_id_from_connection(
        connection: sqlite3.Connection,
        project_id: str,
    ) -> str:
        row = connection.execute(
            "SELECT canonical_project_id FROM project_aliases WHERE alias_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return project_id
        return _canonical_uuid4(row["canonical_project_id"], label="canonical project identity")

    def project_deletion_stages(self, project_id: str) -> list[ProjectStageRecord]:
        """Return the saved scratch stages after proving deletion is currently safe."""
        with self.connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
                ).fetchone()
                is None
            ):
                raise KeyError(project_id)
            self._require_project_deletion_safe(connection, project_id)
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(stage_host, '') AS host, stage_root AS root
                FROM graph_runs
                WHERE project_id = ? AND stage_root IS NOT NULL
                """,
                (project_id,),
            ).fetchall()
        return [ProjectStageRecord.model_validate(dict(row)) for row in rows]

    def delete_project_records(self, project_id: str) -> dict[str, int]:
        """Atomically delete every database row owned by one registration.

        The active-task check is repeated under a write lock so a task cannot be
        launched between the catalog's cleanup preflight and the database commit.
        """
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if (
                    connection.execute(
                        "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
                    ).fetchone()
                    is None
                ):
                    raise KeyError(project_id)
                self._require_project_deletion_safe(connection, project_id)

                operation_ids = connection.execute(
                    "SELECT operation_id FROM graph_runs WHERE project_id = ?",
                    (project_id,),
                ).fetchall()
                operation_count = len(operation_ids)
                counts = {
                    "project_invitations": connection.execute(
                        "DELETE FROM project_invitations WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "project_members": connection.execute(
                        "DELETE FROM project_members WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "paper_drafts": connection.execute(
                        "DELETE FROM paper_drafts WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "writing_sessions": connection.execute(
                        "DELETE FROM writing_sessions WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "chat_session_contexts": connection.execute(
                        "DELETE FROM chat_session_contexts WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "chat_display": connection.execute(
                        "DELETE FROM chat_display WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "provider_history_imports": connection.execute(
                        "DELETE FROM provider_history_imports WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "conversation_worktrees": connection.execute(
                        "DELETE FROM conversation_worktrees WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "result_views": connection.execute(
                        "DELETE FROM result_views WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "artifact_revision_candidates": connection.execute(
                        "DELETE FROM artifact_revision_candidates WHERE project_id = ?",
                        (project_id,),
                    ).rowcount,
                    "compute_jobs": connection.execute(
                        "DELETE FROM compute_jobs WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "compute_backend_probes": connection.execute(
                        "DELETE FROM compute_backend_probes WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "watchers": connection.execute(
                        "DELETE FROM watchers WHERE project_id = ?", (project_id,)
                    ).rowcount,
                    "graph_watcher_reconciliation": connection.execute(
                        "DELETE FROM graph_watcher_reconciliation WHERE project_id = ?",
                        (project_id,),
                    ).rowcount,
                }
                for table in (
                    "_legacy_campaign_invocations_archive",
                    "_legacy_campaign_messages_archive",
                    "_legacy_campaign_recoveries_archive",
                    "_legacy_campaign_reports_archive",
                ):
                    counts[table] = connection.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE campaign_id IN (
                            SELECT campaign_id FROM _legacy_campaigns_archive
                            WHERE project_id = ?
                        )
                        """,
                        (project_id,),
                    ).rowcount
                counts["_legacy_campaigns_archive"] = connection.execute(
                    "DELETE FROM _legacy_campaigns_archive WHERE project_id = ?", (project_id,)
                ).rowcount
                connection.execute(
                    """
                    DELETE FROM auto_research_child_work_attempts
                    WHERE worker_id IN (
                        SELECT worker_id FROM auto_research_child_work WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                connection.execute(
                    """
                    DELETE FROM auto_research_experiment_invocations
                    WHERE auto_research_episode_id IN (
                        SELECT episode_id FROM episodes WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                for table in (
                    "auto_research_command_files",
                    "auto_research_apply_results",
                    "auto_research_inbox_receipts",
                    "auto_research_finish_receipts",
                    "auto_research_lifecycle_notices",
                ):
                    connection.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE episode_id IN (
                            SELECT episode_id FROM episodes WHERE project_id = ?
                        )
                        """,
                        (project_id,),
                    )
                connection.execute(
                    "DELETE FROM auto_research_child_admissions WHERE project_id = ?",
                    (project_id,),
                )
                connection.execute(
                    "DELETE FROM auto_research_child_experiments WHERE project_id = ?",
                    (project_id,),
                )
                connection.execute(
                    "DELETE FROM auto_research_child_work WHERE project_id = ?",
                    (project_id,),
                )
                for table in (
                    "auto_research_recoveries",
                    "auto_research_messages",
                    "auto_research_invocations",
                    "auto_research_episodes",
                    "experiment_episode_state",
                    "episode_reports",
                    "episode_report_attempts",
                    "episode_wrapups",
                    "episode_invocations",
                    "episode_archives",
                ):
                    counts[table] = connection.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE episode_id IN (
                            SELECT episode_id FROM episodes WHERE project_id = ?
                        )
                        """,
                        (project_id,),
                    ).rowcount
                counts["episodes"] = connection.execute(
                    "DELETE FROM episodes WHERE project_id = ?", (project_id,)
                ).rowcount
                counts["agent_usage"] = connection.execute(
                    "DELETE FROM agent_usage WHERE project_id = ?", (project_id,)
                ).rowcount
                for table in (
                    "graph_run_outputs",
                    "graph_run_events",
                    "graph_run_receipts",
                    "graph_run_contracts",
                ):
                    counts[table] = connection.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE operation_id IN (
                            SELECT operation_id FROM graph_runs WHERE project_id = ?
                        )
                        """,
                        (project_id,),
                    ).rowcount
                counts["graph_runs"] = connection.execute(
                    "DELETE FROM graph_runs WHERE project_id = ?", (project_id,)
                ).rowcount
                assert counts["graph_runs"] == operation_count
                counts["project_transfer_import_configurations"] = connection.execute(
                    """
                    DELETE FROM project_transfer_import_configurations
                    WHERE request_id IN (
                        SELECT request_id FROM project_transfer_imports WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                ).rowcount
                counts["project_transfer_imports"] = connection.execute(
                    "DELETE FROM project_transfer_imports WHERE project_id = ?", (project_id,)
                ).rowcount
                counts["project_transfer_restore_reentries"] = connection.execute(
                    """
                    DELETE FROM project_transfer_restore_reentries
                    WHERE target_request_id IN (
                        SELECT request_id FROM project_transfer_requests WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                ).rowcount
                counts["project_transfer_activations"] = connection.execute(
                    "DELETE FROM project_transfer_activations WHERE project_id = ?", (project_id,)
                ).rowcount
                counts["project_transfer_uploads"] = connection.execute(
                    "DELETE FROM project_transfer_uploads WHERE project_id = ?", (project_id,)
                ).rowcount
                counts["project_transfer_proofs"] = connection.execute(
                    """
                    DELETE FROM project_transfer_proofs
                    WHERE request_id IN (
                        SELECT request_id FROM project_transfer_requests WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                ).rowcount
                counts["project_transfer_requests"] = connection.execute(
                    "DELETE FROM project_transfer_requests WHERE project_id = ?", (project_id,)
                ).rowcount
                counts["project_provisioning_step_receipts"] = connection.execute(
                    """
                    DELETE FROM project_provisioning_step_receipts
                    WHERE request_id IN (
                        SELECT request_id FROM project_provisioning_requests
                        WHERE proposed_project_id = ? AND status = 'completed'
                    )
                    """,
                    (project_id,),
                ).rowcount
                counts["project_provisioning_requests"] = connection.execute(
                    """
                    DELETE FROM project_provisioning_requests
                    WHERE proposed_project_id = ? AND status = 'completed'
                    """,
                    (project_id,),
                ).rowcount
                counts["projects"] = connection.execute(
                    "DELETE FROM projects WHERE project_id = ?", (project_id,)
                ).rowcount
                if counts["projects"] != 1:
                    raise RuntimeError("Project registration disappeared during deletion")
            except Exception:
                connection.rollback()
                raise
        return counts

    @staticmethod
    def _require_project_deletion_safe(
        connection: sqlite3.Connection,
        project_id: str,
    ) -> None:
        running_jobs = connection.execute(
            "SELECT COUNT(*) FROM compute_jobs WHERE project_id = ? AND status = 'running'",
            (project_id,),
        ).fetchone()[0]
        if running_jobs:
            raise ProjectActiveTaskConflict(
                f"This project has {running_jobs} running compute job(s). "
                "Cancel or wait for those jobs first before deleting this project."
            )
        if (
            connection.execute(
                """
                SELECT 1 FROM graph_runs
                WHERE project_id = ? AND status IN ('queued', 'running', 'pausing')
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            is not None
        ):
            raise ProjectActiveTaskConflict(
                "Pause the active agent task before deleting this project."
            )
        if (
            connection.execute(
                """
                SELECT 1 FROM episodes
                WHERE project_id = ?
                  AND status IN ('queued', 'running', 'stopping', 'wrapping_up')
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            is not None
        ):
            raise ProjectActiveTaskConflict(
                "Use Stop and wait for the live episode to settle before deleting this project."
            )
        if (
            connection.execute(
                """
                SELECT 1 FROM project_transfer_requests
                WHERE project_id = ? AND phase != 'completed'
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            is not None
        ):
            raise ProjectActiveTaskConflict(
                "Let the project transfer finish before deleting this project."
            )
        if (
            connection.execute(
                """
                SELECT 1 FROM watchers
                WHERE project_id = ?
                  AND (
                    status = 'active'
                    OR (status IN ('degraded', 'completed') AND notified = 0)
                  )
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            is not None
        ):
            raise ProjectActiveTaskConflict("Use stop watching before deleting this project.")

    def upsert_project(self, record: ProjectRecord) -> ProjectRecord:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, home_space_id, locator, name, state_location, state_remote, added_at,
                    last_opened_at, revision, primary_question, attention_count,
                    last_refresh_at, reachable, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    locator = excluded.locator,
                    name = excluded.name,
                    state_location = excluded.state_location,
                    state_remote = excluded.state_remote
                """,
                (
                    record.project_id,
                    record.home_space_id,
                    record.locator,
                    record.name,
                    record.state_location,
                    int(record.state_remote),
                    record.added_at,
                    record.last_opened_at,
                    record.revision,
                    record.primary_question,
                    record.attention_count,
                    record.last_refresh_at,
                    None if record.reachable is None else int(record.reachable),
                    record.error,
                ),
            )
        stored = self.project(record.project_id)
        assert stored is not None
        return stored

    def rebind_project_registration_for_restore(
        self,
        project_id: str,
        *,
        home_space_id: str,
        name: str,
        locator: str,
        state_location: str,
        state_remote: bool,
    ) -> ProjectRecord:
        """Move one stopped restored catalog row to its replacement checkout."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(project_id)
            current = self._project_record(row)
            if current.home_space_id != home_space_id or current.name != name:
                connection.rollback()
                raise ValueError("restored project identity changed before checkout rebinding")
            try:
                connection.execute(
                    """
                    UPDATE projects
                    SET locator = ?, state_location = ?, state_remote = ?,
                        reachable = 0, error = ?
                    WHERE project_id = ?
                    """,
                    (
                        locator,
                        state_location,
                        int(state_remote),
                        "Replacement restore publication is pending.",
                        project_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if updated is None:
                    raise RuntimeError("restored project disappeared during checkout rebinding")
                return self._project_record(updated)
            except Exception:
                connection.rollback()
                raise

    def complete_project_publication_for_restore(
        self,
        project_id: str,
        *,
        expected_locator: str,
        revision: int,
    ) -> ProjectRecord:
        """Expose one stopped restored row only after canonical replay succeeds."""

        if revision < 0:
            raise ValueError("restored project revision must be non-negative")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(project_id)
            current = self._project_record(row)
            if current.locator != expected_locator:
                connection.rollback()
                raise ValueError("restored project locator changed before publication")
            if current.reachable is True:
                if current.revision != revision or current.error is not None:
                    connection.rollback()
                    raise RuntimeError("restored project visibility receipt conflicts")
                return current
            if current.error != "Replacement restore publication is pending.":
                connection.rollback()
                raise RuntimeError("restored project is not awaiting canonical publication")
            connection.execute(
                """
                UPDATE projects
                SET revision = ?, reachable = 1, error = NULL, last_refresh_at = ?
                WHERE project_id = ?
                """,
                (revision, self.now(), project_id),
            )
            updated = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if updated is None:
                raise RuntimeError("restored project disappeared during publication")
            return self._project_record(updated)

    def mark_uncaptured_project_unavailable_for_restore(
        self,
        project_id: str,
        *,
        diagnostic: str,
    ) -> ProjectRecord:
        """Keep one explicitly uncaptured project visible but unavailable."""

        detail = " ".join(diagnostic.split())[:1400]
        if not detail:
            raise ValueError("uncaptured restored project requires a diagnostic")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(project_id)
            connection.execute(
                "UPDATE projects SET reachable = 0, error = ? WHERE project_id = ?",
                (f"Not captured by the replacement archive: {detail}", project_id),
            )
            updated = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if updated is None:
                raise RuntimeError("uncaptured restored project disappeared")
            return self._project_record(updated)

    def update_project_summary(
        self,
        project_id: str,
        *,
        revision: int,
        primary_question: str | None,
        attention_count: int,
        last_refresh_at: str | None,
        reachable: bool,
        error: str | None,
    ) -> ProjectRecord:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE projects
                SET last_opened_at = ?, revision = ?, primary_question = ?,
                    attention_count = ?, last_refresh_at = ?, reachable = ?, error = ?
                WHERE project_id = ?
                """,
                (
                    self.now(),
                    revision,
                    primary_question,
                    attention_count,
                    last_refresh_at,
                    int(reachable),
                    error,
                    project_id,
                ),
            )
        stored = self.project(project_id)
        if stored is None:
            raise KeyError(project_id)
        return stored

    def migrate_legacy_project_data(self, legacy_id: str, project_id: str) -> None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            target = connection.execute(
                "SELECT home_space_id FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            target_alias = connection.execute(
                "SELECT canonical_project_id FROM project_aliases WHERE alias_id = ?",
                (project_id,),
            ).fetchone()
            space = connection.execute(
                "SELECT space_id FROM space_identity WHERE singleton = 1"
            ).fetchone()
            try:
                _canonical_uuid4(project_id, label="canonical project identity")
            except RuntimeError:
                canonical_target = False
            else:
                canonical_target = True
            if (
                target is None
                or target_alias is not None
                or space is None
                or target["home_space_id"] != space["space_id"]
                or not canonical_target
            ):
                raise ValueError(
                    f"Legacy project data migration target {project_id!r} is not an exact "
                    "canonical project registration."
                )
            if legacy_id == project_id:
                return

            legacy_project = connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (legacy_id,),
            ).fetchone()
            if legacy_project is not None:
                raise ValueError(
                    f"Legacy project data migration source {legacy_id!r} is already a "
                    "registered canonical project."
                )
            legacy_alias = connection.execute(
                "SELECT canonical_project_id FROM project_aliases WHERE alias_id = ?",
                (legacy_id,),
            ).fetchone()
            if legacy_alias is not None and legacy_alias["canonical_project_id"] != project_id:
                raise ValueError(
                    f"Legacy project data migration source alias {legacy_id!r} belongs to "
                    f"canonical project {legacy_alias['canonical_project_id']!r}, not "
                    f"{project_id!r}."
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO paper_drafts (
                    project_id, content, base_hash, updated_at, cursor_state, ancestor_content
                )
                SELECT ?, content, base_hash, updated_at, cursor_state, ancestor_content
                FROM paper_drafts
                WHERE project_id = ?
                """,
                (project_id, legacy_id),
            )
            # Canonical wins on conflict, but the legacy identity must still be
            # retired so it cannot reappear as a second draft owner.
            connection.execute(
                "DELETE FROM paper_drafts WHERE project_id = ?",
                (legacy_id,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO project_members (
                    project_id, user_id, seated_at, seated_by
                )
                SELECT ?, user_id, seated_at, seated_by
                FROM project_members
                WHERE project_id = ?
                """,
                (project_id, legacy_id),
            )
            connection.execute(
                "DELETE FROM project_members WHERE project_id = ?",
                (legacy_id,),
            )
            connection.execute(
                "UPDATE writing_sessions SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE chat_session_contexts SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE chat_display SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE provider_history_imports SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE conversation_worktrees "
                "SET project_id = ?, binding_json = json_set(binding_json, '$.project_id', ?) "
                "WHERE project_id = ?",
                (project_id, project_id, legacy_id),
            )
            connection.execute(
                "UPDATE result_views SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE artifact_revision_candidates SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE graph_runs SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE episodes SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE agent_usage SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE compute_jobs SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE compute_backend_probes SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE watchers SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO graph_watcher_reconciliation (
                    project_id, graph_target_key, graph_target_json,
                    revision, transition_id, updated_at
                )
                SELECT ?, graph_target_key, graph_target_json,
                       revision, transition_id, updated_at
                FROM graph_watcher_reconciliation
                WHERE project_id = ?
                """,
                (project_id, legacy_id),
            )
            connection.execute(
                "DELETE FROM graph_watcher_reconciliation WHERE project_id = ?",
                (legacy_id,),
            )
            connection.execute(
                "UPDATE auto_research_child_work SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE auto_research_child_experiments SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
            connection.execute(
                "UPDATE auto_research_child_admissions SET project_id = ? WHERE project_id = ?",
                (project_id, legacy_id),
            )
