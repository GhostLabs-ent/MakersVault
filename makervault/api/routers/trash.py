"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

import audit
import trash_service
from auth import AuthContext
from permissions import require_admin, require_read
from schemas import TrashEntryOut, TrashListOut, TrashPurgeOut

router = APIRouter()


# Trash endpoints -----------------------------------------------


@router.get("/trash", response_model=TrashListOut)
def list_trash(_: Optional[AuthContext] = Depends(require_read)):
    entries = trash_service.list_entries()
    return TrashListOut(
        entries=[TrashEntryOut(**entry) for entry in entries],
        total_size=sum(entry["size"] for entry in entries),
    )


@router.post("/trash/purge", response_model=TrashPurgeOut)
def purge_trash(
    request: Request,
    older_than_days: Optional[int] = Query(None, ge=0),
    context: Optional[AuthContext] = Depends(require_admin),
):
    result = trash_service.purge(older_than_days)
    # The bytes are already gone and there is no row to roll back: fail-loud.
    audit.record(audit.Event(audit.TRASH_PURGE, "trash", dict(result)), ctx=audit.context_for(request, context))
    return TrashPurgeOut(**result)
