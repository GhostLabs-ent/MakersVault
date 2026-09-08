import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification_runtime import DisposableStack, HOST, fixture_certificates, run


class FixtureCertificates(unittest.TestCase):
    def test_server_leaf_and_hostname_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ca, leaf, key = fixture_certificates(root)
            self.assertNotEqual(ca.read_bytes(), leaf.read_bytes())
            details = run(["openssl", "x509", "-in", leaf, "-noout", "-text"]).stdout.decode()
            self.assertIn("CA:FALSE", details)
            self.assertIn("TLS Web Server Authentication", details)
            self.assertIn("DNS:" + HOST, details)
            verify = ["openssl", "verify", "-CAfile", ca, "-purpose", "sslserver", "-verify_hostname"]
            run([*verify, HOST, leaf])
            rejected = run([*verify, "127.0.0.1", leaf], check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b"hostname mismatch", rejected.stderr)
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "ca.key").stat().st_mode & 0o777, 0o600)

    def test_another_fixture_ca_cannot_authenticate_this_server(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _, leaf, _ = fixture_certificates(Path(first))
            other_ca, _, _ = fixture_certificates(Path(second))
            rejected = run(["openssl", "verify", "-CAfile", other_ca, leaf], check=False)
            self.assertNotEqual(rejected.returncode, 0)

    def test_tls_container_does_not_mount_signing_key_or_fixture_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            stack = DisposableStack(Path(temporary) / "stack", "api", "web")
            mounts = json.loads(stack.overlay.read_text())["services"]["tls"]["volumes"]
            self.assertEqual(len(mounts), 3)
            self.assertEqual({entry.split(":")[1] for entry in mounts},
                             {"/tls/server.crt", "/tls/server.key", "/tls/nginx.conf"})
            self.assertEqual(stack.certificate.name, "ca.crt")
            for entry in mounts:
                self.assertTrue(Path(entry.split(":")[0]).is_file())
                self.assertNotIn("ca.key", entry)
                self.assertNotIn("fixture.env", entry)
