from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from .helpers import create_named_app

RouteEntry = tuple[tuple[str, ...], str]


# This is the structural safety net for route extraction. Keep this literal
# unchanged when a handler moves: it records the route surface, not ownership.
_FROZEN_ROUTE_INVENTORY: tuple[RouteEntry, ...] = (
    (("GET", "HEAD"), "/openapi.json"),
    (("GET", "HEAD"), "/docs"),
    (("GET", "HEAD"), "/docs/oauth2-redirect"),
    (("GET", "HEAD"), "/redoc"),
    (("GET",), "/api/health"),
    (("GET",), "/api/update-notice"),
    (("GET",), "/api/server-status"),
    (("GET",), "/api/identity"),
    (("PATCH",), "/api/identity"),
    (("POST",), "/api/team/enroll"),
    (("POST",), "/api/team/session/exchange"),
    (("POST",), "/api/team/session/logout"),
    (("GET",), "/api/team/sessions"),
    (("POST",), "/api/team/sessions/{session_id}/revoke"),
    (("POST",), "/api/team/devices/pairings"),
    (("GET",), "/api/team/devices/pairings/{pairing_id}"),
    (("POST",), "/api/team/devices/pair"),
    (("GET",), "/api/team/invitations"),
    (("POST",), "/api/team/invitations"),
    (("POST",), "/api/team/invitations/{invitation_id}/revoke"),
    (("POST",), "/api/team/credential/rotate"),
    (("POST",), "/api/team/credential/revoke"),
    (("GET",), "/api/team/space"),
    (("PATCH",), "/api/team/space"),
    (("GET",), "/api/projects"),
    (("GET",), "/api/episodes"),
    (("GET",), "/api/space/runs"),
    (("GET",), "/api/space/users"),
    (("GET",), "/api/project-invitations"),
    (("POST",), "/api/project-invitations/{invitation_id}/{response}"),
    (("GET",), "/api/providers"),
    (("GET",), "/api/providers/logins"),
    (("POST",), "/api/providers/{provider}/logins/verify"),
    (("POST",), "/api/providers/{provider}/logins/sign-in"),
    (("GET",), "/api/providers/{provider}/logins/sign-in/{login_id}"),
    (("POST",), "/api/providers/{provider}/logins/sign-in/{login_id}/cancel"),
    (("POST",), "/api/providers/{provider}/logins/token"),
    (("POST",), "/api/providers/{provider}/logins/sign-out"),
    (("POST",), "/api/projects"),
    (("POST",), "/api/project-setup/preflight"),
    (("POST",), "/api/project-setup/ssh-paths"),
    (("POST",), "/api/project-setup/create"),
    (("POST",), "/api/project-provisioning/requests"),
    (("GET",), "/api/project-provisioning/requests"),
    (("GET",), "/api/project-provisioning/requests/{request_id}"),
    (("POST",), "/api/project-provisioning/requests/{request_id}/cancel"),
    (("POST",), "/api/project-provisioning/requests/{request_id}/complete"),
    (("POST",), "/api/project-transfers/incoming-provisioning-requests"),
    (("GET",), "/api/project-transfers/incoming-provisioning-requests"),
    (
        ("GET",),
        "/api/project-transfers/incoming-provisioning-requests/{request_id}",
    ),
    (("POST",), "/api/project-transfers/source-requests"),
    (("POST",), "/api/project-transfers/target-requests"),
    (("GET",), "/api/project-transfers/requests"),
    (("GET",), "/api/project-transfers/requests/{request_id}"),
    (("POST",), "/api/project-transfers/source-requests/{request_id}/link"),
    (("POST",), "/api/project-transfers/target-requests/{request_id}/admit"),
    (("POST",), "/api/project-transfers/source-requests/{request_id}/target-admission"),
    (("GET",), "/api/project-transfers/source-requests/{request_id}/release-boundary"),
    (("POST",), "/api/project-transfers/source-requests/{request_id}/release"),
    (("POST",), "/api/project-transfers/target-requests/{request_id}/restore-reentry"),
    (("POST",), "/api/project-transfers/target-requests/{request_id}/source-release"),
    (("POST",), "/api/project-transfers/requests/{request_id}/archive"),
    (
        ("GET",),
        "/api/native/project-transfers/source-requests/{request_id}/archive",
    ),
    (
        ("POST",),
        "/api/native/project-transfers/target-requests/{request_id}/cleanup-acknowledgment",
    ),
    (
        ("POST",),
        "/api/native/project-transfers/source-requests/{request_id}/target-activation-proof",
    ),
    (
        ("GET",),
        "/api/native/project-transfers/target-requests/{request_id}/activation-proof",
    ),
    (("DELETE",), "/api/projects/{project_id}/caches/all"),
    (("GET",), "/api/projects/{project_id}/experiment-episodes"),
    (("GET",), "/api/skills/{kind}/{package_id}"),
    (("DELETE",), "/api/projects/{project_id}"),
    (("GET",), "/api/projects/{project_id}"),
    (("GET",), "/api/projects/{project_id}/members"),
    (("POST",), "/api/projects/{project_id}/invitations"),
    (("POST",), "/api/projects/{project_id}/leave"),
    (("GET",), "/api/projects/{project_id}/cached"),
    (("GET",), "/api/projects/{project_id}/cached/revision"),
    (("GET",), "/api/projects/{project_id}/readiness"),
    (("GET",), "/api/projects/{project_id}/graph"),
    (("GET",), "/api/projects/{project_id}/graph/changes"),
    (("GET",), "/api/projects/{project_id}/revision"),
    (("HEAD",), "/api/projects/{project_id}/repositories/files/preview"),
    (("GET",), "/api/projects/{project_id}/repositories/files/preview"),
    (("PUT",), "/api/projects/{project_id}/settings"),
    (("POST",), "/api/projects/{project_id}/machines/{machine_alias}/providers/{provider}/resolve"),
    (("POST",), "/api/projects/{project_id}/machines/{machine_alias}/compute/check"),
    (("GET",), "/api/projects/{project_id}/chat-display"),
    (("POST",), "/api/projects/{project_id}/chats/{chat_id}/archive"),
    (("POST",), "/api/projects/{project_id}/chats/{chat_id}/title"),
    (("GET",), "/api/projects/{project_id}/history"),
    (("GET",), "/api/projects/{project_id}/history/summaries"),
    (("GET",), "/api/projects/{project_id}/sources"),
    (("GET",), "/api/projects/{project_id}/graph-edit-options"),
    (("POST",), "/api/projects/{project_id}/sync"),
    (("GET",), "/api/projects/{project_id}/transition-manifest"),
    (("POST",), "/api/projects/{project_id}/sync/preview"),
    (("DELETE",), "/api/projects/{project_id}/caches"),
    (("POST",), "/api/projects/{project_id}/chats/{chat_id}/attachments"),
    (("DELETE",), "/api/projects/{project_id}/chats/{chat_id}/attachments/{attachment_id}"),
    (("POST",), "/api/projects/{project_id}/tasks/{kind}"),
    (("POST",), "/api/projects/{project_id}/experiments/{node_id:path}/run"),
    (("GET",), "/api/projects/{project_id}/tasks"),
    (("GET",), "/api/projects/{project_id}/usage"),
    (("GET",), "/api/projects/{project_id}/watchers"),
    (("POST",), "/api/projects/{project_id}/watchers/{watcher_id}/check"),
    (("POST",), "/api/projects/{project_id}/watchers/{watcher_id}/stop"),
    (("POST",), "/api/projects/{project_id}/watchers/{watcher_id}/cancel"),
    (("POST",), "/api/projects/{project_id}/experiments/{node_id:path}/watchers/stop"),
    (("POST",), "/api/projects/{project_id}/experiments/{node_id:path}/stop"),
    (("GET",), "/api/projects/{project_id}/chats"),
    (("GET",), "/api/projects/{project_id}/chats/{chat_id}"),
    (("GET",), "/api/projects/{project_id}/chats/{chat_id}/worktree"),
    (("DELETE",), "/api/projects/{project_id}/chats/{chat_id}/worktree"),
    (("GET",), "/api/projects/{project_id}/episodes"),
    (("POST",), "/api/projects/{project_id}/episodes"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/archive"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/stop"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/merge"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/continue"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/messages"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/messages"),
    (("HEAD",), "/api/projects/{project_id}/episodes/{episode_id}/report/content"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/report/content"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/timeline"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/timeline/text/{text_ref}"),
    (("POST",), "/api/projects/{project_id}/episodes/{episode_id}/report/save"),
    (("HEAD",), "/api/projects/{project_id}/episodes/{episode_id}/report/preview"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/report/preview"),
    (("GET",), "/api/projects/{project_id}/episodes/{episode_id}/report/viewer"),
    (("GET",), "/api/projects/{project_id}/result-views"),
    (("GET",), "/api/projects/{project_id}/artifacts"),
    (("HEAD",), "/api/projects/{project_id}/result-views/{view_id}/preview"),
    (("GET",), "/api/projects/{project_id}/result-views/{view_id}/preview"),
    (("POST",), "/api/projects/{project_id}/result-views/{view_id}/keep"),
    (("GET",), "/api/projects/{project_id}/tasks/{operation_id}"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/steer"),
    (("HEAD",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/content"),
    (("GET",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/content"),
    (("HEAD",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/preview"),
    (("GET",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/preview"),
    (("HEAD",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/download"),
    (("GET",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/download"),
    (("GET",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/viewer"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/artifacts/{artifact_id}/keep"),
    (("HEAD",), "/api/projects/{project_id}/artifact-revisions/{candidate_id}/content"),
    (("GET",), "/api/projects/{project_id}/artifact-revisions/{candidate_id}/content"),
    (("POST",), "/api/projects/{project_id}/artifact-revisions/{candidate_id}/accept"),
    (("POST",), "/api/projects/{project_id}/artifact-revisions/{candidate_id}/reject"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/pause"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/resume"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/repair-graph-update"),
    (("POST",), "/api/projects/{project_id}/tasks/{operation_id}/retry"),
    (("GET",), "/api/projects/{project_id}/paper"),
    (("POST",), "/api/projects/{project_id}/paper/create"),
    (("PUT",), "/api/projects/{project_id}/paper"),
    (("GET",), "/api/projects/{project_id}/paper/sessions"),
    (("DELETE",), "/api/projects/{project_id}/terminals/{session_id}"),
    (("GET",), "/api/projects/{project_id}/terminals"),
    (("GET",), "/api/projects/{project_id}/terminals/repositories"),
    (("POST",), "/api/projects/{project_id}/terminals"),
    (("POST",), "/api/projects/{project_id}/terminals/probe"),
)


def _walk_routes(routes: Iterable[object]) -> Iterable[object]:
    """Yield actual routes, including routes nested by ``include_router``."""

    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk_routes(inner.routes)
        elif hasattr(route, "methods"):
            yield route


def _route_entry(route: Any) -> RouteEntry:
    methods = tuple(sorted(route.methods))
    return methods, route.path


@pytest.fixture
def route_app(manifest, tmp_path: Path) -> FastAPI:
    return create_named_app(str(manifest.path), data_dir=tmp_path / "route-inventory")


def test_frozen_route_inventory(route_app: FastAPI) -> None:
    routes = list(_walk_routes(route_app.routes))
    entries = tuple(_route_entry(route) for route in routes)

    assert len(entries) == 160
    assert len(_FROZEN_ROUTE_INVENTORY) == 160
    # Registration order is not part of the route contract; membership is.
    assert frozenset(entries) == frozenset(_FROZEN_ROUTE_INVENTORY)

    # The count makes the application/generated split explicit. FastAPI's
    # built-in routes are ordinary Starlette Route objects, while application
    # routes are APIRoute objects (including those nested in the router).
    assert sum(isinstance(route, APIRoute) for route in routes) == 156
    assert len(routes) - sum(isinstance(route, APIRoute) for route in routes) == 4
