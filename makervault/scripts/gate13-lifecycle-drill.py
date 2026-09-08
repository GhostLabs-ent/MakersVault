"""Current-build upgrade, raw recovery, rollback and portable-startup proof."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

from verification_runtime import APP, REPO, SCHEMA, HOST, DisposableStack, image_identity, install_signal_handlers, run, smoke

sys.path.insert(0, str(APP / "api/tests"))
from gate5_fixture import build_fixture
from gate13_fixture import snapshot as filesystem_snapshot


def verify_upgrade(client, expected):
    assets = {item["id"]: item for item in client.request("/assets?limit=100")}
    assert sorted(assets) == expected["asset_ids"]
    managed = assets["asset-managed"]
    assert (managed["name"], managed["filename"], managed["creator"]) == (
        "Renamed Bracket", "old-bracket-name.stl", "MakersVault Fixture")
    content = client.request(managed["url"])
    assert hashlib.sha256(content).hexdigest() == expected["managed_sha256"]["Workshop/Fasteners/Renamed Bracket/old-bracket-name.stl"]
    assert client.request(managed["thumb_url"]) == b"legacy-derived-thumbnail"
    prepared = assets["asset-prepared"]["prepared_print"]
    assert {key: prepared[key] for key in expected["prepared_summary"]} == expected["prepared_summary"]
    related = client.request("/asset/asset-prepared/files")
    assert [item["id"] for item in related] == ["file-doc"]
    assert client.request("/asset/asset-prepared/files/file-doc") == b"%PDF-1.4 gate5 assembly\n"
    assert client.request(assets["asset-external-available"]["url"]) == b"externally-owned-step\n"
    client.request(assets["asset-external-missing"]["url"], expected=404)
    folders = {item["id"]: item for item in client.request("/folders")}
    assert folders["folder-fasteners"]["parent_id"] == "folder-workshop"
    assert folders["folder-jigs"]["parent_id"] == "folder-workshop"


def enrich(client, password):
    client.upload("/asset/asset-managed/revisions", "revision-two.stl", b"solid revision two\nendsolid revision two\n")
    project = client.request("/projects", method="POST", body={"name": "Recovery Project", "creator": "Fixture maker", "license": "CC0"}, expected=201)
    for asset in ("asset-managed", "asset-prepared"):
        client.request(f"/project/{project['id']}/items/{asset}", method="POST", expected=201)
    client.request(f"/project/{project['id']}/relationships", method="POST", expected=201,
                   body={"source_asset_id": "asset-managed", "target_asset_id": "asset-prepared", "kind": "derived_from"})
    machine = client.request("/machines", method="POST", body={"name": "Recovery P1S", "category": "fdm_printer"}, expected=201)
    client.request(f"/asset/asset-prepared/machines/{machine['id']}", method="POST", expected=201)
    client.request("/asset/asset-prepared/prepared-machine", method="PUT", body={"machine_id": machine["id"]})
    client.request("/asset/asset-interrupted", method="DELETE")
    client.request("/session/reauthenticate", method="POST", body={"password": password})
    member = client.request("/users", method="POST", expected=201,
                            body={"username": "recovery-member", "display_name": "Recovery fixture", "password": "fixture-member-password", "role": "member"})
    client.request("/account/passkeys/registration/options", method="POST")
    return member["id"]


def assert_raw_restore(before, after):
    assert before["schema"] == after["schema"] == SCHEMA
    assert before["files"] == after["files"], "Raw restore changed stored bytes"
    assert before["tables"].keys() == after["tables"].keys(), "Raw restore changed table inventory"
    for table, rows in before["tables"].items():
        if table not in {"browsersession", "webauthnchallenge", "recoverymarker"}:
            assert rows == after["tables"][table], f"Raw restore changed {table}"
    for table, changed_field in (("browsersession", "revoked_at"), ("webauthnchallenge", "consumed_at")):
        original = {row["id"]: row for row in before["tables"][table]}
        restored = {row["id"]: row for row in after["tables"][table]}
        assert original and original.keys() == restored.keys(), f"Missing copied {table}"
        for key, row in original.items():
            assert restored[key][changed_field] is not None, f"Copied {table} remained active"
            assert {k: v for k, v in row.items() if k != changed_field} == {
                k: v for k, v in restored[key].items() if k != changed_field}, f"Unexpected {table} mutation"
    assert after["tables"]["webauthncredential"], "Credential fixture missing"
    assert len(after["tables"]["recoverymarker"]) == len(before["tables"]["recoverymarker"]) + 1


def portable_members(archive):
    result = {}
    with tarfile.open(archive, "r|gz") as source:
        for member in source:
            if not member.name.startswith(("mvault/catalogs/", "mvault/content/", "mvault/derived/")):
                continue
            stream = source.extractfile(member)
            if member.name in {"mvault/catalogs/revisions.jsonl", "mvault/catalogs/artifacts.jsonl"}:
                rows = [json.loads(line) for line in stream]
                # A clean import intentionally makes external references unavailable.
                # Normalize only that specified state; every other field must match.
                for row in rows:
                    if row.get("content", {}).get("ownership") == "external":
                        row["content"]["state"] = "unavailable"
                result[member.name] = json.dumps(rows, sort_keys=True)
            else:
                result[member.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def expected_started_fixture_members(before):
    expected = dict(before)
    # Import deliberately omits operational preview timestamps. On startup,
    # backfill_embedded_thumbnails re-evaluates the legacy 3MF fixture with no
    # thumbnail/timestamp. Assert exactly that derived-state transition; do not
    # ignore arbitrary preview, metadata, graph, or payload differences.
    for catalog, owner_key in (("artifacts", "id"), ("revisions", "asset_id")):
        name = f"mvault/catalogs/{catalog}.jsonl"
        rows = json.loads(before[name])
        matches = [row for row in rows if row[owner_key] == "asset-prepared"]
        assert len(matches) == 1
        assert matches[0]["preview"] == {"policy_version": 1, "reason": "embedded_complexity",
                                          "source": "embedded_thumbnail", "status": "skipped_policy"}
        matches[0]["preview"].update(status="pending", reason=None)
        expected[name] = json.dumps(rows, sort_keys=True)
    return expected


def portable(stack, directory, module, *args, check=True):
    return stack.compose("run", "--rm", "-T", "--no-deps", "--user",
                         f"{os.getuid()}:{os.getgid()}", "-v", f"{directory}:/evidence",
                         "--entrypoint", "python", "api", "-m", module, *args, check=check)


def seed_empty_volumes(stack, database_directory, storage_directory):
    # Only newly generated projects are accepted by this harness. Refuse an
    # existing pair before copying verified, stopped filesystem staging output.
    for source, destination in ((database_directory, "/app/data"), (storage_directory, "/app/storage")):
        listing = stack.compose("run", "--rm", "-T", "--no-deps", "--entrypoint", "ls", "api", "-A", destination)
        assert not listing.stdout.strip(), "Fixture destination must be empty"
    for source, destination in ((database_directory, "/app/data"), (storage_directory, "/app/storage")):
        data = run(["tar", "-C", source, "-cf", "-", "."]).stdout
        stack.compose("run", "--rm", "-T", "--no-deps", "--entrypoint", "tar", "api", "-C", destination, "-xf", "-", data=data)


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-dirty", action="store_true", help="development only; report is explicitly unqualified")
    args = parser.parse_args()
    revision = run(["git", "-C", REPO, "rev-parse", "HEAD"]).stdout.decode().strip()
    dirty = bool(run(["git", "-C", REPO, "status", "--porcelain", "--untracked-files=all", "--",
                      "makervault/api", "makervault/web", "makervault/scripts", "makervault/benchmarks"]).stdout)
    if dirty and not args.allow_dirty:
        parser.error("Verification sources must be committed (or use --allow-dirty for development)")
    version = "development-gate13b" + ("-dirty" if dirty else "")
    api_image = f"makersvault-api:gate13b-{revision[:12]}" + ("-dirty" if dirty else "")
    web_image = f"makersvault-web:gate13b-{revision[:12]}" + ("-dirty" if dirty else "")
    print("Building local development verification images", flush=True)
    for target, image, context in (("runtime", api_image, "api"), (None, web_image, "web")):
        run(["docker", "build", *(["--target", target] if target else []),
             "--build-arg", f"MAKERSVAULT_VERSION={version}", "--build-arg", f"MAKERSVAULT_REVISION={revision}",
             "-t", image, APP / context])
    images = {"api": image_identity(api_image, version, revision), "web": image_identity(web_image, version, revision)}
    with tempfile.TemporaryDirectory(prefix="makersvault-gate13-") as temporary, ExitStack() as cleanup:
        root = Path(temporary)
        legacy = root / "legacy"
        build_fixture(legacy, api_image)
        expected = json.loads((legacy / "expected.json").read_text())

        def stack(name, **kwargs):
            instance = DisposableStack(root / name, images["api"], images["web"], **kwargs)
            cleanup.callback(instance.close)
            return instance

        source = stack("source", username="gate5", password="gate5-recovery-password", imports=legacy / "imports")
        seed_empty_volumes(source, legacy / "database", legacy / "storage")
        before = source.snapshot()
        assert before["schema"] == 4
        pre_backup = root / "pre-upgrade.tar.gz"
        source.backup(pre_backup, revision)
        print("Upgrading representative schema 4 to production schema 17 over HTTPS", flush=True)
        source.start()
        client = source.client()
        client.login(source.config["AUTH_USERNAME"], source.config["AUTH_PASSWORD"])
        verify_upgrade(client, expected)
        source.stop()
        upgraded = source.snapshot()
        assert upgraded["schema"] == SCHEMA and upgraded["files"] == before["files"]
        assert len(upgraded["tables"]["artifactrevision"]) == 5
        source.compose("start", "api", "web")
        source.wait()
        member_id = enrich(client, source.config["AUTH_PASSWORD"])
        node_env = {**os.environ, "NODE_EXTRA_CA_CERTS": "/fixture/ca.crt",
                    "MAKERSVAULT_HARNESS_ORIGIN": source.origin,
                    "MAKERSVAULT_HARNESS_USERNAME": source.config["AUTH_USERNAME"],
                    "MAKERSVAULT_HARNESS_PASSWORD": source.config["AUTH_PASSWORD"]}
        node_image = "node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293"
        run(["docker", "run", "--rm", "--network", "host", "--add-host", f"{HOST}:127.0.0.1",
             "-e", "NODE_EXTRA_CA_CERTS", "-e", "MAKERSVAULT_HARNESS_ORIGIN",
             "-e", "MAKERSVAULT_HARNESS_USERNAME", "-e", "MAKERSVAULT_HARNESS_PASSWORD",
             "-v", f"{source.certificate}:/fixture/ca.crt:ro", "-v", f"{APP / 'benchmarks'}:/bench:ro",
             node_image, "node", "/bench/session-client-smoke.mjs"], env=node_env)
        source.stop()
        source.offline("/app/tests/gate13_fixture.py", "seed-public-credential", "--confirm-disposable", "--user-id", member_id)
        snapshot = source.snapshot()
        for table in ("project", "projectrelationship", "machineprofile", "artifactmachine", "webauthncredential", "webauthnchallenge", "auditevent"):
            assert snapshot["tables"][table], f"Missing representative {table}"
        assert any(row["revoked_at"] is None for row in snapshot["tables"]["browsersession"])
        assert any(row["consumed_at"] is None for row in snapshot["tables"]["webauthnchallenge"])
        archive = root / "schema17.tar.gz"
        source.backup(archive, revision)

        print("Testing refusal, matched raw restore and pre-start credential/session state", flush=True)
        rejected = source.restore(archive, check=False)
        assert rejected.returncode != 0 and b"not empty" in rejected.stderr
        assert source.snapshot() == snapshot, "Nonempty refusal changed source"
        corrupt = root / "corrupt.tar.gz"
        corrupt.write_bytes(archive.read_bytes()[:64])
        assert source.restore(corrupt, check=False).returncode != 0
        assert source.snapshot() == snapshot, "Corrupt-archive refusal changed source"
        restored = stack("restored", username=source.config["AUTH_USERNAME"], password=source.config["AUTH_PASSWORD"])
        restored.config["AUTH_SECRET"] = source.config["AUTH_SECRET"]
        restored.write_config()
        restored.restore(archive)
        assert_raw_restore(snapshot, restored.snapshot())
        restored.start()
        restored.client(client.jar).request("/session", expected=401)
        restored_client = restored.client()
        restored_client.login(source.config["AUTH_USERNAME"], source.config["AUTH_PASSWORD"])
        assert restored_client.request("/projects")[0]["name"] == "Recovery Project"
        restored_client.request("/file/asset-external-available/available.step", expected=404)
        restored.stop()
        started = restored.snapshot()
        assert all(row["processed_at"] is not None for row in started["tables"]["recoverymarker"])
        assert len(started["tables"]["auditevent"]) > len(snapshot["tables"]["auditevent"])

        print("Exporting schema 17, importing empty schema 12, then bootstrapping a new schema-17 identity", flush=True)
        portable(source, root, "mvault_export", "--database", "/app/data/app.db", "--storage", "/app/storage",
                 "--output", "/evidence/source.mvault", "--confirm-stopped")
        run(["python3", APP / "api/mvault_verify.py", root / "source.mvault"])
        assert source.snapshot() == snapshot, "Portable export changed source"
        imported = stack("imported", username="fresh-portable-admin", password="fresh-portable-password")
        # The importer atomically renames sibling staging directories. A mounted
        # volume root cannot be renamed: import under a writable private parent,
        # verify the completed pair, then populate empty production volumes.
        target = root / "portable-target"
        import_args = ("--archive", "/evidence/source.mvault", "--database", "/evidence/portable-target/database/app.db",
                       "--storage", "/evidence/portable-target/storage", "--confirm-stopped-empty")
        portable(imported, root, "mvault_import", *import_args)
        clean = filesystem_snapshot(target / "database/app.db", target / "storage")
        assert clean["schema"] == 12 and "useraccount" not in clean["tables"]
        assert portable(imported, root, "mvault_import", *import_args, check=False).returncode != 0
        assert filesystem_snapshot(target / "database/app.db", target / "storage") == clean, "Portable nonempty refusal changed imported target"
        seed_empty_volumes(imported, target / "database", target / "storage")
        assert imported.snapshot() == clean, "Staged portable pair changed during volume population"
        portable(imported, root, "mvault_export", "--database", "/app/data/app.db", "--storage", "/app/storage",
                 "--output", "/evidence/before-start.mvault", "--confirm-stopped")
        left = portable_members(root / "source.mvault")
        assert left == portable_members(root / "before-start.mvault"), "Offline portable content/graph changed"
        imported.start()
        fresh_client = imported.client()
        fresh_client.request("/login", method="POST", body={"username": "gate5", "password": "gate5-recovery-password"}, expected=401)
        fresh_client.login(imported.config["AUTH_USERNAME"], imported.config["AUTH_PASSWORD"])
        assert fresh_client.request("/projects")[0]["name"] == "Recovery Project"
        imported.stop()
        fresh = imported.snapshot()
        assert fresh["schema"] == SCHEMA and len(fresh["tables"]["useraccount"]) == 1
        assert fresh["tables"]["useraccount"][0]["username"] == "fresh-portable-admin"
        assert not fresh["tables"]["webauthncredential"] and not fresh["tables"]["webauthnchallenge"]
        assert fresh["tables"]["authenticatorpolicy"][0]["mode"] == "optional"
        portable(imported, root, "mvault_export", "--database", "/app/data/app.db", "--storage", "/app/storage",
                 "--output", "/evidence/reexport.mvault", "--confirm-stopped")
        right = portable_members(root / "reexport.mvault")
        expected_started = expected_started_fixture_members(left)
        if expected_started != right:
            differences = [name for name in sorted(expected_started.keys() | right.keys()) if expected_started.get(name) != right.get(name)]
            raise AssertionError("Portable content/graph changed: " + ", ".join(differences))

        print("Restoring exact pre-upgrade pair and checking a clean production install", flush=True)
        source.restore(pre_backup, replace=True)
        assert source.snapshot() == before, "Rollback did not restore exact schema-4 database/storage"
        assert (legacy / "imports/available/available.step").read_bytes() == b"externally-owned-step\n"
        fresh_stack = stack("fresh")
        fresh_stack.start()
        smoke_result = smoke(fresh_stack, version, revision)
        report = {"status": "passed", "revision": revision, "dirty": dirty, "version": version, "images": images,
                  "upgrade": "4-to-17", "raw_restore_contract": 6, "pre_start_revocation": True,
                  "startup_audit": True, "portable_import_schema": 12, "portable_startup_schema": SCHEMA,
                  "fresh_identity_only": True, "portable_members_compared": len(left),
                  "portable_staged_pair_verified": True,
                  "offline_portable_graph_equal": True, "startup_preview_reconciliation": "legacy_3mf_pending",
                  "external_availability_normalized": True, "exact_schema4_rollback": True,
                  "refusals": ["nonempty_raw_target", "corrupt_raw_archive", "nonempty_portable_target"],
                  "benchmark_session_helper": "passed", "fresh_smoke": smoke_result}
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
