from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from rcp.api.dependencies import get_release_check
from rcp.release_check import ReleaseCheck, UpdateNotice

router = APIRouter()


@router.get("/api/update-notice", response_model=UpdateNotice)
def update_notice(
    release_check: Annotated[ReleaseCheck, Depends(get_release_check)],
) -> UpdateNotice:
    return release_check.snapshot()
