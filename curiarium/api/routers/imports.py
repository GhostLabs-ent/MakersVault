"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from pathlib import Path
from typing import Optional
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, HTTPException, Request

import asset_service
import seams
from auth import AuthContext
from file_utils import build_import_filename, mime_from_content_type
from import_policy import refuse_paid_or_gated
from permissions import require_contribute
from project_import import import_into_project
from routers.presenters import import_project_to_out, to_out
from schemas import (
    AssetOut,
    ImportInspectOut,
    ImportProjectOut,
    ImportProjectRequest,
    ImportRequest,
    ImportZipEntriesOut,
    ImportZipEntriesRequest,
    ImportZipExtractRequest,
    ImportZipResult,
)
from zip_service import extract_zip_entries_to_assets, list_zip_entries

router = APIRouter()


@router.post("/import", response_model=AssetOut)
def import_from_link(
    request: Request,
    body: ImportRequest,
    context: Optional[AuthContext] = Depends(require_contribute),
):
    # Before normalize_import_url: normalization resolves DNS, so the refusal must
    # precede it to keep a paid/gated URL off the network entirely.
    refuse_paid_or_gated(body.url)
    url = seams.normalize_import_url(body.url)
    origin = asset_service.AssetOrigin.for_principal(request, context, "link-import")
    asset = seams.import_asset_from_url(url, body, origin=origin)
    return to_out(asset)


@router.post("/import/project", response_model=ImportProjectOut)
def import_link_into_project(
    request: Request,
    body: ImportProjectRequest,
    context: Optional[AuthContext] = Depends(require_contribute),
):
    # Before normalize_import_url: normalization resolves DNS, so the refusal must
    # precede it to keep a paid/gated URL off the network entirely.
    refuse_paid_or_gated(body.url)
    url = seams.normalize_import_url(body.url)
    origin = asset_service.AssetOrigin.for_principal(request, context, "link-import")
    return import_project_to_out(import_into_project(url, body, origin=origin))


@router.post("/import/inspect", response_model=ImportInspectOut)
def inspect_import_link(body: ImportRequest, _: Optional[AuthContext] = Depends(require_contribute)):
    refuse_paid_or_gated(body.url)
    url = seams.normalize_import_url(body.url)
    resp, final_url = seams.open_import_response(url, body)
    with resp:
        filename = build_import_filename(final_url, resp.headers, body.filename)
        mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
    is_zip = Path(filename).suffix.lower() == ".zip"
    return ImportInspectOut(filename=filename, mime=mime, is_zip=is_zip)


@router.post("/import/zip/entries", response_model=ImportZipEntriesOut)
def list_import_zip_entries(body: ImportZipEntriesRequest, _: Optional[AuthContext] = Depends(require_contribute)):
    refuse_paid_or_gated(body.url)
    url = seams.normalize_import_url(body.url)
    tmp_path, filename, _ = seams.download_import_to_temp(url, body)
    try:
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            entries = list_zip_entries(tmp_path)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
        if not entries:
            raise HTTPException(status_code=400, detail="No files found in zip")
        return ImportZipEntriesOut(filename=filename, entries=entries)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/import/zip", response_model=ImportZipResult)
def import_zip_entries(
    request: Request,
    body: ImportZipExtractRequest,
    context: Optional[AuthContext] = Depends(require_contribute),
):
    refuse_paid_or_gated(body.url)
    url = seams.normalize_import_url(body.url)
    origin = asset_service.AssetOrigin.for_principal(request, context, "zip-import")
    tmp_path, filename, _ = seams.download_import_to_temp(url, body)
    try:
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            assets, failed = extract_zip_entries_to_assets(tmp_path, body.entries, body, origin=origin)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
        return ImportZipResult(assets=[to_out(asset) for asset in assets], failed=failed)
    finally:
        tmp_path.unlink(missing_ok=True)
