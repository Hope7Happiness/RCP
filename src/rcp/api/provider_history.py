"""Read-only display of explicitly imported local provider conversations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from rcp.api.dependencies import (
    get_catalog,
    get_store,
    require_project_membership,
    require_project_write_admission,
)
from rcp.limits import PROVIDER_HISTORY_PAGE_LIMIT
from rcp.projects import ProjectCatalog
from rcp.provider_history import read_codex_history
from rcp.storage import AppStore

router = APIRouter(dependencies=[Depends(require_project_membership)])
CatalogDependency = Annotated[ProjectCatalog, Depends(get_catalog)]
StoreDependency = Annotated[AppStore, Depends(get_store)]


class CodexHistoryImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "provider",
            "session_id",
            "source_sha256",
            "source_bytes",
            "repository_alias",
            "first_timestamp",
            "last_timestamp",
            "imported_at",
        )
    } | {
        "message_count": len(record["messages"])
        if "messages" in record
        else record["message_count"]
    }


@router.get("/api/projects/{project_id}/provider-history")
def provider_histories(
    project_id: str, *, catalog: CatalogDependency, store: StoreDependency
) -> list[dict[str, Any]]:
    project_id = catalog.resolve_project_id(project_id)
    return [_summary(item) for item in store.provider_histories(project_id)]


@router.get("/api/projects/{project_id}/provider-history/codex/{session_id}")
def provider_history(
    project_id: str,
    session_id: str,
    *,
    catalog: CatalogDependency,
    store: StoreDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=PROVIDER_HISTORY_PAGE_LIMIT, ge=1, le=PROVIDER_HISTORY_PAGE_LIMIT),
) -> dict[str, Any]:
    project_id = catalog.resolve_project_id(project_id)
    record = store.provider_history(project_id, "codex", session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Imported Codex session not found")
    return _summary(record) | {
        "offset": offset,
        "limit": limit,
        "messages": record["messages"][offset : offset + limit],
    }


@router.post(
    "/api/projects/{project_id}/provider-history/codex",
    dependencies=[Depends(require_project_write_admission)],
)
def import_codex_history(
    project_id: str,
    body: CodexHistoryImportBody,
    *,
    catalog: CatalogDependency,
    store: StoreDependency,
) -> dict[str, Any]:
    if store.space_kind != "personal":
        raise HTTPException(
            status_code=409, detail="Local Codex history import requires a personal space."
        )
    project_id = catalog.resolve_project_id(project_id)
    service = catalog.open(project_id)
    if service.history.workspace.remote:
        raise HTTPException(
            status_code=409, detail="Local Codex history import requires local project state."
        )
    try:
        history = read_codex_history(service.manifest, body.session_id)
        saved = store.save_provider_history(project_id, **history)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _summary(saved)
