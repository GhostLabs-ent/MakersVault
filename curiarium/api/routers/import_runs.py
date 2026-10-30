"""Read-only mounted-import run history.

The rows are written by ``mount_import.scan_mount_imports()``; this module only
presents them. A run that is still walking gets its live counters and errors
from ``import_runs.active_state`` instead of the row, which is written only when
the run finishes.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import import_runs
from auth import AuthContext
from library_scan import ScanState
from models import ImportRun
from permissions import require_read
from schemas import ImportRunDetailOut, ImportRunListOut, ImportRunSummaryOut

router = APIRouter()


def _live_state(row: ImportRun) -> Optional[ScanState]:
    if row.status != import_runs.RUNNING:
        return None
    return import_runs.active_state(row.id)


def _run_values(row: ImportRun, state: Optional[ScanState]) -> tuple[int, int, int, int, list[str]]:
    if state is None:
        return (
            row.registered,
            row.known,
            row.ignored,
            row.failed,
            json.loads(row.errors_json or "[]"),
        )
    return (state.registered, state.known, state.ignored, state.failed, list(state.errors))


def run_to_summary(row: ImportRun, state: Optional[ScanState] = None) -> ImportRunSummaryOut:
    registered, known, ignored, failed, _errors = _run_values(row, state)
    return ImportRunSummaryOut(
        id=row.id,
        status=row.status,
        mode=row.mode,
        root=row.root,
        reason=row.reason,
        started_at=row.started_at,
        finished_at=row.finished_at,
        registered=registered,
        known=known,
        ignored=ignored,
        failed=failed,
        rejected=row.rejected,
        discovered=registered + known + ignored + failed,
        skipped=known + ignored,
    )


def run_to_detail(row: ImportRun, state: Optional[ScanState] = None) -> ImportRunDetailOut:
    summary = run_to_summary(row, state)
    _registered, _known, _ignored, _failed, errors = _run_values(row, state)
    return ImportRunDetailOut(**summary.model_dump(), errors=errors)


@router.get("/imports/runs", response_model=ImportRunListOut)
def list_import_runs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    rows, total = import_runs.list_runs(limit=limit, offset=offset)
    runs = [run_to_summary(row, _live_state(row)) for row in rows]
    return ImportRunListOut(runs=runs, total=total, limit=limit, offset=offset)


@router.get("/imports/runs/{run_id}", response_model=ImportRunDetailOut)
def get_import_run(run_id: str, _: Optional[AuthContext] = Depends(require_read)):
    row = import_runs.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Import run not found")
    return run_to_detail(row, _live_state(row))
