import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from sqlmodel import Session, select

from db import STORAGE, engine
from models import ArtifactRevision, ContentHashJob, ContentHashJobItem
from resource_limits import digest_reader


CONTENT_HASH_FAILURE_LIMIT = 50
CONTENT_HASH_HISTORY_LIMIT = 100
CONTENT_HASH_REASON_LIMIT = 160

_hash_coordinator_lock = threading.Lock()
_active_hash_job_id: Optional[str] = None


def content_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def content_hash_failure_details(job: ContentHashJob) -> list[dict[str, str]]:
    try:
        raw = json.loads(job.failure_details_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    details: list[dict[str, str]] = []
    for item in raw[:CONTENT_HASH_FAILURE_LIMIT]:
        if not isinstance(item, dict):
            continue
        revision_id = item.get("revision_id")
        reason = item.get("reason")
        if isinstance(revision_id, str) and isinstance(reason, str):
            details.append({
                "revision_id": revision_id,
                "reason": reason[:CONTENT_HASH_REASON_LIMIT],
            })
    return details


def latest_content_hash_job() -> Optional[ContentHashJob]:
    with Session(engine) as session:
        return session.exec(
            select(ContentHashJob).order_by(
                ContentHashJob.started_at.desc(),
                ContentHashJob.id.desc(),
            )
        ).first()


def get_content_hash_job(job_id: str) -> Optional[ContentHashJob]:
    with Session(engine) as session:
        return session.get(ContentHashJob, job_id)


def recover_interrupted_content_hash_jobs() -> int:
    recovered = 0
    now = content_timestamp()
    with Session(engine) as session:
        jobs = list(
            session.exec(
                select(ContentHashJob).where(ContentHashJob.status == "running")
            )
        )
        for job in jobs:
            job.status = "interrupted"
            job.finished_at = now
            session.add(job)
            items = list(
                session.exec(
                    select(ContentHashJobItem).where(
                        ContentHashJobItem.job_id == job.id,
                        ContentHashJobItem.status == "running",
                    )
                )
            )
            for item in items:
                item.status = "pending"
                item.reason = None
                session.add(item)
            recovered += 1
        if recovered:
            session.commit()
    return recovered


def _prune_hash_job_history(session: Session) -> None:
    older = list(
        session.exec(
            select(ContentHashJob)
            .where(ContentHashJob.status != "running")
            .order_by(ContentHashJob.started_at.desc(), ContentHashJob.id.desc())
            .offset(CONTENT_HASH_HISTORY_LIMIT)
        )
    )
    for job in older:
        for item in session.exec(
            select(ContentHashJobItem).where(ContentHashJobItem.job_id == job.id)
        ):
            session.delete(item)
        session.delete(job)


def _resume_interrupted_job(session: Session) -> Optional[ContentHashJob]:
    jobs = list(
        session.exec(
            select(ContentHashJob)
            .where(ContentHashJob.status == "interrupted")
            .order_by(ContentHashJob.started_at.desc(), ContentHashJob.id.desc())
        )
    )
    for job in jobs:
        pending = session.exec(
            select(ContentHashJobItem).where(
                ContentHashJobItem.job_id == job.id,
                ContentHashJobItem.status == "pending",
            )
        ).first()
        if pending:
            job.status = "running"
            job.finished_at = None
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
    return None


def _create_content_hash_job(trigger: str, verify_all: bool) -> Optional[ContentHashJob]:
    with Session(engine) as session:
        if trigger == "startup":
            resumed = _resume_interrupted_job(session)
            if resumed:
                return resumed

        predicate = "1 = 1" if verify_all else "content_state IN ('pending', 'failed')"
        total = int(
            session.connection().exec_driver_sql(
                f"SELECT COUNT(*) FROM artifactrevision WHERE {predicate}"
            ).scalar_one()
        )
        if total == 0:
            return None

        job = ContentHashJob(
            trigger=trigger,
            status="running",
            started_at=content_timestamp(),
            total=total,
        )
        session.add(job)
        session.flush()
        session.connection().exec_driver_sql(
            f"""
            INSERT INTO contenthashjobitem(job_id, revision_id, status)
            SELECT ?, id, 'pending' FROM artifactrevision WHERE {predicate}
            """,
            (job.id,),
        )
        _prune_hash_job_history(session)
        session.commit()
        session.refresh(job)
        return job


def _managed_revision_path(revision: ArtifactRevision) -> Optional[Path]:
    if not revision.storage_path:
        return None
    root = STORAGE.resolve()
    candidate = (STORAGE / revision.storage_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("managed_path_outside_storage")
    return candidate if candidate.is_file() else None


def _digest_revision(revision: ArtifactRevision) -> tuple[str, Optional[str], int]:
    managed = _managed_revision_path(revision)
    if managed:
        with managed.open("rb") as source:
            size, digest = digest_reader(source, "Revision content", max_bytes=None)
        return digest, "managed", size

    if revision.source_path:
        import mount_import

        root_raw = (mount_import.MOUNT_IMPORT_PATH or "").strip()
        if not root_raw:
            raise FileNotFoundError("external_mount_unconfigured")
        with mount_import.open_safe_mount_file(
            Path(root_raw), Path(revision.source_path)
        ) as (source, opened_size, _):
            size, digest = digest_reader(source, "External revision content", max_bytes=None)
        if size != opened_size:
            raise ValueError("external_content_changed_while_hashing")
        return digest, "external", size

    raise FileNotFoundError("content_missing")


def _classify_revision(revision: ArtifactRevision) -> tuple[str, Optional[str]]:
    try:
        observed, _kind, size = _digest_revision(revision)
    except FileNotFoundError as exc:
        revision.content_state = "unavailable"
        revision.content_reason = str(exc) or "content_missing"
        revision.observed_sha256 = None
        revision.content_checked_at = content_timestamp()
        return revision.content_state, revision.content_reason
    except Exception as exc:
        revision.content_state = "failed"
        revision.content_reason = (str(exc).strip() or "hash_failed")[:CONTENT_HASH_REASON_LIMIT]
        revision.content_checked_at = content_timestamp()
        return revision.content_state, revision.content_reason

    revision.observed_sha256 = observed
    revision.content_checked_at = content_timestamp()
    if int(revision.size or 0) != size:
        revision.content_state = "changed"
        revision.content_reason = "size_mismatch"
    elif revision.sha256 and revision.sha256 != observed:
        revision.content_state = "changed"
        revision.content_reason = "digest_mismatch"
    else:
        if not revision.sha256:
            revision.sha256 = observed
        revision.content_state = "ready"
        revision.content_reason = None
    return revision.content_state, revision.content_reason


def _record_item_result(job_id: str, revision_id: str) -> None:
    with Session(engine) as session:
        job = session.get(ContentHashJob, job_id)
        item = session.get(ContentHashJobItem, (job_id, revision_id))
        revision = session.get(ArtifactRevision, revision_id)
        if not job or not item:
            return
        if revision:
            state, reason = _classify_revision(revision)
            session.add(revision)
        else:
            state, reason = "failed", "revision_missing"

        item.status = state
        item.reason = reason
        job.processed += 1
        if state == "ready":
            job.ready += 1
        elif state == "unavailable":
            job.unavailable += 1
        elif state == "changed":
            job.changed += 1
        else:
            job.failed += 1
        if state != "ready":
            details = content_hash_failure_details(job)
            detail = {"revision_id": revision_id, "reason": reason or state}
            if len(details) < CONTENT_HASH_FAILURE_LIMIT:
                details.append(detail)
                job.failure_details_json = json.dumps(details)
            else:
                job.failure_details_omitted += 1
        session.add(item)
        session.add(job)
        session.commit()


def _finish_job(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(ContentHashJob, job_id)
        if not job:
            return
        job.status = (
            "completed_with_findings"
            if job.failed or job.unavailable or job.changed
            else "completed"
        )
        job.finished_at = content_timestamp()
        session.add(job)
        session.commit()


def _run_content_hash_job(job_id: str) -> None:
    global _active_hash_job_id
    try:
        while True:
            with Session(engine) as session:
                job = session.get(ContentHashJob, job_id)
                if not job or job.status != "running":
                    return
                item = session.exec(
                    select(ContentHashJobItem)
                    .where(
                        ContentHashJobItem.job_id == job_id,
                        ContentHashJobItem.status == "pending",
                    )
                    .order_by(ContentHashJobItem.revision_id)
                ).first()
                if not item:
                    break
                revision_id = item.revision_id
                item.status = "running"
                session.add(item)
                session.commit()
            _record_item_result(job_id, revision_id)
        _finish_job(job_id)
    finally:
        with _hash_coordinator_lock:
            if _active_hash_job_id == job_id:
                _active_hash_job_id = None


def start_content_hash_job(
    trigger: str = "manual",
    verify_all: bool = False,
) -> Tuple[Optional[ContentHashJob], bool]:
    global _active_hash_job_id
    with _hash_coordinator_lock:
        if _active_hash_job_id:
            active = get_content_hash_job(_active_hash_job_id)
            if active and active.status == "running":
                return active, False
            _active_hash_job_id = None

        job = _create_content_hash_job(trigger, verify_all)
        if not job:
            return latest_content_hash_job(), False
        _active_hash_job_id = job.id
        threading.Thread(
            target=_run_content_hash_job,
            args=(job.id,),
            daemon=True,
            name=f"content-hash-{job.id[:8]}",
        ).start()
        return job, True
