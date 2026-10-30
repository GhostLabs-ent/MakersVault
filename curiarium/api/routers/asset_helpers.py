"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import List, Optional

from fastapi import HTTPException, Response
from sqlalchemy import func
from sqlmodel import Session, select

import bulk_service
from models import Asset, ProjectAsset


# The 400 half of the batch contract documented above the batch routes in
# routers/assets.py: a request with no ids cannot change anything.
def require_asset_ids(raw: List[str]) -> List[str]:
    asset_ids = bulk_service.unique_asset_ids(raw)
    if not asset_ids:
        raise HTTPException(status_code=400, detail="asset_ids is required")
    return asset_ids


def apply_asset_filters(
    stmt,
    q: Optional[str],
    tags: Optional[str],
    folder_id: Optional[str],
    project_id: Optional[str] = None,
    not_in_project: bool = False,
    creator: Optional[str] = None,
):
    if q:
        qlike = f"%{q}%"
        stmt = stmt.where(
            (Asset.name.like(qlike))
            | (Asset.filename.like(qlike))
            | (Asset.title.like(qlike))
            | (Asset.notes.like(qlike))
            | (Asset.creator.like(qlike))
            | (Asset.collection.like(qlike))
        )
    if folder_id:
        stmt = stmt.where(Asset.folder_id == folder_id)
    # An exact creator filter, case-insensitive like the facet's dedupe. A
    # whitespace-only value is ignored rather than a 400: the UI sends the chip
    # back verbatim and an empty chip means "no filter".
    if creator is not None:
        cleaned_creator = creator.strip()
        if cleaned_creator:
            stmt = stmt.where(func.lower(Asset.creator) == cleaned_creator.lower())
    if project_id:
        stmt = stmt.where(Asset.id.in_(select(ProjectAsset.asset_id).where(ProjectAsset.project_id == project_id)))
    if not_in_project:
        # asset_id is half of project_asset's composite primary key, so it is
        # never NULL and NOT IN is the exact complement of the membership filter
        # used by the project listing and by POST /download/zip.
        stmt = stmt.where(Asset.id.not_in(select(ProjectAsset.asset_id)))
    tag_filter = [t.strip() for t in (tags or "").split(",") if t.strip()]
    for tag in tag_filter:
        stmt = stmt.where(Asset.tags_json.like(f'%"{tag}"%'))
    return stmt


def apply_asset_order(stmt, sort: Optional[str], order: str = "asc"):
    """Order an asset listing, with a unique tiebreaker chain on every sort.

    No `sort` keeps the historical default (`Asset.name`, `Asset.filename`,
    `Asset.id`). An explicit sort always ends in `Asset.filename, Asset.id`, so
    a page boundary can never duplicate or skip a row: `size` and `creator` are
    not unique, and without the tiebreakers SQLite is free to return equal rows
    in any order between two limit/offset queries.

    Creator sorts case-insensitively and puts NULLs last in BOTH directions:
    the NULL flag is ordered ascending before the optional descending value.
    """
    if sort is None:
        return stmt.order_by(Asset.name, Asset.filename, Asset.id)
    descending = order == "desc"
    if sort == "size":
        primary = Asset.size.desc() if descending else Asset.size
        return stmt.order_by(primary, Asset.filename, Asset.id)
    if sort == "creator":
        creator = func.lower(Asset.creator)
        primary = creator.desc() if descending else creator
        return stmt.order_by(Asset.creator.is_(None), primary, Asset.filename, Asset.id)
    primary = Asset.name.desc() if descending else Asset.name
    return stmt.order_by(primary, Asset.filename, Asset.id)


def asset_page(session: Session, stmt, response: Response, limit: Optional[int], offset: Optional[int]) -> List[Asset]:
    """The one pagination contract: at most `limit` rows plus the two headers.

    Shared by `GET /assets` and `GET /project/{project_id}/assets`, so the two
    listings cannot disagree about `X-Has-More`, `X-Next-Offset`, or about sending
    no pagination header at all when `limit` is absent. The extra `+ 1` row is how
    `has_more` is known without a second count query.
    """
    if limit is not None:
        stmt = stmt.limit(limit + 1)
        if offset:
            stmt = stmt.offset(offset)
    assets = list(session.exec(stmt))

    has_more = False
    if limit is not None and len(assets) > limit:
        has_more = True
        assets = assets[:limit]
    if limit is not None and response is not None:
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str((offset or 0) + len(assets))
    return assets
