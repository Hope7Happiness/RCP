"""Imported provider history and explicitly admitted local Codex continuation."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from rcp.api.dependencies import (
    get_attachment_store,
    get_background_tasks,
    get_catalog,
    get_identity_access,
    get_result_view_keep_locks,
    get_store,
    require_project_membership,
    require_project_write_admission,
)
from rcp.api.identity import IdentityAccess
from rcp.api.tasks import _agent_task_response, _start_agent_task, _validated_task_request
from rcp.attachments import ChatAttachmentStore
from rcp.background import BackgroundAgentTasks
from rcp.keyed_locks import KeyedLocks
from rcp.limits import PROVIDER_HISTORY_PAGE_LIMIT
from rcp.projects import ProjectCatalog
from rcp.provider_history import (
    codex_history_source_size,
    read_codex_history,
    reprove_codex_history,
)
from rcp.storage import AppStore

router = APIRouter(dependencies=[Depends(require_project_membership)])
CatalogDependency = Annotated[ProjectCatalog, Depends(get_catalog)]
StoreDependency = Annotated[AppStore, Depends(get_store)]
IdentityDependency = Annotated[IdentityAccess, Depends(get_identity_access)]
AttachmentStoreDependency = Annotated[ChatAttachmentStore, Depends(get_attachment_store)]
BackgroundTasksDependency = Annotated[BackgroundAgentTasks, Depends(get_background_tasks)]
ResultViewKeepLocksDependency = Annotated[KeyedLocks, Depends(get_result_view_keep_locks)]
_continuation_dispatch_locks = KeyedLocks()


class CodexHistoryImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


class CodexContinuationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    mode: Literal["discuss", "work"]


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
        else record["message_count"],
        "continued_chat_id": record.get("continued_chat_id"),
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
    offset: int | None = Query(default=None, ge=0),
    limit: int = Query(default=PROVIDER_HISTORY_PAGE_LIMIT, ge=1, le=PROVIDER_HISTORY_PAGE_LIMIT),
    chat_id: str | None = Query(default=None),
) -> dict[str, Any]:
    project_id = catalog.resolve_project_id(project_id)
    record = store.provider_history(project_id, "codex", session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Imported Codex session not found")
    claim = store.codex_continuation(session_id)
    if chat_id is not None:
        if claim is None or claim["project_id"] != project_id or claim["chat_id"] != chat_id:
            raise HTTPException(status_code=404, detail="Imported Codex chat binding not found")
        try:
            context = read_codex_history(
                catalog.open(project_id).manifest, session_id, prefix_bytes=claim["source_bytes"]
            )
            for key in (
                "source_path_sha256",
                "source_sha256",
                "source_bytes",
                "source_cwd",
                "repository_alias",
            ):
                if context[key] != claim[key]:
                    raise ValueError("The imported Codex context changed source identity")
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record = {**context, "imported_at": record["imported_at"]}
        if offset is None:
            offset = max(0, len(record["messages"]) - limit)
    record["continued_chat_id"] = (
        claim["chat_id"] if claim is not None and claim["project_id"] == project_id else None
    )
    offset = offset or 0
    return _summary(record) | {
        "offset": offset,
        "limit": limit,
        "messages": record["messages"][offset : offset + limit],
    }


@router.get("/api/projects/{project_id}/provider-history/codex/{session_id}/source-status")
def codex_history_source_status(
    project_id: str,
    session_id: str,
    *,
    catalog: CatalogDependency,
    store: StoreDependency,
) -> dict[str, object]:
    """Observe appended native bytes without rereading the full transcript."""

    project_id = catalog.resolve_project_id(project_id)
    record = store.provider_history(project_id, "codex", session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Imported Codex session not found")
    service = catalog.open(project_id)
    if service.history.workspace.remote:
        raise HTTPException(status_code=409, detail="Codex history source is not local")
    try:
        size = codex_history_source_size(service.manifest, record)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"source_bytes": size, "imported_bytes": record["source_bytes"]}


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
        saved = store.save_provider_history(
            project_id, **{key: value for key, value in history.items() if key != "source_cwd"}
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    claim = store.codex_continuation(body.session_id)
    saved["continued_chat_id"] = (
        claim["chat_id"] if claim is not None and claim["project_id"] == project_id else None
    )
    return _summary(saved)


@router.post(
    "/api/projects/{project_id}/provider-history/codex/{session_id}/continue",
    status_code=202,
    dependencies=[Depends(require_project_write_admission)],
)
def continue_codex_history(
    project_id: str,
    session_id: str,
    body: CodexContinuationBody,
    http_request: Request,
    *,
    catalog: CatalogDependency,
    store: StoreDependency,
    identity_access: IdentityDependency,
    attachment_store: AttachmentStoreDependency,
    background_tasks: BackgroundTasksDependency,
    result_view_keep_locks: ResultViewKeepLocksDependency,
) -> dict[str, object]:
    """Admit the first RCP-owned turn of one imported Codex native session."""

    identity_access.require_patch_capable_identity(http_request)
    if store.space_kind != "personal":
        raise HTTPException(status_code=409, detail="Codex continuation requires a personal space")
    project_id = catalog.resolve_project_id(project_id)
    service = catalog.open(project_id)
    if service.history.workspace.remote:
        raise HTTPException(
            status_code=409, detail="Codex continuation requires local project state"
        )
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="A Codex continuation message cannot be blank")
    try:
        canonical = str(uuid.UUID(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="session_id must be a canonical UUID") from exc
    if canonical != session_id:
        raise HTTPException(status_code=422, detail="session_id must be a canonical UUID")
    imported = store.provider_history(project_id, "codex", session_id)
    if imported is None:
        raise HTTPException(status_code=404, detail="Imported Codex session not found")
    message_sha256 = hashlib.sha256(body.message.encode("utf-8")).hexdigest()
    with _continuation_dispatch_locks(f"{store.path}:{session_id}"):
        claimed = store.codex_continuation(session_id)
        if claimed is not None:
            if (
                claimed["project_id"] != project_id
                or claimed["initial_mode"] != body.mode
                or claimed["first_message_sha256"] != message_sha256
            ):
                raise HTTPException(
                    status_code=409,
                    detail="This Codex session already has a different RCP continuation",
                )
            task = store.agent_task(claimed["first_operation_id"])
            if task is not None:
                if task.project_id != project_id or not task.visible:
                    raise HTTPException(status_code=409, detail="Continuation task is unavailable")
                return {
                    "chat_id": claimed["chat_id"],
                    "task": _agent_task_response(store, task, background_tasks),
                }
        profile = service.resolve_agent_profile("project_chat")
        if profile.provider != "codex" or profile.runtime != "herdr-native":
            raise HTTPException(
                status_code=409,
                detail="Project chat must use Codex with the Herdr native runtime",
            )
        machine = service.manifest.machine_map[profile.run_on]
        if machine.host:
            raise HTTPException(
                status_code=409, detail="Codex continuation requires a local runtime"
            )
        try:
            current = reprove_codex_history(service.manifest, imported)
            if claimed is not None:
                original = reprove_codex_history(
                    service.manifest,
                    {
                        "session_id": session_id,
                        "source_path_sha256": claimed["source_path_sha256"],
                        "source_sha256": claimed["source_sha256"],
                        "source_bytes": claimed["source_bytes"],
                        "repository_alias": claimed["repository_alias"],
                    },
                )
                if original["source_cwd"] != claimed["source_cwd"]:
                    raise ValueError("The original Codex session working directory changed")
            if current["repository_alias"] not in (
                service.history.state().project_truth_scope or service.manifest.project.truth_scope
            ):
                raise ValueError("The imported repository is outside project truth scope")
            from rcp.agents.herdr_bridge import require_codex_session_quiescent

            require_codex_session_quiescent(session_id, Path(current["source_cwd"]))
            chat_id = claimed["chat_id"] if claimed is not None else str(uuid.uuid4())
            operation_id = (
                claimed["first_operation_id"] if claimed is not None else str(uuid.uuid4())
            )
            request_body: dict[str, object] = {
                "chat_id": chat_id,
                "session_id": session_id,
                "message": body.message,
                "mode": body.mode,
                "run_truth_scope": [current["repository_alias"]],
            }
            resolved = _validated_task_request(service, "project_chat", request_body)
            if resolved.provider != "codex" or resolved.run_on != profile.run_on:
                raise ValueError("Codex continuation resolved to a different project profile")
            claimed = store.claim_codex_continuation(
                project_id=project_id,
                session_id=session_id,
                chat_id=chat_id,
                first_operation_id=operation_id,
                source_path_sha256=imported["source_path_sha256"],
                source_sha256=(
                    claimed["source_sha256"] if claimed is not None else imported["source_sha256"]
                ),
                source_bytes=(
                    claimed["source_bytes"] if claimed is not None else imported["source_bytes"]
                ),
                source_cwd=current["source_cwd"],
                repository_alias=current["repository_alias"],
                execution_machine=profile.run_on,
                initial_mode=body.mode,
                first_message_sha256=message_sha256,
            )
            task = _start_agent_task(
                project_id,
                "project_chat",
                request_body,
                http_request,
                catalog=catalog,
                store=store,
                identity_access=identity_access,
                attachment_store=attachment_store,
                background_tasks=background_tasks,
                result_view_keep_locks=result_view_keep_locks,
                branch_id=None,
                operation_id_override=claimed["first_operation_id"],
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"chat_id": claimed["chat_id"], "task": task}
