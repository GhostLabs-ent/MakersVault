import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("browser_workflows", SCRIPTS / "gate13-browser-workflows.py")
browser_workflows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser_workflows)


class BrowserFixtureSafety(unittest.TestCase):
    def test_output_never_overwrites_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "keep.txt"
            sentinel.write_text("untouched")
            with self.assertRaises(FileExistsError):
                browser_workflows.new_output(root)
            self.assertEqual(sentinel.read_text(), "untouched")

    def test_dirty_verification_sources_cannot_claim_a_clean_run(self):
        with patch.object(browser_workflows, "run", side_effect=[Mock(stdout=b"revision\n"), Mock(stdout=b" M makervault/api/main.py\n")]):
            with self.assertRaisesRegex(ValueError, "Commit verification"):
                browser_workflows.source_identity()

    def run_fixture(self, fail_with=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            certificate = root / "server.crt"
            certificate.write_text("fixture")
            stack = Mock(config={"AUTH_USERNAME": "fixture", "AUTH_PASSWORD": "fixture"},
                         origin="https://vault.example.test:12345", certificate=certificate)
            def execute(args, **kwargs):
                if args[:2] == ["docker", "run"] and fail_with:
                    raise fail_with
                return subprocess.CompletedProcess(args, 0, b"", b"")
            with patch.object(browser_workflows, "DisposableStack", return_value=stack), patch.object(browser_workflows, "run", side_effect=execute) as command:
                if fail_with:
                    with self.assertRaises(type(fail_with)):
                        browser_workflows.run_case(root, output, {"api": "api", "web": "web"}, "browser", "organization", "chromium")
                else:
                    result = browser_workflows.run_case(root, output, {"api": "api", "web": "web"}, "browser", "organization", "chromium")
                    self.assertEqual(result["status"], "failed")  # Exit zero without evidence is not a pass.
                stack.close.assert_called_once()
                cleanup = command.call_args_list[-1].args[0]
                self.assertEqual(cleanup[:3], ["docker", "rm", "-f"])
                self.assertTrue(cleanup[3].startswith("mv-g13-browser-"))

    def test_missing_report_is_not_a_pass_and_owned_container_is_cleaned(self):
        self.run_fixture()

    def test_timeout_still_cleans_owned_container_and_stack(self):
        self.run_fixture(subprocess.TimeoutExpired("docker", 600))
