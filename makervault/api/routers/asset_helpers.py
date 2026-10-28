"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import List, Optional

from fastapi import HTTPException, Response
from sqlmodel import Session

import bulk_service
from models import Asset


# The 400 half of the batch contract documented above the batch routes in
# routers/assets.py: a request with no ids cannot change anything.
def require_asset_ids(raw: List[str]) -> List[str]:
    asset_ids = bulk_service.unique_asset_ids(raw)
    if not asset_ids:
        raise HTTPException(status_code=400, detail="asset_ids is required")
    return asset_ids


def apply_asset_filters(stmt, q: Optional[str], tags: Optional[str], folder_id: Optional[str]):
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
    tag_filter = [t.strip() for t in (tags or "").split(",") if t.strip()]
    for tag in tag_filter:
        stmt = stmt.where(Asset.tags_json.like(f'%"{tag}"%'))
    return stmt


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
