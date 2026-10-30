"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import re
from typing import List, Optional
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlmodel import Session
from starlette.requests import ClientDisconnect

import audit
import auth
import db
import multipart_stream
from asset_file_service import (
    PREVIEW_TEXT_MEDIA_TYPE,
    UNPREVIEWABLE_DETAIL,
    delete_prepared_file,
    delete_supporting_file,
    list_supporting_files,
    managed_asset_file_path,
    preview_media_type,
    rename_supporting_file,
    reorder_supporting_files,
    supporting_file_limits,
)
from asset_service import new_staging_path, resolve_asset_file, save_thumb
from auth import AuthContext
from db import engine
from models import Asset, AssetFile
from permissions import require_file_read, require_read, require_write
from routers.presenters import asset_file_to_out, to_out
from routers.uploads import CLIENT_CLOSED_REQUEST, multipart_form_openapi
from schemas import (
    AssetFileLimitsOut,
    AssetFileOrderUpdate,
    AssetFileOut,
    AssetFileRename,
    AssetOut,
    FileGrantListOut,
    FileGrantOut,
    FileGrantRequest,
)

router = APIRouter()


@router.get("/file/{asset_id}/{name}")
def get_file(asset_id: str, name: str, _: Optional[AuthContext] = Depends(require_file_read)):
    media_type: Optional[str] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if a:
            media_type = a.mime
            p = resolve_asset_file(a)
        else:
            p = None

    if not p or not p.exists():
        raise HTTPException(404)

    return FileResponse(
        p,
        media_type=media_type or "application/octet-stream",
        filename=name,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/asset/{asset_id}/files", response_model=List[AssetFileOut])
def get_supporting_files(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as session:
        if not session.get(Asset, asset_id):
            raise HTTPException(404)
    return [asset_file_to_out(row) for row in list_supporting_files(asset_id)]


@router.get("/asset/{asset_id}/files/limits", response_model=AssetFileLimitsOut)
def get_supporting_file_limits(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    # Declared before `/{file_id}` so "limits" is never read as a file id.
    return supporting_file_limits(asset_id)


@router.put("/asset/{asset_id}/files/order", response_model=List[AssetFileOut])
def reorder_supporting_files_route(
    asset_id: str,
    body: AssetFileOrderUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    rows = reorder_supporting_files(
        asset_id,
        body.file_ids,
        audit_ctx=audit.context_for(request, context),
    )
    return [asset_file_to_out(row) for row in rows]


@router.get("/asset/{asset_id}/files/{file_id}")
def download_supporting_file(
    asset_id: str,
    file_id: str,
    inline: bool = False,
    _: Optional[AuthContext] = Depends(require_file_read),
):
    with Session(engine) as session:
        record = session.get(AssetFile, file_id)
        if not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
        preview_type = preview_media_type(record) if inline else None
    if not path.exists():
        raise HTTPException(404)
    if not inline:
        return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)
    if preview_type is None:
        raise HTTPException(status_code=415, detail=UNPREVIEWABLE_DETAIL)
    # `nosniff` on every inline response; the CSP sandbox is for text only,
    # because it stops Chrome's built-in PDF viewer from rendering at all.
    headers = {"X-Content-Type-Options": "nosniff"}
    if preview_type == PREVIEW_TEXT_MEDIA_TYPE:
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(
        path,
        media_type=preview_type,
        filename=filename,
        content_disposition_type="inline",
        headers=headers,
    )


@router.patch("/asset/{asset_id}/files/{file_id}", response_model=AssetFileOut)
def rename_supporting_file_route(
    asset_id: str,
    file_id: str,
    body: AssetFileRename,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    record = rename_supporting_file(
        asset_id,
        file_id,
        body.filename,
        audit_ctx=audit.context_for(request, context),
    )
    return asset_file_to_out(record)


@router.delete("/asset/{asset_id}/files/{file_id}", response_model=AssetOut)
def remove_supporting_file(
    asset_id: str,
    file_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_supporting_file(asset_id, file_id, audit_ctx=audit.context_for(request, context)))


@router.get("/asset/{asset_id}/prepared-print")
def get_prepared_print(asset_id: str, _: Optional[AuthContext] = Depends(require_file_read)):
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset or not asset.prepared_file_id:
            raise HTTPException(404)
        record = session.get(AssetFile, asset.prepared_file_id)
        if not record or record.asset_id != asset_id or record.role != "prepared":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)


@router.delete("/asset/{asset_id}/prepared-print", response_model=AssetOut)
def remove_prepared_print(
    asset_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_prepared_file(asset_id, audit_ctx=audit.context_for(request, context)))


@router.get("/thumb/{asset_id}.jpg")
def get_thumb(asset_id: str, _: Optional[AuthContext] = Depends(require_file_read)):
    p = db.THUMBS / f"{asset_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(
        p,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


FILE_GRANT_MAX_PATHS = 50
FILE_GRANT_FILE = "file"
FILE_GRANT_SUPPORTING_FILE = "supporting-file"
FILE_GRANT_THUMB = "thumb"
FILE_GRANT_PREPARED_PRINT = "prepared-print"

# The complete allow-list of paths a grant may name. A path outside these four
# templates is a 400; a template that names a missing row is a 404. The patterns
# match the URL path component only (the query is validated separately).
_FILE_GRANT_TEMPLATES = (
    (FILE_GRANT_FILE, re.compile(r"^/file/(?P<asset_id>[^/]+)/(?P<name>[^/]+)$")),
    (FILE_GRANT_SUPPORTING_FILE, re.compile(r"^/asset/(?P<asset_id>[^/]+)/files/(?P<file_id>[^/]+)$")),
    (FILE_GRANT_THUMB, re.compile(r"^/thumb/(?P<asset_id>[^/]+)\.jpg$")),
    (FILE_GRANT_PREPARED_PRINT, re.compile(r"^/asset/(?P<asset_id>[^/]+)/prepared-print$")),
)


def file_grant_target(path: str, session: Session) -> str:
    """Validate one requested grant path; returns the template it matched.

    Reading the rows here, not in the verifier, is what makes the allow-list an
    allow-list: a grant can only name a file that existed when it was minted.
    """
    for template, pattern in _FILE_GRANT_TEMPLATES:
        match = pattern.fullmatch(path)
        if match is None:
            continue
        asset = session.get(Asset, match.group("asset_id"))
        if asset is None:
            raise HTTPException(status_code=404)
        if template == FILE_GRANT_SUPPORTING_FILE:
            record = session.get(AssetFile, match.group("file_id"))
            if record is None or record.asset_id != asset.id or record.role != "supporting":
                raise HTTPException(status_code=404)
        elif template == FILE_GRANT_PREPARED_PRINT:
            record = session.get(AssetFile, asset.prepared_file_id) if asset.prepared_file_id else None
            if record is None or record.asset_id != asset.id or record.role != "prepared":
                raise HTTPException(status_code=404)
        return template
    raise HTTPException(status_code=400, detail="not a grantable path")


@router.post("/file-grants", response_model=FileGrantListOut)
def mint_file_grants(body: FileGrantRequest, context: Optional[AuthContext] = Depends(require_read)):
    """Mint a short-lived, single-path, read-only grant for each requested URL.

    Read-only by construction: the mint itself needs only READ, and the grants
    it mints are accepted only by `require_file_read` on the four file routes.
    The client owns the public base, so every URL returned is API-relative.
    """
    if not body.paths:
        raise HTTPException(status_code=400, detail="at least one path is required")
    if len(body.paths) > FILE_GRANT_MAX_PATHS:
        raise HTTPException(
            status_code=400,
            detail=f"at most {FILE_GRANT_MAX_PATHS} paths may be granted at once",
        )
    if context is None:
        session_id = None
        subject = "local"
    else:
        session_id = context.session_id
        subject = context.user_id or auth.BREAK_GLASS_SUBJECT
    grants: List[FileGrantOut] = []
    with Session(engine) as session:
        for raw in body.paths:
            # `urlsplit` raises ValueError on a malformed authority (`//[`), which
            # would be a 500 from a request the client cannot have built.
            try:
                parsed = urlsplit(raw)
            except ValueError:
                raise HTTPException(status_code=400, detail="file grant paths must be API-relative") from None
            if parsed.scheme or parsed.netloc or parsed.fragment:
                raise HTTPException(status_code=400, detail="file grant paths must be API-relative")
            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            # ASGI hands the app the *decoded* path (ASGI `scope["path"]`), and
            # the verifier compares that against the grant's `p` claim, so the
            # claim must be the decoded form: a filename with a space arrives as
            # `my%20model.stl` and would otherwise never match its own grant.
            route_path = unquote(parsed.path)
            inline: Optional[str] = None
            for key, value in query_items:
                if key not in auth.FILE_GRANT_QUERY_KEYS:
                    raise HTTPException(status_code=400, detail=f"query parameter {key!r} is not allowed")
                if key == "inline":
                    inline = value
            template = file_grant_target(route_path, session)
            if inline is not None:
                if template != FILE_GRANT_SUPPORTING_FILE:
                    raise HTTPException(status_code=400, detail="inline is only supported on a supporting-file URL")
                if inline != "1":
                    raise HTTPException(status_code=400, detail="inline must be 1")
            token, expires_at = auth.create_file_grant(
                path=route_path,
                session_id=session_id,
                subject=subject,
                inline=inline,
            )
            # `path` echoes the request string verbatim so the client can key its
            # cache by the exact rel it holds (`?inline=1` included); the URL is
            # that same rel plus `sig`, which keeps `v` and `inline` intact.
            separator = "&" if "?" in raw else "?"
            grants.append(FileGrantOut(path=raw, url=f"{raw}{separator}{urlencode({'sig': token})}", expires_at=expires_at))
    return FileGrantListOut(grants=grants)


GENERATED_THUMBNAIL_MAX_BYTES = 8 * 1024 * 1024
GENERATED_THUMBNAIL_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


# Parsed off the raw body rather than through ``UploadFile`` so the bytes land in
# a staging file and the 8 MB cap trips while they arrive, not after the body has
# been spooled to a temp file and read.
@router.post(
    "/asset/{asset_id}/thumbnail-generated",
    response_model=AssetOut,
    openapi_extra=multipart_form_openapi(),
)
async def save_generated_thumbnail(
    asset_id: str,
    request: Request,
    _: Optional[AuthContext] = Depends(require_write),
):
    staging = new_staging_path()
    # Read the cap as a module global at call time: tests shrink it to prove the
    # rejection happens mid-stream rather than after a buffered read.
    limit = GENERATED_THUMBNAIL_MAX_BYTES
    try:
        staged = await multipart_stream.stream_file_part(
            request,
            staging,
            max_bytes=limit,
            allowed_content_types=GENERATED_THUMBNAIL_TYPES,
        )
        with Session(engine) as s:
            asset = s.get(Asset, asset_id)
            if not asset:
                raise HTTPException(404)
            if not save_thumb(asset_id, staged.path):
                raise HTTPException(status_code=400, detail="Invalid thumbnail image")
            # The bump commits in another session. On this engine a SELECT runs
            # in autocommit (pysqlite's legacy isolation only begins a
            # transaction before DML), so today this ends no snapshot and is a
            # no-op. It stays because the failure it prevents is unrecoverable:
            # `/thumb/` is served year-immutable, so one stale `?v=` pins the
            # old image in a client for a year. It becomes load-bearing as soon
            # as a read snapshot does span the bump - sqlite with begin-on-read
            # (`autocommit=False` or an `isolation_level` change in `db.py`), or
            # a non-sqlite `DB_URL` at REPEATABLE READ or stricter.
            s.rollback()
            s.refresh(asset)
            return to_out(asset)
    except multipart_stream.UnsupportedContentType:
        raise HTTPException(status_code=415, detail="Generated thumbnail must be PNG, JPEG, or WebP") from None
    except multipart_stream.UploadTooLarge:
        raise HTTPException(status_code=413, detail="Generated thumbnail exceeds 8 MB") from None
    except multipart_stream.UploadRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except ClientDisconnect:
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    finally:
        staging.unlink(missing_ok=True)
