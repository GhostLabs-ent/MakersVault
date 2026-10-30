"""Pre-operation snapshots on the three destructive routes (Mf-julm).

The guard itself is tested in `test_snapshot_guard.py`; this module drives it
through the routes, where the things that matter are the ones a unit test cannot
see: a refusal must leave the library byte-identical, the snapshot must really
hold the pre-delete bytes, and each request must own exactly one row.

Every test works in a temporary storage root (`db.STORAGE` / `db.THUMBS` are
patched by the `isolated_storage` fixture), and every test that reaches the guard
installs its own capability answer through `snapshot_fakes`, so no outcome here
depends on the filesystem this suite happens to run on. The policies are pinned
in the same fixture for the same reason: they are operator environment variables.

The parametrised table in `test_the_outcome_table_on_purge` is AC-5: policy x
availability x provider failure, with the status, the audit row and the mutation
that must (not) have happened for each row.
"""

import json
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
import snapshot_fakes
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import audit
import config
import db
import library_scan
import snapshot_guard
import snapshots
import trash_service
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder

PRE_DELETE = snapshots.SnapshotReason.PRE_DELETE
PRE_PURGE = snapshots.SnapshotReason.PRE_PURGE
PRE_BULK = snapshots.SnapshotReason.PRE_BULK

SNAPSHOT_ACTIONS = (audit.SNAPSHOT_CREATE, audit.SNAPSHOT_PRUNE, audit.SNAPSHOT_DELETE)

REQUEST_ID_HEADER = "X-Request-ID"


# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage and thumbnails at temp roots, pin the policies, undo the rows."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # The guard's decisions are configuration, and the configuration is the
    # operator's environment: pin it so no developer's `.env` changes an outcome.
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREDELETE", "warn")
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "strict")
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREBULK", "strict")
    monkeypatch.setattr(config, "SNAPSHOT_REQUIRE_CAPABILITY", False)

    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        files_before = {row.id for row in session.exec(select(AssetFile))}
    yield storage
    with Session(engine) as session:
        for row in list(session.exec(select(AssetFile))):
            if row.id not in files_before:
                session.delete(row)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture()
def client():
    """`raise_server_exceptions=False`: the table asserts a 500 for one row."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def request_id_for(test_name: str) -> str:
    """A unique, header-legal id: letters, digits and dashes only."""
    return f"{test_name}-{uuid4().hex}"


def admin_headers(client: TestClient, value: Optional[str] = None) -> dict:
    """Bearer token (or nothing when auth is disabled), plus the request id."""
    health = client.get("/health").json()
    headers = {}
    if health.get("auth_required"):
        token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
        headers["Authorization"] = f"Bearer {token}"
    if value is not None:
        headers[REQUEST_ID_HEADER] = value
    return headers


def storage_state(root: Path) -> dict:
    """Path -> kind/content map, so byte-level changes are directly comparable."""
    state = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            state[relative] = ("dir", None)
        else:
            state[relative] = ("file", path.read_bytes())
    return state


def write_placeholder_file(path: Path, payload: bytes = b"placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def trash_entry(storage: Path, name: str = "20250101T000000Z-Old", payload: bytes = b"aaaa") -> Path:
    """One disposable trash entry; the purge's subject."""
    entry = storage / ".trash" / name
    write_placeholder_file(entry / "a.stl", payload)
    return entry


def insert_asset_row(
    name: str,
    folder_id: Optional[str],
    storage_path: Optional[str],
    *,
    filename: str = "model.stl",
    size: int = 10,
    is_reference: int = 0,
    source_path: Optional[str] = None,
    supporting_file_count: int = 0,
) -> str:
    asset = Asset(
        filename=filename,
        mime="model/stl",
        size=size,
        name=name,
        folder_id=folder_id,
        storage_path=storage_path,
        is_reference=is_reference,
        source_path=source_path,
        supporting_file_count=supporting_file_count,
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


def created_folder(client: TestClient, headers: dict, name: str) -> dict:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def events_for(value: str) -> list[AuditEvent]:
    """Every audit row this request wrote; the table is append-only, so never all of it."""
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == value)))


def destructive_rows(value: str) -> list[AuditEvent]:
    return [row for row in events_for(value) if row.action.startswith("destructive.")]


def detail_of(row: AuditEvent) -> dict:
    return json.loads(row.detail_json or "{}")


def spy_guard(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record what `guard()` returned, without calling it a second time.

    The purge response is `TrashPurgeOut` and must not gain a key, so the notice
    the guard built is only observable here -- at the seam the route calls.
    """
    recorded: dict = {}
    real = snapshot_guard.guard

    def wrapper(reason, target, *, ctx):
        notice = real(reason, target, ctx=ctx)
        recorded.update(reason=reason, target=target, notice=notice)
        return notice

    monkeypatch.setattr(snapshot_guard, "guard", wrapper)
    return recorded


# --- AC-5: the outcome table ------------------------------------------------

OUTCOMES = [
    # policy, capability, provider failure, require_capability, status, action, cause
    ("warn", "unavailable", None, False, 200, "proceed_without", "unavailable"),
    ("strict", "unavailable", None, False, 200, "proceed_without", "unavailable"),
    ("strict", "unavailable", None, True, 409, None, "unavailable"),
    ("warn", "available", None, False, 200, "snapshot", None),
    ("strict", "available", None, False, 200, "snapshot", None),
    ("warn", "available", "unavailable", False, 200, "proceed_without", "unavailable"),
    ("strict", "available", "unavailable", False, 409, None, "unavailable"),
    ("warn", "available", "failed", False, 200, "proceed_without", "failed"),
    ("strict", "available", "failed", False, 500, None, "failed"),
]


def outcome_id(row: tuple) -> str:
    policy, capability, failure, require, status, action, cause = row
    return f"{policy}-{capability}-{failure or 'ok'}-{'required' if require else 'optional'}-{status}"


def provider_failure(kind: Optional[str]) -> Optional[BaseException]:
    """The exception a scripted provider raises, from the table's short name."""
    if kind == "unavailable":
        return snapshots.SnapshotUnavailable("the snapshot directory vanished")
    if kind == "failed":
        return snapshots.SnapshotError("boom")
    return None


@pytest.mark.parametrize("row", OUTCOMES, ids=outcome_id)
def test_the_outcome_table_on_purge(isolated_storage: Path, client, monkeypatch, row: tuple) -> None:
    """Policy x availability x provider failure, on `POST /trash/purge` itself.

    Everything the table claims is asserted from outside the guard: the HTTP
    status, the one row the request wrote, the notice the guard built, and the
    trash tree. A refused row must be byte-identical afterwards, which is the
    proof that the guard runs before the mutation rather than around it.
    """
    storage = isolated_storage
    policy, capability, failure, require, status, action, cause = row
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", policy)
    monkeypatch.setattr(config, "SNAPSHOT_REQUIRE_CAPABILITY", require)
    error = provider_failure(failure)
    provider = None
    if capability == "available":
        provider = snapshot_fakes.use_provider(monkeypatch, storage, fail=error)
    else:
        snapshot_fakes.use_unavailable(monkeypatch)

    entry = trash_entry(storage)
    before = storage_state(storage)
    entries_before = trash_service.list_entries()
    recorded = spy_guard(monkeypatch)
    value = request_id_for("table")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == status, response.text

    rows = events_for(value)
    snapshot_rows = [item for item in rows if item.action.startswith("destructive.")]
    assert len(snapshot_rows) == 1, [item.action for item in rows]
    row_written = snapshot_rows[0]
    detail = detail_of(row_written)
    assert row_written.target == "trash"
    # The guard passes `ctx=None`, so the provider writes none of its own rows.
    assert [item for item in rows if item.action in SNAPSHOT_ACTIONS] == []

    if cause is None:
        assert row_written.action == audit.DESTRUCTIVE_SNAPSHOT_TAKEN
        assert detail["reason"] == "prepurge"
        assert detail["policy"] == policy
        assert snapshots.NAME_RE.fullmatch(detail["name"])
        assert detail["method"] == provider.method
        assert recorded["notice"].name == detail["name"]
        assert recorded["notice"].action == "snapshot"
        assert recorded["notice"].capability == "available"
        assert not entry.exists(), "a taken snapshot does not stop the purge"
    else:
        assert row_written.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
        assert detail == {
            "reason": "prepurge",
            "policy": policy,
            "cause": cause,
            "error": None if error is None else str(error),
        }
        if action is None:
            assert recorded == {}, "a refusal returns no notice"
            assert response.json()["detail"]
            assert storage_state(storage) == before
            assert trash_service.list_entries() == entries_before
            assert entry.is_dir()
        else:
            assert recorded["notice"].action == action
            assert recorded["notice"].name is None
            assert not entry.exists()

    if provider is not None:
        assert provider.calls == [(PRE_PURGE, None)], "one snapshot per request, and no context"


def test_the_purge_response_gains_no_key(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """`TrashPurgeOut` is unchanged: the notice lives in the audit log, not here."""
    snapshot_fakes.use_unavailable(monkeypatch)
    storage = Path(db.STORAGE)
    trash_entry(storage)

    response = client.post("/trash/purge", headers=admin_headers(client))

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"purged", "bytes", "failed"}


# --- AC-1: a folder delete leaves a named snapshot of the pre-delete tree ---


def test_ac1_a_folder_delete_snapshots_the_pre_delete_tree(isolated_storage: Path, client, monkeypatch) -> None:
    """The snapshot is real: it holds the bytes the delete is about to move away."""
    storage = isolated_storage
    provider = snapshot_fakes.use_tree_copy(monkeypatch, storage)
    headers = admin_headers(client)
    folder = created_folder(client, headers, "Shelf")
    write_placeholder_file(storage / "Shelf" / "model.stl", b"model bytes")
    write_placeholder_file(storage / "Shelf" / "part.stl", b"part bytes")
    write_placeholder_file(storage / "Shelf" / "scene" / "notes.txt", b"notes bytes")
    asset_id = insert_asset_row("model", folder["id"], "Shelf/model.stl")
    value = request_id_for("ac1")

    response = client.delete(
        f"/folder/{folder['id']}",
        params={"confirm_name": "Shelf"},
        headers=admin_headers(client, value),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    notice = body["snapshot"]
    name = notice["name"]
    assert name is not None, "the response to the mutation names the snapshot"
    assert snapshots.NAME_RE.fullmatch(name)
    assert notice["reason"] == "predelete"
    assert notice["action"] == "snapshot"
    assert notice["capability"] == "available"
    assert notice["pattern"] == snapshot_guard.name_pattern(PRE_DELETE)
    assert snapshots.parse_name(name).reason is PRE_DELETE

    # The row names the same snapshot, and GET /audit serves it.
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_TAKEN
    assert row.target == folder["id"]
    assert detail_of(row)["name"] == name
    assert detail_of(row)["reason"] == "predelete"
    served = client.get("/audit", params={"action": audit.DESTRUCTIVE_SNAPSHOT_TAKEN, "target": folder["id"]}, headers=headers)
    assert served.status_code == 200, served.text
    assert served.json()["events"][0]["detail"]["name"] == name
    assert snapshots.NAME_RE.fullmatch(served.json()["events"][0]["detail"]["name"])

    # The snapshot holds the pre-delete tree, and never the snapshot store itself.
    snapshot_path = provider.path_for(name)
    store = (storage / snapshots.SNAPSHOT_DIRNAME).resolve()
    assert snapshot_path.is_dir()
    assert store in snapshot_path.parents
    assert ".trash" not in snapshot_path.relative_to(storage.resolve()).parts
    assert (snapshot_path / "Shelf" / "model.stl").read_bytes() == b"model bytes"
    assert (snapshot_path / "Shelf" / "part.stl").read_bytes() == b"part bytes"
    assert (snapshot_path / "Shelf" / "scene" / "notes.txt").read_bytes() == b"notes bytes"
    assert not (snapshot_path / snapshots.SNAPSHOT_DIRNAME).exists()

    # And the delete really happened: live folder gone, bytes in the trash.
    assert not (storage / "Shelf").exists()
    trashed = storage / body["trash_path"]
    assert (trashed / "model.stl").read_bytes() == b"model bytes"
    assert (trashed / "part.stl").read_bytes() == b"part bytes"
    with Session(engine) as session:
        assert session.get(Asset, asset_id) is None
        assert session.get(Folder, folder["id"]) is None


# --- AC-2: an unavailable capability follows the policy and audits ----------


def test_ac2_unavailable_warn_proceeds_and_audits_the_absence(isolated_storage: Path, client, monkeypatch) -> None:
    storage = isolated_storage
    snapshot_fakes.use_unavailable(monkeypatch)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "warn")
    entry = trash_entry(storage)
    value = request_id_for("ac2-warn")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == 200, response.text
    assert response.json() == {"purged": 1, "bytes": 4, "failed": []}
    assert not entry.exists()
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert row.target == "trash"
    assert detail_of(row) == {"reason": "prepurge", "policy": "warn", "cause": "unavailable", "error": None}


def test_ac2_unavailable_strict_with_the_switch_refuses_and_audits(isolated_storage: Path, client, monkeypatch) -> None:
    storage = isolated_storage
    snapshot_fakes.use_unavailable(monkeypatch)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "strict")
    monkeypatch.setattr(config, "SNAPSHOT_REQUIRE_CAPABILITY", True)
    entry = trash_entry(storage)
    before = storage_state(storage)
    value = request_id_for("ac2-strict")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == 409, response.text
    assert "refusing prepurge" in response.json()["detail"]
    assert "SNAPSHOT_REQUIRE_CAPABILITY" in response.json()["detail"]
    assert storage_state(storage) == before
    assert entry.is_dir()
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert detail_of(row) == {"reason": "prepurge", "policy": "strict", "cause": "unavailable", "error": None}


# --- AC-3: strict blocks a purge whose snapshot failed ---------------------


def test_ac3_strict_refuses_the_purge_when_the_snapshot_fails(isolated_storage: Path, client, monkeypatch) -> None:
    storage = isolated_storage
    failure = snapshots.SnapshotUnavailable("the snapshot directory vanished")
    provider = snapshot_fakes.use_provider(monkeypatch, storage, fail=failure)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "strict")
    entry = trash_entry(storage)
    before = storage_state(storage)
    value = request_id_for("ac3-unavailable-strict")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == str(failure)
    assert storage_state(storage) == before, "a refused purge has removed nothing"
    assert entry.is_dir()
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert detail_of(row) == {"reason": "prepurge", "policy": "strict", "cause": "unavailable", "error": str(failure)}
    assert provider.calls == [(PRE_PURGE, None)]


def test_ac3_warn_mirror_purges_and_audits_the_failed_snapshot(isolated_storage: Path, client, monkeypatch) -> None:
    storage = isolated_storage
    failure = snapshots.SnapshotUnavailable("the snapshot directory vanished")
    snapshot_fakes.use_provider(monkeypatch, storage, fail=failure)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "warn")
    entry = trash_entry(storage)
    value = request_id_for("ac3-unavailable-warn")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == 200, response.text
    assert response.json() == {"purged": 1, "bytes": 4, "failed": []}
    assert not entry.exists()
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert detail_of(row)["cause"] == "unavailable"
    assert detail_of(row)["error"] == str(failure)


def test_ac3_a_generic_snapshot_failure_is_a_500_under_strict_and_purges_nothing(
    isolated_storage: Path, client, monkeypatch
) -> None:
    storage = isolated_storage
    failure = snapshots.SnapshotError("boom")
    snapshot_fakes.use_provider(monkeypatch, storage, fail=failure)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", "strict")
    entry = trash_entry(storage)
    before = storage_state(storage)
    value = request_id_for("ac3-failed-strict")

    response = client.post("/trash/purge", headers=admin_headers(client, value))

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == str(failure)
    assert storage_state(storage) == before
    assert entry.is_dir()
    row = destructive_rows(value)[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert detail_of(row) == {"reason": "prepurge", "policy": "strict", "cause": "failed", "error": str(failure)}


# --- AC-5: one snapshot row per request, on all three routes ---------------


def destruct(operation: str, client: TestClient, headers: dict, folder: dict, asset_ids: list[str]) -> None:
    """Call one of the three destructive routes and assert it answered 200."""
    if operation == "folder":
        response = client.delete(f"/folder/{folder['id']}", params={"confirm_name": "Shelf"}, headers=headers)
    elif operation == "purge":
        response = client.post("/trash/purge", headers=headers)
    else:
        response = client.post(
            "/assets/batch/delete",
            json={"asset_ids": asset_ids, "confirm_count": len(asset_ids)},
            headers=headers,
        )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("operation", ["folder", "purge", "bulk"], ids=["folder", "purge", "bulk"])
def test_ac5_each_destructive_route_writes_exactly_one_snapshot_row(
    isolated_storage: Path, client, monkeypatch, operation: str
) -> None:
    storage = isolated_storage
    provider = snapshot_fakes.use_provider(monkeypatch, storage)
    headers = admin_headers(client)
    folder = created_folder(client, headers, "Shelf")
    write_placeholder_file(storage / "Shelf" / "model.stl", b"model bytes")
    insert_asset_row("model", folder["id"], "Shelf/model.stl")
    trash_entry(storage)
    asset_ids = [
        insert_asset_row("one", None, None, filename="one.stl"),
        insert_asset_row("two", None, None, filename="two.stl"),
    ]
    value = request_id_for(f"ac5-{operation}")

    destruct(operation, client, admin_headers(client, value), folder, asset_ids)

    rows = events_for(value)
    snapshot_rows = [row for row in rows if row.action.startswith("destructive.")]
    assert len(snapshot_rows) == 1, [row.action for row in rows]
    row = snapshot_rows[0]
    expected = {"folder": (PRE_DELETE, folder["id"]), "purge": (PRE_PURGE, "trash"), "bulk": (PRE_BULK, "assets")}[operation]
    reason, target = expected
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_TAKEN
    assert row.target == target
    assert detail_of(row)["reason"] == reason.value
    assert snapshots.NAME_RE.fullmatch(detail_of(row)["name"])
    # One provider call, and never a context: the guard owns the request's row.
    assert provider.calls == [(reason, None)]
    assert [item for item in rows if item.action in SNAPSHOT_ACTIONS] == []


def test_a_bulk_delete_takes_one_snapshot_for_the_whole_selection(isolated_storage: Path, client, monkeypatch) -> None:
    storage = isolated_storage
    provider = snapshot_fakes.use_provider(monkeypatch, storage)
    asset_ids = [insert_asset_row(f"asset {index}", None, None, filename=f"asset-{index}.stl") for index in range(3)]
    value = request_id_for("bulk-one")

    response = client.post(
        "/assets/batch/delete",
        json={"asset_ids": asset_ids, "confirm_count": 3},
        headers=admin_headers(client, value),
    )

    assert response.status_code == 200, response.text
    assert sorted(response.json()["deleted"]) == sorted(asset_ids)
    rows = events_for(value)
    snapshot_rows = [row for row in rows if row.action.startswith("destructive.")]
    assert len(snapshot_rows) == 1, "one snapshot per gesture, not one per asset"
    assert snapshot_rows[0].action == audit.DESTRUCTIVE_SNAPSHOT_TAKEN
    assert snapshot_rows[0].target == "assets"
    assert detail_of(snapshot_rows[0])["reason"] == "prebulk"
    # The per-asset action still names each id, as before.
    assert sorted(row.target for row in rows if row.action == audit.ASSET_DELETE) == sorted(asset_ids)
    assert provider.calls == [(PRE_BULK, None)]


# --- the bulk delete preview ------------------------------------------------


@pytest.mark.parametrize("available", [True, False], ids=["available", "unavailable"])
def test_the_delete_preview_counts_like_the_dialog_and_writes_nothing(
    isolated_storage: Path, client, monkeypatch, tmp_path: Path, available: bool
) -> None:
    """A reference contributes no files and no bytes: deleting its row moves nothing."""
    storage = isolated_storage
    if available:
        snapshot_fakes.use_capability(monkeypatch)
    else:
        snapshot_fakes.use_unavailable(monkeypatch)
    headers = admin_headers(client)
    folder = created_folder(client, headers, "Shelf")
    write_placeholder_file(storage / "Shelf" / "model.stl", b"model bytes")
    external = tmp_path / "external.stl"
    write_placeholder_file(external, b"external bytes")
    plain = insert_asset_row("model", folder["id"], "Shelf/model.stl", size=10, supporting_file_count=3)
    reference = insert_asset_row(
        "external", folder["id"], None, filename="external.stl", size=999, is_reference=1, source_path=str(external)
    )
    before = storage_state(storage)
    value = request_id_for("preview")

    response = client.get(
        "/assets/delete-preview",
        params={"asset_ids": [plain, reference]},
        headers=admin_headers(client, value),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assets"] == 2
    assert body["files"] == 4, "1 + 3 supporting for the plain asset, 0 for the reference"
    assert body["bytes"] == 10, "the reference's recorded size is not reclaimed"
    notice = body["snapshot"]
    assert notice["reason"] == "prebulk"
    assert notice["pattern"] == snapshot_guard.name_pattern(PRE_BULK)
    assert notice["name"] is None
    assert notice["capability"] == ("available" if available else "unavailable")
    assert notice["action"] == ("snapshot" if available else "proceed_without")
    assert notice["detail"] == (None if available else snapshot_fakes.UNUSABLE.reason)

    # A GET changes nothing, on disk or in the log.
    assert storage_state(storage) == before
    assert events_for(value) == []


def test_the_delete_preview_needs_at_least_one_id(client, monkeypatch) -> None:
    snapshot_fakes.use_unavailable(monkeypatch)

    response = client.get("/assets/delete-preview", headers=admin_headers(client))

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "asset_ids is required"


def test_the_delete_preview_ignores_unknown_ids(isolated_storage: Path, client, monkeypatch) -> None:
    """Only rows that exist are counted, so a stale dialog reports the truth."""
    storage = isolated_storage
    snapshot_fakes.use_unavailable(monkeypatch)
    headers = admin_headers(client)
    known = insert_asset_row("known", None, None, filename="known.stl", size=7)

    response = client.get(
        "/assets/delete-preview",
        params={"asset_ids": [known, "00000000-0000-0000-0000-000000000000"]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["assets"] == 1
    assert response.json()["files"] == 1
    assert response.json()["bytes"] == 7
    assert not (storage / snapshots.SNAPSHOT_DIRNAME).exists()
