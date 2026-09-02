from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from db import STORAGE, engine
from main import app
from models import ArtifactRevision, Asset, AssetFile
import revision_workflow


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def _upload(client: TestClient, headers: dict[str, str], name: str, data: bytes) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (name, data, "model/stl")},
    )
    assert response.status_code == 200
    return response.json()


def _replace(
    client: TestClient,
    headers: dict[str, str],
    asset_id: str,
    data: bytes,
    note: str = "",
    expected_current_revision_id: str | None = None,
):
    return client.post(
        f"/asset/{asset_id}/revisions",
        headers=headers,
        data={
            "change_note": note,
            **(
                {"expected_current_revision_id": expected_current_revision_id}
                if expected_current_revision_id else {}
            ),
        },
        files={"file": ("replacement.stl", data, "model/stl")},
    )


def test_replacement_is_immutable_identical_is_noop_and_restore_creates_history() -> None:
    first_bytes = b"solid revision one\n"
    second_bytes = b"solid revision two\n"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "versioned.stl", first_bytes)
        try:
            first_history = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()
            revision_one = first_history[0]

            replaced = _replace(
                client, headers, asset["id"], second_bytes, "Stronger mounting tab"
            )
            assert replaced.status_code == 200
            assert replaced.json()["created"] is True
            assert replaced.json()["revision"]["revision_number"] == 2
            assert replaced.json()["revision"]["change_note"] == "Stronger mounting tab"

            history = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()
            assert [row["revision_number"] for row in history] == [2, 1]
            assert [row["is_current"] for row in history] == [True, False]

            current = client.get(replaced.json()["asset"]["url"], headers=headers)
            historical = client.get(revision_one["url"], headers=headers)
            assert current.content == second_bytes
            assert historical.content == first_bytes

            identical = _replace(client, headers, asset["id"], second_bytes)
            assert identical.status_code == 200
            assert identical.json()["created"] is False
            assert len(client.get(f"/asset/{asset['id']}/revisions", headers=headers).json()) == 2

            restored = client.post(
                f"/asset/{asset['id']}/revisions/{revision_one['id']}/restore",
                headers=headers,
                json={"change_note": "Return to original geometry"},
            )
            assert restored.status_code == 200
            assert restored.json()["created"] is True
            assert restored.json()["revision"]["revision_number"] == 3
            assert restored.json()["revision"]["origin_revision_id"] == revision_one["id"]
            assert restored.json()["revision"]["change_note"] == "Return to original geometry"
            assert client.get(restored.json()["asset"]["url"], headers=headers).content == first_bytes
            assert client.get(revision_one["url"], headers=headers).content == first_bytes
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_changed_historical_bytes_cannot_be_restored() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "changed-history.stl", b"first bytes")
        try:
            revision_one = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            replaced = _replace(client, headers, asset["id"], b"second bytes")
            assert replaced.status_code == 200

            with Session(engine) as session:
                revision = session.get(ArtifactRevision, revision_one["id"])
                path = (STORAGE / revision.storage_path).resolve()
            path.write_bytes(b"tampered bytes")

            restore = client.post(
                f"/asset/{asset['id']}/revisions/{revision_one['id']}/restore",
                headers=headers,
                json={},
            )
            assert restore.status_code == 409
            history = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()
            assert len(history) == 2
            changed = next(row for row in history if row["id"] == revision_one["id"])
            assert changed["content_state"] == "changed"
            assert changed["content_reason"] in {"size_mismatch", "digest_mismatch"}
            assert next(row for row in history if row["is_current"])["revision_number"] == 2
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_concurrent_replacements_have_one_winner_and_clean_loser_staging() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "revision-race.stl", b"initial")
        try:
            initial_revision_id = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]["id"]
            def replace(data: bytes):
                return _replace(
                    client,
                    headers,
                    asset["id"],
                    data,
                    expected_current_revision_id=initial_revision_id,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(replace, [b"candidate a", b"candidate b"]))

            assert sorted(response.status_code for response in responses) == [200, 409]
            history = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()
            assert [row["revision_number"] for row in history] == [2, 1]
            staging = STORAGE / ".revision-staging"
            assert not staging.exists() or not any(path.is_file() for path in staging.rglob("*"))
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_artifact_rename_does_not_move_or_relabel_historical_revision() -> None:
    content = b"immutable rename bytes"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "before-name.stl", content)
        try:
            before = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            with Session(engine) as session:
                row = session.get(Asset, asset["id"])
                original_path = Path(row.storage_path)

            renamed = client.post(
                f"/asset/{asset['id']}/meta",
                headers=headers,
                json={"name": "After Name"},
            )
            assert renamed.status_code == 200
            assert renamed.json()["filename"] == "After Name.stl"

            after = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            assert after["filename"] == before["filename"]
            with Session(engine) as session:
                row = session.get(Asset, asset["id"])
                revision = session.get(ArtifactRevision, before["id"])
                assert Path(row.storage_path) == original_path
                assert Path(revision.storage_path) == original_path
            assert client.get(renamed.json()["url"], headers=headers).content == content
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_restore_copies_prepared_payload_into_new_revision() -> None:
    gcode = b";TIME:192\n; nozzle_diameter = 0.4\nG28\n"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "prepared-history.stl", b"first")
        try:
            attached = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("prepared.gcode", gcode, "text/plain")},
            )
            assert attached.status_code == 200
            revision_one = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            assert revision_one["prepared_print"] is not None

            assert _replace(client, headers, asset["id"], b"second").status_code == 200
            assert client.get(f"/asset/{asset['id']}/prepared-print", headers=headers).status_code == 404

            restored = client.post(
                f"/asset/{asset['id']}/revisions/{revision_one['id']}/restore",
                headers=headers,
                json={},
            )
            assert restored.status_code == 200
            assert restored.json()["asset"]["prepared_print"] is not None
            downloaded = client.get(f"/asset/{asset['id']}/prepared-print", headers=headers)
            assert downloaded.status_code == 200
            assert downloaded.content == gcode

            history = client.get(f"/asset/{asset['id']}/revisions", headers=headers).json()
            restored_revision = next(row for row in history if row["is_current"])
            with Session(engine) as session:
                restored_row = session.get(ArtifactRevision, restored_revision["id"])
                prepared = session.get(AssetFile, restored_row.prepared_file_id)
                assert prepared.revision_id == restored_row.id
                assert prepared.id != revision_one["id"]
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_history_export_preserves_artifact_and_revision_scopes() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "exported.stl", b"one")
        try:
            artifact_file = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("assembly.pdf", b"pdf notes", "application/pdf")},
            )
            assert artifact_file.status_code == 200
            replacement = _replace(client, headers, asset["id"], b"two", "Second edition")
            assert replacement.status_code == 200
            current_revision_id = replacement.json()["revision"]["id"]
            scoped_file = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                data={"revision_id": current_revision_id},
                files={"file": ("plate-notes.txt", b"revision notes", "text/plain")},
            )
            assert scoped_file.status_code == 200

            related = client.get(f"/asset/{asset['id']}/files", headers=headers).json()
            assert {row["revision_id"] for row in related} == {None, current_revision_id}

            exported = client.get(f"/asset/{asset['id']}/revisions/export", headers=headers)
            assert exported.status_code == 200
            with ZipFile(BytesIO(exported.content)) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["format"] == "makersvault-artifact-history"
                assert len(manifest["revisions"]) == 2
                assert any(name.startswith("attachments/artifact/") for name in names)
                assert any(name.startswith("revisions/2/attachments/") for name in names)
                assert "revisions/1/exported.stl" in names
                assert "revisions/2/exported.stl" in names
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_delete_removes_all_managed_revision_files() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "cleanup.stl", b"one")
        assert _replace(client, headers, asset["id"], b"two").status_code == 200
        with Session(engine) as session:
            paths = [
                (STORAGE / row.storage_path).resolve()
                for row in session.exec(
                    select(ArtifactRevision).where(ArtifactRevision.asset_id == asset["id"])
                )
                if row.storage_path
            ]
        assert all(path.is_file() for path in paths)
        deleted = client.delete(f"/asset/{asset['id']}", headers=headers)
        assert deleted.status_code == 200
        assert all(path.exists() for path in paths)
        purged = client.post(
            "/trash/permanent",
            headers=headers,
            json={
                "asset_ids": [asset["id"]],
                "confirmation": "PERMANENTLY DELETE",
            },
        )
        assert purged.status_code == 200
        assert all(not path.exists() for path in paths)


def test_replacement_preserves_historical_thumbnail_bytes() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 140)).save(image, format="PNG")
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "thumbnail-history.stl", b"one")
        try:
            generated = client.post(
                f"/asset/{asset['id']}/thumbnail-generated",
                headers=headers,
                files={"file": ("thumbnail.png", image.getvalue(), "image/png")},
            )
            assert generated.status_code == 200
            revision_one = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]

            assert _replace(client, headers, asset["id"], b"two").status_code == 200
            history = client.get(f"/asset/{asset['id']}/revisions", headers=headers).json()
            old = next(row for row in history if row["id"] == revision_one["id"])
            old_thumb = client.get(old["thumb_url"], headers=headers)
            assert old_thumb.status_code == 200
            old_bytes = old_thumb.content

            regenerated = client.post(
                f"/asset/{asset['id']}/thumbnail-generated",
                headers=headers,
                files={"file": ("thumbnail.png", image.getvalue(), "image/png")},
            )
            assert regenerated.status_code == 200
            updated_history = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()
            current = next(row for row in updated_history if row["is_current"])
            assert current["thumb_url"]
            assert current["thumb_url"] != old["thumb_url"]
            assert client.get(old["thumb_url"], headers=headers).content == old_bytes
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_failed_revision_stream_leaves_current_and_staging_unchanged(monkeypatch) -> None:
    async def fail_stream(upload, destination, label, digest=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial")
        raise RuntimeError("simulated stream failure")

    monkeypatch.setattr(revision_workflow, "stream_upload_to_file", fail_stream)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "failed-revision.stl", b"stable")
        try:
            before = client.get(f"/asset/{asset['id']}/revisions", headers=headers).json()
            failed = _replace(client, headers, asset["id"], b"replacement")
            assert failed.status_code == 500
            after = client.get(f"/asset/{asset['id']}/revisions", headers=headers).json()
            assert after == before
            assert client.get(asset["url"], headers=headers).content == b"stable"
            staging = STORAGE / ".revision-staging"
            assert not staging.exists() or not any(path.is_file() for path in staging.rglob("*"))
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)
