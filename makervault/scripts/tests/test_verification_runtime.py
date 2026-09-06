import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("lifecycle", SCRIPTS / "gate13-lifecycle-drill.py")
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class RawRestoreAssertions(unittest.TestCase):
    def fixture(self):
        before = {"schema": 17, "files": {"file": "sha256"}, "tables": {
            "useraccount": [{"id": "user", "password_hash": "hash"}],
            "webauthncredential": [{"id": "credential", "public_key": "key"}],
            "authenticatorpolicy": [{"mode": "optional"}],
            "project": [{"id": "project"}], "recoverymarker": [],
            "browsersession": [{"id": "session", "user_id": "user", "revoked_at": None}],
            "webauthnchallenge": [{"id": "challenge", "consumed_at": None}],
        }}
        after = copy.deepcopy(before)
        after["tables"]["browsersession"][0]["revoked_at"] = 1
        after["tables"]["webauthnchallenge"][0]["consumed_at"] = 1
        after["tables"]["recoverymarker"].append({"id": "marker"})
        return before, after

    def test_expected_security_mutation_only(self):
        lifecycle.assert_raw_restore(*self.fixture())

    def test_content_identity_policy_and_credentials_cannot_silently_change(self):
        for table in ("useraccount", "webauthncredential", "authenticatorpolicy", "project"):
            with self.subTest(table=table):
                before, after = self.fixture()
                after["tables"][table] = []
                with self.assertRaises(AssertionError):
                    lifecycle.assert_raw_restore(before, after)

    def test_missing_revocation_or_marker_cannot_pass(self):
        for table, field in (("browsersession", "revoked_at"), ("webauthnchallenge", "consumed_at")):
            before, after = self.fixture()
            after["tables"][table][0][field] = None
            with self.assertRaises(AssertionError):
                lifecycle.assert_raw_restore(before, after)
        before, after = self.fixture()
        after["tables"]["recoverymarker"] = []
        with self.assertRaises(AssertionError):
            lifecycle.assert_raw_restore(before, after)

    def test_raw_file_digest_and_schema_are_binding(self):
        before, after = self.fixture()
        after["files"]["file"] = "changed"
        with self.assertRaises(AssertionError):
            lifecycle.assert_raw_restore(before, after)
        before, after = self.fixture()
        after["schema"] = 5
        with self.assertRaises(AssertionError):
            lifecycle.assert_raw_restore(before, after)


class PortableAssertions(unittest.TestCase):
    def test_startup_expectation_changes_only_known_legacy_preview(self):
        before = {"payload": "sha256"}
        for catalog, owner_key in (("artifacts", "id"), ("revisions", "asset_id")):
            before[f"mvault/catalogs/{catalog}.jsonl"] = json.dumps([{
                owner_key: "asset-prepared", "name": "unchanged", "preview": {
                    "policy_version": 1, "reason": "embedded_complexity",
                    "source": "embedded_thumbnail", "status": "skipped_policy"}}], sort_keys=True)
        expected = lifecycle.expected_started_fixture_members(before)
        self.assertEqual(expected["payload"], before["payload"])
        for catalog in ("artifacts", "revisions"):
            name = f"mvault/catalogs/{catalog}.jsonl"
            original, restarted = json.loads(before[name])[0], json.loads(expected[name])[0]
            self.assertEqual(restarted["preview"]["status"], "pending")
            self.assertIsNone(restarted["preview"]["reason"])
            restarted["preview"] = original["preview"]
            self.assertEqual(original, restarted)
        # Unexpected source state is not silently accepted as the same transition.
        before["mvault/catalogs/artifacts.jsonl"] = before["mvault/catalogs/artifacts.jsonl"].replace("embedded_complexity", "timeout")
        with self.assertRaises(AssertionError):
            lifecycle.expected_started_fixture_members(before)

    def test_volume_population_checks_both_targets_before_writing(self):
        for occupied in (0, 1):
            stack = Mock()
            stack.compose.side_effect = [Mock(stdout=b"occupied" if index == occupied else b"") for index in range(2)]
            with patch.object(lifecycle, "run") as tar:
                with self.assertRaisesRegex(AssertionError, "must be empty"):
                    lifecycle.seed_empty_volumes(stack, Path("database"), Path("storage"))
                tar.assert_not_called()
            self.assertTrue(all(call.args[5] == "ls" for call in stack.compose.call_args_list))

    def archive(self, path, state="ready", filename="model.stl", payload=b"model bytes"):
        row = {"filename": filename, "content": {"ownership": "external", "state": state,
                                                "source_path": "/imports/model.stl"}}
        with tarfile.open(path, "w:gz") as archive:
            for name, data in (("mvault/catalogs/revisions.jsonl", json.dumps(row).encode() + b"\n"),
                               ("mvault/content/files/supporting/payload", payload)):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def test_only_external_availability_is_normalized(self):
        with tempfile.TemporaryDirectory() as temporary:
            left, right = Path(temporary) / "left", Path(temporary) / "right"
            self.archive(left)
            self.archive(right, state="unavailable")
            self.assertEqual(lifecycle.portable_members(left), lifecycle.portable_members(right))
            self.archive(right, state="unavailable", filename="changed.stl")
            self.assertNotEqual(lifecycle.portable_members(left), lifecycle.portable_members(right))
            self.archive(right, state="unavailable", payload=b"changed bytes")
            self.assertNotEqual(lifecycle.portable_members(left), lifecycle.portable_members(right))


if __name__ == "__main__":
    unittest.main()
