"""Orchestration for "import a URL into a project" (Mf-56z9).

Nothing here is HTTP plumbing and nothing here is a pydantic boundary: the route
normalises the URL, the import service performs the fetch, and this module
decides which project the result belongs to. Outbound calls go through `seams`
so the suite keeps patching the names it pins on `main`.

Two orderings are load-bearing:

* the files are imported BEFORE the project is found or created, so a hard
  failure cannot leave an empty junk project behind - while an EXPLICIT
  `project_id` is proved to exist first, so a stale id cannot leave the asset it
  just downloaded orphaned behind a later 404;
* a gated outcome stores no files and issues no second request - the page's own
  metadata is all it keeps.

The project is reused when the same page is imported twice, but the files are
not: a repeat import writes fresh asset rows and adds them as extra members,
because the filename and size are only known once the body has been streamed.
No member-level de-duplication exists on this path - this is an accepted
limitation of Mf-56z9, not something another flow covers.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from zipfile import BadZipFile

from fastapi import HTTPException

import project_service
import seams
import zip_service
from asset_service import AssetOrigin
from import_metadata import PageMetadata, parse_page_metadata
from import_policy import GATED_IMPORT_DETAIL
from models import Asset
from schemas import ImportProjectRequest
from url_utils import canonical_url

# The site itself refusing anonymous access is a gated outcome; any other status
# is the error it always was (a free model with no downloadable file stays 400).
GATED_STATUS_CODES = frozenset({401, 403})


@dataclass(frozen=True)
class ImportOutcome:
    """What one import did: the project, the assets and the per-step results."""

    project_id: str
    created: bool
    assets: List[Asset] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    gated: bool = False
    message: str = ""


def _host_for_name(source_url: str) -> str:
    """The host to name an unnamed import after; total on garbage."""
    try:
        return (urlparse(source_url).hostname or "").lower() or "the web"
    except ValueError:
        return "the web"


def _is_gated(page, metadata: PageMetadata, error: HTTPException) -> bool:
    """Whether a failed fetch means "behind a login/purchase" rather than "no file".

    Both halves require a page this import actually read: the model page was
    public and only its FILES were refused. Without one there are no details to
    import, and a 403 at that point can equally be bot protection or a hotlink
    guard on a free model, so the original error stands (today's behaviour).

    With a page, an explicit boolean flag in it is the primary detector, and a
    401/403 from the site is the real one - that is the site refusing anonymous
    access while the page itself was readable.
    """
    if page is None:
        return False
    return metadata.gated or error.status_code in GATED_STATUS_CODES


def _zip_assets(attempt, body: ImportProjectRequest, origin: Optional[AssetOrigin]) -> Tuple[List[Asset], List[str]]:
    """Extract the selected entries, always removing the downloaded temp file.

    Extracting a zip is its own door (`CreatedVia`), even inside a project
    import: the route names the request "link-import", and every row this
    function creates is honestly "zip-import".
    """
    tmp_path = attempt.tmp_path
    zip_origin = None if origin is None else replace(origin, created_via="zip-import")
    try:
        if Path(attempt.filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            return zip_service.extract_zip_entries_to_assets(tmp_path, body.entries, body, origin=zip_origin)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def import_into_project(url: str, body: ImportProjectRequest, *, origin: Optional[AssetOrigin] = None) -> ImportOutcome:
    """Import `url` (already normalised) and attach the result to a project."""
    if body.project_id:
        project_service.require_project(body.project_id)
    wants_zip = body.entries is not None
    if wants_zip:
        attempt = seams.download_zip_attempt(url, body)
    else:
        attempt = seams.import_asset_attempt(url, body, origin=origin)

    page = attempt.page
    metadata = parse_page_metadata(page.html, page.url) if page else PageMetadata()
    source_url = canonical_url(page.url if page else url)
    suggested_name = body.project_name or metadata.title or f"Imported model from {_host_for_name(source_url)}"

    if attempt.error is not None:
        if not _is_gated(page, metadata, attempt.error):
            raise attempt.error
        project_id, created = project_service.find_or_create_import_project(
            project_id=body.project_id,
            suggested_name=suggested_name,
            source_url=source_url,
            creator=metadata.creator,
            licence=metadata.licence,
            licence_url=metadata.licence_url,
        )
        # Only a project that has no files is "details only": marking one that
        # already has members would tell the user its files are missing.
        if project_service.project_with_stats(project_id)[1] == 0:
            project_service.set_project_metadata_marker(project_id, {"_files": "user-supplied"})
        return ImportOutcome(project_id=project_id, created=created, gated=True, message=GATED_IMPORT_DETAIL)

    if wants_zip:
        assets, failed = _zip_assets(attempt, body, origin)
    elif attempt.asset is not None:
        assets, failed = [attempt.asset], []
    else:
        raise HTTPException(status_code=400, detail="No downloadable model file found. Use a direct download link.")

    project_id, created = project_service.find_or_create_import_project(
        project_id=body.project_id,
        suggested_name=suggested_name,
        source_url=source_url,
        creator=metadata.creator,
        licence=metadata.licence,
        licence_url=metadata.licence_url,
    )
    added, skipped, _member_failures = project_service.add_assets(project_id, [asset.id for asset in assets])
    return ImportOutcome(
        project_id=project_id,
        created=created,
        assets=assets,
        added=added,
        skipped=skipped,
        failed=failed,
    )
