"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from pathlib import Path
from typing import Optional
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, HTTPException

import seams
from auth import AuthContext
from file_utils import build_import_filename, mime_from_content_type
from permissions import require_write
from routers.presenters import to_out
from schemas import (
    AssetOut,
    ImportInspectOut,
    ImportRequest,
    ImportZipEntriesOut,
    ImportZipEntriesRequest,
    ImportZipExtractRequest,
    ImportZipResult,
)
from zip_service import extract_zip_entries_to_assets, list_zip_entries

router = APIRouter()


@router.post("/import", response_model=AssetOut)
def import_from_link(body: ImportRequest, _: Optional[AuthContext] = Depends(require_write)):
    url = seams.normalize_import_url(body.url)
    asset = seams.import_asset_from_url(url, body)
    return to_out(asset)


@router.post("/import/inspect", response_model=ImportInspectOut)
def inspect_import_link(body: ImportRequest, _: Optional[AuthContext] = Depends(require_write)):
    url = seams.normalize_import_url(body.url)
    resp, final_url = seams.open_import_response(url, body)
    with resp:
        filename = build_import_filename(final_url, resp.headers, body.filename)
        mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
    is_zip = Path(filename).suffix.lower() == ".zip"
    return ImportInspectOut(filename=filename, mime=mime, is_zip=is_zip)


@router.post("/import/zip/entries", response_model=ImportZipEntriesOut)
def list_import_zip_entries(body: ImportZipEntriesRequest, _: Optional[AuthContext] = Depends(require_write)):
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
def import_zip_entries(body: ImportZipExtractRequest, _: Optional[AuthContext] = Depends(require_write)):
    url = seams.normalize_import_url(body.url)
    tmp_path, filename, _ = seams.download_import_to_temp(url, body)
    try:
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            assets, failed = extract_zip_entries_to_assets(tmp_path, body.entries, body)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
        return ImportZipResult(assets=[to_out(asset) for asset in assets], failed=failed)
    finally:
        tmp_path.unlink(missing_ok=True)
