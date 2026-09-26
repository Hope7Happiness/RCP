from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from rcp.api.dependencies import (
    ServerStatusComposition,
    get_release_check,
    get_server_status_composition,
    get_store,
)
from rcp.release_check import ReleaseCheck, UpdateNotice
from rcp.server_ops.backup import BackupArchiveReceipt
from rcp.server_ops.doctor import ServerDoctorReport
from rcp.storage import AppStore

router = APIRouter()

ServerStatusCompositionDependency = Annotated[
    ServerStatusComposition,
    Depends(get_server_status_composition),
]
StoreDependency = Annotated[AppStore, Depends(get_store)]

StatusTone = Literal["good", "attention", "bad", "neutral"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ServerStatusSummary(_StrictModel):
    label: str = Field(min_length=1, max_length=120)
    tone: StatusTone


class ServerReleaseStatus(_StrictModel):
    status: ServerStatusSummary
    managed_source_commit: str | None
    current_release_commit: str | None
    running_commit: str | None
    upstream_commit: str | None
    candidate_commit: str | None
    update_available: bool
    last_update_failure: str | None
    command: Literal["rcp server update"] = "rcp server update"


class ServerBackupStatus(_StrictModel):
    status: ServerStatusSummary
    configured: bool
    destination: str | None
    schedule: str | None
    retention: int | None
    last_attempt_at: datetime | None
    last_protected_at: datetime | None
    captured_bytes: int | None
    protected_projects: int | None
    uncaptured_projects: int | None
    last_failure: str | None
    configure_command: Literal["rcp server backup configure"] = "rcp server backup configure"
    run_command: Literal["rcp server backup run"] = "rcp server backup run"


class ServerRestoreStatus(_StrictModel):
    status: ServerStatusSummary
    last_completed_at: datetime | None
    drill_age_days: int | None = Field(default=None, ge=0)
    command: Literal["rcp server restore"] = "rcp server restore"


class ServerExecutionReadiness(_StrictModel):
    machine: ServerStatusSummary
    provider_checks: ServerStatusSummary
    dependency_versions: str
    provider_command: Literal["rcp server provider check"] = "rcp server provider check"


class ServerStatusResponse(_StrictModel):
    overall: ServerStatusSummary
    release_check: UpdateNotice
    releases: ServerReleaseStatus
    backup: ServerBackupStatus
    restore: ServerRestoreStatus
    execution: ServerExecutionReadiness
    problems: tuple[str, ...]


@router.get("/api/server-status", response_model=ServerStatusResponse)
def server_status(
    *,
    composition: ServerStatusCompositionDependency,
    store: StoreDependency,
    release_check: Annotated[ReleaseCheck, Depends(get_release_check)],
) -> ServerStatusResponse:
    if store.space_kind != "team":
        raise HTTPException(status_code=404, detail="Server status is available in a team space.")
    try:
        report = composition.doctor_reader()
        protected_backup = composition.protected_backup_reader(report)
        restored_at = composition.restore_completed_at_reader()
        now = composition.clock()
        return project_server_status(
            report,
            protected_backup=protected_backup,
            restored_at=restored_at,
            now=now,
            release_check=release_check.snapshot(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=("Server status could not be read safely. Run rcp server doctor on the server."),
        ) from exc


def project_server_status(
    report: ServerDoctorReport,
    *,
    protected_backup: BackupArchiveReceipt | None,
    restored_at: datetime | None,
    now: datetime,
    release_check: UpdateNotice,
) -> ServerStatusResponse:
    if now.utcoffset() is None:
        raise ValueError("server status clock must include a UTC offset")
    restore = _restore_status(restored_at, now)
    return ServerStatusResponse(
        overall=_overall_status(report, release_check),
        release_check=release_check,
        releases=ServerReleaseStatus(
            status=_release_status(report, release_check),
            managed_source_commit=report.managed_main_head,
            current_release_commit=report.current_commit,
            running_commit=report.running_commit,
            upstream_commit=report.upstream_head,
            candidate_commit=report.candidate_commit,
            update_available=release_check.status == "update_available",
            last_update_failure=report.update_failure,
        ),
        backup=ServerBackupStatus(
            status=_backup_status(report),
            configured=report.backup_status != "not_configured",
            destination=report.backup_destination,
            schedule=report.backup_schedule,
            retention=report.backup_retention,
            last_attempt_at=report.last_backup_at,
            last_protected_at=(
                protected_backup.protected_at if protected_backup is not None else None
            ),
            captured_bytes=(
                protected_backup.captured_bytes if protected_backup is not None else None
            ),
            protected_projects=(
                protected_backup.protected_project_count if protected_backup is not None else None
            ),
            uncaptured_projects=(
                protected_backup.uncaptured_project_count if protected_backup is not None else None
            ),
            last_failure=report.last_backup_failure,
        ),
        restore=restore,
        execution=ServerExecutionReadiness(
            machine=ServerStatusSummary(
                label=(
                    "Server tools are ready"
                    if report.dependencies_ready
                    else "Server tools need attention"
                ),
                tone="good" if report.dependencies_ready else "bad",
            ),
            provider_checks=ServerStatusSummary(
                label=(
                    "Provider checks are available"
                    if report.provider_check_status == "available"
                    else "Provider checks are unavailable"
                ),
                tone="good" if report.provider_check_status == "available" else "bad",
            ),
            dependency_versions=report.dependency_versions,
        ),
        problems=report.problems,
    )


def _overall_status(report: ServerDoctorReport, release_check: UpdateNotice) -> ServerStatusSummary:
    labels = {
        "healthy": "Server is healthy",
        "update_available": "Update is available",
        "candidate_pending": "Built update is waiting",
        "restart_pending": "Server restart is waiting",
        "problems": "Server needs attention",
    }
    tones: dict[str, StatusTone] = {
        "healthy": "good",
        "update_available": "attention",
        "candidate_pending": "attention",
        "restart_pending": "attention",
        "problems": "bad",
    }
    state = report.overall_state
    if state in {"healthy", "update_available"}:
        state = "update_available" if release_check.status == "update_available" else "healthy"
    return ServerStatusSummary(label=labels[state], tone=tones[state])


def _release_status(report: ServerDoctorReport, release_check: UpdateNotice) -> ServerStatusSummary:
    if report.update_failure is not None:
        return ServerStatusSummary(label="Last update needs attention", tone="bad")
    if report.release_state == "candidate_pending":
        return ServerStatusSummary(label="Built update is waiting", tone="attention")
    if report.release_state == "restart_pending":
        return ServerStatusSummary(label="Restart is waiting", tone="attention")
    if report.release_state != "aligned" or report.source_state in {
        "local_ahead",
        "diverged",
        "unavailable",
    }:
        return ServerStatusSummary(label="Update is not ready", tone="bad")
    if release_check.status == "update_available":
        return ServerStatusSummary(label="Update is available", tone="attention")
    return ServerStatusSummary(label="Running selected release", tone="good")


def _backup_status(report: ServerDoctorReport) -> ServerStatusSummary:
    labels: dict[str, tuple[str, StatusTone]] = {
        "not_configured": ("Backups are not configured", "attention"),
        "never_run": ("Backup has not run", "attention"),
        "protected": ("Last backup is protected", "good"),
        "partial": ("Last backup is partial", "bad"),
        "failure": ("Last backup failed", "bad"),
        "unavailable": ("Backup status is unavailable", "bad"),
    }
    label, tone = labels[report.backup_status]
    return ServerStatusSummary(label=label, tone=tone)


def _restore_status(restored_at: datetime | None, now: datetime) -> ServerRestoreStatus:
    if restored_at is None:
        return ServerRestoreStatus(
            status=ServerStatusSummary(label="Restore history is unavailable", tone="neutral"),
            last_completed_at=None,
            drill_age_days=None,
        )
    if restored_at.utcoffset() is None or restored_at > now:
        raise ValueError("completed restore time is invalid")
    age_days = (now - restored_at).days
    if age_days == 0:
        label = "Restore completed today"
    elif age_days == 1:
        label = "Restore completed 1 day ago"
    else:
        label = f"Restore completed {age_days} days ago"
    return ServerRestoreStatus(
        status=ServerStatusSummary(label=label, tone="good"),
        last_completed_at=restored_at,
        drill_age_days=age_days,
    )


__all__ = [
    "ServerStatusResponse",
    "project_server_status",
    "router",
    "server_status",
]
