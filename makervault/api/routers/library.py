"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import audit
import seams
from auth import AuthContext
from permissions import require_admin, require_read
from schemas import LibraryScanStatusOut

router = APIRouter()


@router.get("/library/scan", response_model=LibraryScanStatusOut)
def library_scan_status(_: Optional[AuthContext] = Depends(require_read)):
    return seams.scan_status()


@router.post("/library/scan", response_model=LibraryScanStatusOut, status_code=202)
def library_scan_start(request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not seams.start_scan():
        raise HTTPException(status_code=409, detail="A library scan is already running")
    # The scan has no DB row to join: fail-loud, and the log line explains why a
    # request that started a scan returned an error.
    audit.record(audit.Event(audit.LIBRARY_SCAN_START, "library"), ctx=audit.context_for(request, context))
    return seams.scan_status()
