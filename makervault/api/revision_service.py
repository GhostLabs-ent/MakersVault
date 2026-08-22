from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from models import ArtifactRevision, Asset


def revision_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def initial_revision_for_asset(asset: Asset) -> ArtifactRevision:
    return ArtifactRevision(
        asset_id=asset.id,
        revision_number=1,
        created_at=revision_timestamp(),
        filename=asset.filename,
        mime=asset.mime,
        size=int(asset.size or 0),
        storage_path=asset.storage_path,
        source_path=asset.source_path,
        prepared_file_id=asset.prepared_file_id,
        prepared_metadata_json=asset.prepared_metadata_json,
        preview_status=asset.preview_status,
        preview_reason=asset.preview_reason,
        preview_attempts=int(asset.preview_attempts or 0),
        preview_policy_version=int(asset.preview_policy_version or 1),
        preview_updated_at=asset.preview_updated_at,
        preview_source=asset.preview_source,
        preview_thumb_path=f"thumbs/{asset.id}.jpg",
        content_state="pending",
    )


def current_revision(session: Session, asset: Asset) -> Optional[ArtifactRevision]:
    if not asset.current_revision_id:
        return None
    revision = session.get(ArtifactRevision, asset.current_revision_id)
    if revision and revision.asset_id == asset.id:
        return revision
    return None


def sync_current_revision(
    session: Session,
    asset: Asset,
    *,
    content_sha256: Optional[str] = None,
) -> ArtifactRevision:
    revision = current_revision(session, asset)
    if revision is None:
        revision = initial_revision_for_asset(asset)
        asset.current_revision_id = revision.id

    revision.filename = asset.filename
    revision.mime = asset.mime
    revision.size = int(asset.size or 0)
    revision.storage_path = asset.storage_path
    revision.source_path = asset.source_path
    revision.prepared_file_id = asset.prepared_file_id
    revision.prepared_metadata_json = asset.prepared_metadata_json
    revision.preview_status = asset.preview_status
    revision.preview_reason = asset.preview_reason
    revision.preview_attempts = int(asset.preview_attempts or 0)
    revision.preview_policy_version = int(asset.preview_policy_version or 1)
    revision.preview_updated_at = asset.preview_updated_at
    revision.preview_source = asset.preview_source
    revision.preview_thumb_path = f"thumbs/{asset.id}.jpg"
    if content_sha256:
        revision.sha256 = content_sha256
        revision.observed_sha256 = content_sha256
        revision.content_state = "ready"
        revision.content_reason = None
        revision.content_checked_at = revision_timestamp()

    session.add(revision)
    session.add(asset)
    return revision


def delete_artifact_revisions(session: Session, asset_id: str) -> None:
    for revision in session.exec(
        select(ArtifactRevision).where(ArtifactRevision.asset_id == asset_id)
    ):
        session.delete(revision)
