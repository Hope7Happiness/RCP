from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rcp.api.app import create_app
from rcp.api.server_status import project_server_status
from rcp.release_check import UpdateNotice
from rcp.server_ops.backup import BackupArchiveReceipt, BackupRunRefused
from rcp.server_ops.doctor import ServerDoctorReport
from rcp.storage import AppStore

COMMIT = "a" * 40
UPSTREAM = "b" * 40
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _protected_backup() -> BackupArchiveReceipt:
    return BackupArchiveReceipt(
        installation_id="5dd24fa7-f302-4f2e-85cf-86cfd55eeadb",
        space_id="e006232f-2c66-4a7e-aeab-d40743326be8",
        capture_id="1e0187e2-9c29-47e8-93c9-939545833db3",
        destination="/srv/backup",
        archive_name=(
            "rcp-team-backup-v1-20260830T030000000000Z-1e0187e2-9c29-47e8-93c9-939545833db3.tar.age"
        ),
        captured_at=NOW - timedelta(hours=9, minutes=1),
        protected_at=NOW - timedelta(hours=9),
        capture_status="partial",
        age_version="1.3.1",
        age_recipient_fingerprint="d" * 64,
        archive_sha256="e" * 64,
        archive_size_bytes=8192,
        manifest_sha256="f" * 64,
        captured_bytes=4096,
        project_count=4,
        protected_project_count=3,
        uncaptured_project_count=1,
    )


def _report(**changes: object) -> ServerDoctorReport:
    values: dict[str, object] = {
        "overall_state": "problems",
        "installation_id": "5dd24fa7-f302-4f2e-85cf-86cfd55eeadb",
        "service_account": "rcp",
        "data_dir": "/home/rcp/rcp-server/data",
        "source_root": "/home/rcp/rcp-server/source",
        "releases_root": "/home/rcp/rcp-server/releases",
        "configured_origin": "git@github.com:openai/rcp.git",
        "configured_branch": "main",
        "source_public_key_fingerprint": "SHA256:source",
        "managed_main_head": COMMIT,
        "upstream_head": UPSTREAM,
        "candidate_commit": None,
        "current_commit": COMMIT,
        "running_commit": COMMIT,
        "release_state": "aligned",
        "source_state": "update_available",
        "current_web_build_id": None,
        "running_web_build_id": None,
        "service_active_state": "active",
        "service_unit_file_state": "enabled",
        "service_main_pid": 123,
        "reload_mode": "disabled",
        "space_id": "e006232f-2c66-4a7e-aeab-d40743326be8",
        "instance_id": "92cc19d4-7736-4911-9ef2-8364f24801cd",
        "process_pid": 123,
        "data_dir_id": "c" * 64,
        "control_socket_status": "healthy",
        "provider_check_status": "available",
        "dependencies_ready": True,
        "dependency_versions": "git=2.43.0,node=24.1.0,python=3.12.11",
        "backup_status": "partial",
        "backup_destination": "/srv/backup",
        "backup_schedule": "02:00",
        "backup_retention": 30,
        "backup_recipient_fingerprint": "d" * 64,
        "backup_timer_active_state": "active",
        "backup_timer_unit_file_state": "enabled",
        "last_backup_at": NOW - timedelta(hours=8),
        "last_backup_archive": "/srv/backup/team.tar.age",
        "last_backup_captured_bytes": 4096,
        "last_backup_protected_projects": 3,
        "last_backup_uncaptured_projects": 1,
        "last_backup_failure": None,
        "update_operation_state": "none",
        "update_candidate_commit": None,
        "update_restored_commit": None,
        "update_failure": None,
        "problems": ("the last protected backup is partial; inspect uncaptured projects",),
    }
    values.update(changes)
    return ServerDoctorReport.model_validate(values)


def test_server_status_projects_concrete_read_models_without_mutation(tmp_path) -> None:
    store, _bootstrap = AppStore.initialize_team_space(tmp_path / "rcp.sqlite3", "Team Lab")
    member = store.preprovision_team_member("Alice")
    restored_at = NOW - timedelta(days=17, hours=3)
    app = create_app(
        data_dir=tmp_path,
        trusted_principal_resolver=lambda _request, opened: opened.space_user(member.user_id),
        server_doctor_reader=_report,
        server_protected_backup_reader=lambda _report: _protected_backup(),
        server_restore_completed_at_reader=lambda: restored_at,
        server_status_clock=lambda: NOW,
    )

    with TestClient(app, base_url="https://team.test") as client:
        response = client.get("/api/server-status")
        refused = client.post("/api/server-status", json={})

    assert response.status_code == 200
    payload = response.json()
    payload["overall"].pop("label")
    assert payload["overall"] == {"tone": "bad"}
    payload["releases"]["status"].pop("label")
    assert payload["releases"] == {
        "status": {"tone": "good"},
        "managed_source_commit": COMMIT,
        "current_release_commit": COMMIT,
        "running_commit": COMMIT,
        "upstream_commit": UPSTREAM,
        "candidate_commit": None,
        "update_available": False,
        "last_update_failure": None,
        "command": "rcp server update",
    }
    payload["backup"]["status"].pop("label")
    assert payload["backup"]["status"] == {"tone": "bad"}
    assert payload["backup"]["protected_projects"] == 3
    assert payload["backup"]["uncaptured_projects"] == 1
    assert payload["backup"]["last_attempt_at"] == "2026-08-30T04:00:00Z"
    assert payload["backup"]["last_protected_at"] == "2026-08-30T03:00:00Z"
    payload["restore"]["status"].pop("label")
    assert payload["restore"] == {
        "status": {"tone": "good"},
        "last_completed_at": "2026-08-13T09:00:00Z",
        "drill_age_days": 17,
        "command": "rcp server restore",
    }
    payload["execution"]["machine"].pop("label")
    assert payload["execution"]["machine"] == {"tone": "good"}
    payload["execution"]["provider_checks"].pop("label")
    assert payload["execution"]["provider_checks"] == {"tone": "good"}
    # Machine operations are console work with CLI help of their own; the
    # projection reports health and never carries a command catalogue.
    assert "operator_commands" not in payload
    assert refused.status_code == 405


def test_server_status_is_team_only_and_fails_loudly_on_unsafe_read(tmp_path) -> None:
    personal = create_app(
        data_dir=tmp_path / "personal",
        server_doctor_reader=_report,
        server_restore_completed_at_reader=lambda: None,
        server_status_clock=lambda: NOW,
    )
    with TestClient(personal) as client:
        assert client.get("/api/server-status").status_code == 404

    team_dir = tmp_path / "team"
    store, _bootstrap = AppStore.initialize_team_space(team_dir / "rcp.sqlite3", "Team Lab")
    member = store.preprovision_team_member("Alice")

    def unsafe_read() -> ServerDoctorReport:
        raise ValueError("unsafe doctor state")

    team = create_app(
        data_dir=team_dir,
        trusted_principal_resolver=lambda _request, opened: opened.space_user(member.user_id),
        server_doctor_reader=unsafe_read,
        server_restore_completed_at_reader=lambda: None,
        server_status_clock=lambda: NOW,
    )
    with TestClient(team, base_url="https://team.test") as client:
        response = client.get("/api/server-status")

    assert response.status_code == 503

    unsafe_receipt = create_app(
        data_dir=team_dir,
        trusted_principal_resolver=lambda _request, opened: opened.space_user(member.user_id),
        server_doctor_reader=_report,
        server_protected_backup_reader=lambda _report: (_ for _ in ()).throw(
            BackupRunRefused("A retained backup receipt is invalid.")
        ),
        server_restore_completed_at_reader=lambda: None,
        server_status_clock=lambda: NOW,
    )
    with TestClient(unsafe_receipt, base_url="https://team.test") as client:
        receipt_response = client.get("/api/server-status")
    assert receipt_response.status_code == 503
    assert receipt_response.json()["detail"] == response.json()["detail"]


def test_server_status_default_restore_reader_keeps_team_settings_available(tmp_path) -> None:
    store, _bootstrap = AppStore.initialize_team_space(tmp_path / "rcp.sqlite3", "Team Lab")
    member = store.preprovision_team_member("Alice")
    app = create_app(
        data_dir=tmp_path,
        trusted_principal_resolver=lambda _request, opened: opened.space_user(member.user_id),
        server_doctor_reader=_report,
        server_protected_backup_reader=lambda _report: _protected_backup(),
        server_status_clock=lambda: NOW,
    )

    with TestClient(app, base_url="https://team.test", raise_server_exceptions=False) as client:
        response = client.get("/api/server-status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["releases"]["running_commit"] == COMMIT
    assert payload["backup"]["protected_projects"] == 3
    payload["restore"]["status"].pop("label")
    assert payload["restore"]["status"] == {"tone": "neutral"}
    assert payload["restore"]["last_completed_at"] is None
    assert payload["restore"]["drill_age_days"] is None


def test_server_status_does_not_invent_a_restore_age() -> None:
    status = project_server_status(
        _report(),
        protected_backup=None,
        restored_at=None,
        now=NOW,
        release_check=UpdateNotice(space="team", status="unchecked", current_version=None),
    )

    assert status.restore.drill_age_days is None


def test_server_status_names_selected_release_without_source_freshness_claim() -> None:
    status = project_server_status(
        _report(source_state="aligned"),
        protected_backup=None,
        restored_at=None,
        now=NOW,
        release_check=UpdateNotice(space="team", status="unchecked", current_version=None),
    )
    assert status.releases.current_release_commit == COMMIT
    assert status.releases.update_available is False
