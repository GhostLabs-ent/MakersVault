import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("audit", SCRIPTS / "gate13-advisory-audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditEvidenceTests(unittest.TestCase):
    def test_missing_or_truncated_json_cannot_be_clean(self):
        for data in ("", "{", '{} trailing error'):
            with self.assertRaises(ValueError):
                audit.json_stream(data)
        self.assertEqual(audit.json_stream('{}\n {"config":1}'), [{}, {"config": 1}])

    def test_npm_error_is_not_an_empty_vulnerability_report(self):
        with self.assertRaises(RuntimeError):
            audit.summarize("npm-web", 1, [{"error": "registry unavailable"}])
        result = audit.summarize("npm-web", 1, [{"metadata": {"vulnerabilities": {"total": 3}}}])
        self.assertEqual(result["vulnerabilities"]["total"], 3)

    def test_python_skips_are_explicit(self):
        result = audit.summarize("python-runtime", 0, [{"dependencies": [
            {"name": "a", "vulns": [{"id": "advisory"}]}, {"name": "b", "skip_reason": "unavailable"}]}])
        self.assertEqual(result["advisories"], 1)
        self.assertEqual(result["skipped"], ["b"])

    def test_go_inventory_is_not_a_finding_but_zero_exit_does_not_erase_findings(self):
        records = [{"config": {"scanner_version": "v1.7.0"}}, {"osv": {"id": "historical"}}]
        self.assertEqual(audit.summarize("go", 0, records)["findings"], [])
        records.append({"finding": {"osv": "actual"}})
        self.assertEqual(len(audit.summarize("go", 0, records)["findings"]), 1)

    def test_missing_image_database_cannot_be_a_clean_scan(self):
        for database in ({}, {"status": {"valid": False}}, {"status": {"built": "fixture"}}):
            with self.assertRaises(RuntimeError):
                audit.summarize("image-api", 0, [{"matches": [], "descriptor": {"db": database}}])
        result = audit.summarize("image-api", 0, [{"matches": [], "descriptor": {
            "version": "0.118.0", "db": {"status": {"valid": True, "built": "fixture"}}}}])
        self.assertEqual(result["matches"], 0)


if __name__ == "__main__":
    unittest.main()
