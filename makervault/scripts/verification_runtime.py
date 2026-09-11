"""Disposable production-Compose/HTTPS fixtures. Never targets an existing project."""
from __future__ import annotations

import hashlib
import http.cookiejar
import http.client
import json
import os
from pathlib import Path
import ssl
import socket
import signal
import subprocess
import struct
import time
import zlib
import urllib.error
import urllib.request
from uuid import uuid4
from container_privileges import process_privileges

APP = Path(__file__).resolve().parents[1]
REPO = APP.parent
SCHEMA = 17  # An explicit assertion, not dynamically accepted from the tested image.
HOST = "vault.example.test"


def install_signal_handlers():
    def interrupted(signum, frame):
        raise KeyboardInterrupt("Disposable verification interrupted")
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)


def run(args, *, env=None, data=None, check=True):
    result = subprocess.run([str(arg) for arg in args], input=data, capture_output=True,
                            env=env, timeout=600)
    if check and result.returncode:
        # Arguments/environment and successful response bodies can contain fixture secrets.
        raise RuntimeError(f"Verification command failed ({Path(str(args[0])).name}, exit {result.returncode}): "
                           + result.stderr.decode(errors="replace")[-3000:])
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LoopbackHTTPSConnection(http.client.HTTPSConnection):
    """Resolve only the fixture DNS name locally; retain TLS hostname verification."""
    def connect(self):
        if self.host != HOST:
            raise ValueError("Only the disposable fixture host may use loopback resolution")
        sock = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class FixtureHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(LoopbackHTTPSConnection, req, context=self._context)


class SessionClient:
    def __init__(self, origin: str, certificate: Path, jar=None):
        self.origin = origin
        self.base = origin + "/api"
        self.jar = jar if jar is not None else http.cookiejar.CookieJar()
        self.csrf = None
        context = ssl.create_default_context(cafile=str(certificate))
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), FixtureHTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect(),
        )

    def request(self, path, *, method="GET", body=None, data=None, headers=None, expected=200):
        assert path.startswith("/") and not path.startswith("//"), "Invalid fixture API path"
        request_headers = {}
        if method not in {"GET", "HEAD", "OPTIONS"}:
            request_headers["Origin"] = self.origin
            if self.csrf:
                request_headers["X-CSRF-Token"] = self.csrf
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers=request_headers)
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            assert response.status == expected, f"{method} {path.split('?')[0]}: HTTP {response.status}, expected {expected}"
            if "application/json" in response.headers.get("Content-Type", ""):
                return json.loads(content)
            return content

    def login(self, username, password):
        result = self.request("/login", method="POST", body={"username": username, "password": password})
        assert "token" not in result and result.get("csrf_token"), "Cookie session required"
        self.csrf = result["csrf_token"]
        session = [cookie for cookie in self.jar if cookie.name == "__Host-makersvault_session"]
        assert len(session) == 1 and session[0].secure and session[0].path == "/"
        assert not session[0].domain_specified and session[0].has_nonstandard_attr("HttpOnly")
        return result

    def upload(self, path, filename, content, mime="model/stl"):
        boundary = "mvfixture" + uuid4().hex
        payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                   f'Content-Type: {mime}\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self.request(path, method="POST", data=payload,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})


def fixture_certificates(directory: Path):
    """Separate disposable trust anchor and server leaf; never serve a CA as a leaf."""
    ca, ca_key = directory / "ca.crt", directory / "ca.key"
    certificate, key = directory / "server.crt", directory / "server.key"
    csr, extensions = directory / "server.csr", directory / "server.ext"
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=MakersVault disposable fixture CA",
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", ca_key, "-out", ca])
    ca_key.chmod(0o600)
    run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
         "-subj", f"/CN={HOST}", "-keyout", key, "-out", csr])
    key.chmod(0o600)
    extensions.write_text("basicConstraints=critical,CA:FALSE\n"
                          "keyUsage=critical,digitalSignature,keyEncipherment\n"
                          "extendedKeyUsage=serverAuth\n"
                          f"subjectAltName=DNS:{HOST}\n")
    run(["openssl", "x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key,
         "-set_serial", "0x" + uuid4().hex, "-days", "1", "-extfile", extensions,
         "-out", certificate])
    return ca, certificate, key


class DisposableStack:
    def __init__(self, directory: Path, api_image: str, web_image: str, *, username="gate13", password="gate13-fixture-password", imports=None):
        self.directory = directory
        directory.mkdir(mode=0o700)
        self.project = "mv-g13-" + uuid4().hex
        self.env_file = directory / "fixture.env"
        self.overlay = directory / "https.json"
        self.certificate, self.server_certificate, key = fixture_certificates(directory)
        if imports is None:
            imports = directory / "imports"
            imports.mkdir()
        self.config = {
            "API_IMAGE": api_image, "WEB_IMAGE": web_image, "AUTH_USERNAME": username,
            "AUTH_PASSWORD": password, "AUTH_SECRET": uuid4().hex + uuid4().hex,
            "API_PORT": "127.0.0.1:0", "WEB_PORT": "127.0.0.1:0",
            "PUBLIC_URL": f"https://{HOST}", "TRUSTED_HOSTS": HOST,
            "CORS_ORIGINS": f"https://{HOST}", "VITE_API_URL": "",
            "WEBAUTHN_RP_ID": HOST, "WEBAUTHN_ORIGIN": f"https://{HOST}",
            "IMPORT_MOUNT_PATH": "/imports", "IMPORT_MOUNT_PATH_HOST": str(imports),
            "IMPORT_MOUNT_ON_STARTUP": "false", "IMPORT_MOUNT_COPY": "false",
            "PUID": str(os.getuid()), "PGID": str(os.getgid()),
        }
        self.write_config()
        (directory / "nginx.conf").write_text("""pid /tmp/fixture-nginx.pid;
error_log /dev/stderr warn;
events {}
http {
  access_log off;
  client_body_temp_path /tmp/fixture-body;
  proxy_temp_path /tmp/fixture-proxy;
  fastcgi_temp_path /tmp/fixture-fastcgi;
  uwsgi_temp_path /tmp/fixture-uwsgi;
  scgi_temp_path /tmp/fixture-scgi;
  server {
    listen 8443 ssl;
    ssl_certificate /tls/server.crt;
    ssl_certificate_key /tls/server.key;
    client_max_body_size 513m;
    resolver 127.0.0.11 valid=1s ipv6=off;
    location / {
      set $upstream http://web:5173;
      proxy_pass $upstream$request_uri;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto https;
    }
  }
}
""")
        self.overlay.write_text(json.dumps({"services": {"tls": {
            "image": web_image, "user": f"{os.getuid()}:{os.getgid()}",
            "entrypoint": ["nginx", "-c", "/tls/nginx.conf", "-g", "daemon off;"],
            "volumes": [f"{directory / 'nginx.conf'}:/tls/nginx.conf:ro",
                        f"{self.server_certificate}:/tls/server.crt:ro",
                        f"{key}:/tls/server.key:ro"], "ports": ["127.0.0.1::8443"],
        }}}))
        self.origin = None

    @property
    def environment(self):
        return {**os.environ, **self.config}

    def write_config(self):
        self.env_file.write_text("".join(f"{key}={value}\n" for key, value in self.config.items()))
        self.env_file.chmod(0o600)

    def compose(self, *args, **kwargs):
        return run(["docker", "compose", "--project-name", self.project, "--env-file", self.env_file,
                    "-f", APP / "docker-compose.deploy.yml", "-f", self.overlay, *args],
                   env=self.environment, **kwargs)

    def start(self):
        self.compose("up", "-d", "api", "web", "tls")
        published = self.compose("port", "tls", "8443", check=False)
        if published.returncode:
            logs = self.compose("logs", "--no-color", "--tail", "30", "tls", check=False)
            raise RuntimeError("Disposable TLS proxy did not start: " + logs.stdout.decode(errors="replace"))
        port = published.stdout.decode().strip().rsplit(":", 1)[1]
        self.origin = f"https://{HOST}:" + port
        for setting in ("PUBLIC_URL", "CORS_ORIGINS", "WEBAUTHN_ORIGIN"):
            self.config[setting] = self.origin
        self.write_config()
        self.compose("up", "-d", "--force-recreate", "--no-deps", "api", "web")
        self.wait()

    def wait(self):
        deadline = time.monotonic() + 90
        client = self.client()
        while time.monotonic() < deadline:
            try:
                if client.request("/health")["ok"]:
                    return
            except (OSError, AssertionError):
                time.sleep(1)
        logs = self.compose("logs", "--no-color", "--tail", "20", "api", "web", "tls", check=False)
        raise RuntimeError("Disposable HTTPS instance did not become healthy: " + logs.stdout.decode(errors="replace"))

    def client(self, jar=None):
        return SessionClient(self.origin, self.certificate, jar)

    def stop(self):
        self.compose("stop", "api", "web")

    def offline(self, *args, **kwargs):
        return self.compose("run", "--rm", "-T", "--no-deps", "--entrypoint", "python", "api", *args, **kwargs)

    def snapshot(self):
        return json.loads(self.offline("/app/tests/gate13_fixture.py", "snapshot").stdout)

    def backup(self, archive, revision):
        run([APP / "scripts/backup.sh", "--env-file", self.env_file, "--project-name", self.project,
             "--output", archive, "--release", "development-gate13b", "--source-revision", revision,
             "--leave-stopped"], env=self.environment)

    def restore(self, archive, *, replace=False, check=True):
        return run([APP / "scripts/restore.sh", "--env-file", self.env_file, "--project-name", self.project,
                    "--archive", archive, "--leave-stopped", *(["--replace"] if replace else [])],
                   env=self.environment, check=check)

    def close(self):
        self.compose("down", "--volumes", "--remove-orphans")


def image_identity(image, version, revision):
    metadata = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
    labels = metadata["Config"]["Labels"]
    assert labels["org.opencontainers.image.version"] == version, "Image version mismatch"
    assert labels["org.opencontainers.image.revision"] == revision, "Image revision mismatch"
    return metadata["Id"]


def smoke(stack, version, revision):
    client = stack.client()
    with client.opener.open(stack.origin + "/", timeout=15) as response:
        assert response.status == 200 and "text/html" in response.headers.get("Content-Type", "")
        assert b'id="root"' in response.read(), "Production web application shell missing"
    health = client.request("/health")
    assert health["ok"] and health["auth_required"] and health["version"] == version and health["revision"] == revision
    client.request("/assets", expected=401)
    client.login(stack.config["AUTH_USERNAME"], stack.config["AUTH_PASSWORD"])
    client.request("/folders", method="POST", body={"name": "rejected"},
                   headers={"X-CSRF-Token": "wrong"}, expected=403)
    client.request("/folders", method="POST", body={"name": "rejected"},
                   headers={"Origin": "https://untrusted.invalid"}, expected=403)
    payload = b"solid persistence\nendsolid persistence\n"
    asset = client.upload("/upload", "persistence.stl", payload)
    # Stand in for the browser-generated preview bytes (not a manual-image UI).
    # Exercise native image decode/JPEG persistence under the running API policy.
    def png_chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    png = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack("!2I5B", 2, 2, 8, 2, 0, 0, 0))
           + png_chunk(b"IDAT", zlib.compress(b"\x00\x20\x60\xa0\x20\x60\xa0" * 2)) + png_chunk(b"IEND", b""))
    preview = client.upload(f"/asset/{asset['id']}/thumbnail-generated", "generated.png", png, "image/png")
    assert preview["preview_status"] == "ready" and preview["thumb_url"]
    thumbnail = client.request(preview["thumb_url"])
    assert thumbnail.startswith(b"\xff\xd8"), "Persisted generated preview is not JPEG"
    stack.compose("restart", "api", "web")
    stack.wait()
    assert client.request(asset["url"]) == payload
    assert client.request(preview["thumb_url"]) == thumbnail
    schema = stack.compose("exec", "-T", "api", "python", "-m", "migrations").stdout.decode()
    assert f"schema version: {SCHEMA}" in schema
    privileges = {}
    for service in ("api", "web"):
        assert stack.compose("exec", "-T", service, "stat", "-c", "%u", "/proc/1").stdout.strip() != b"0"
        status = stack.compose("exec", "-T", service, "cat", "/proc/1/status").stdout.decode()
        privileges[service] = process_privileges(status)
        # Nginx worker processes must inherit the same boundary as the master.
        if service == "web":
            children = stack.compose("exec", "-T", service, "cat", "/proc/1/task/1/children").stdout.decode().split()
            assert children, "Nginx worker evidence missing"
            statuses = stack.compose("exec", "-T", service, "cat",
                                     *[f"/proc/{int(pid)}/status" for pid in children]).stdout.decode()
            records = statuses.split("\nName:")
            assert len(records) == len(children), "Nginx worker status count mismatch"
            privileges[service]["workers"] = [process_privileges(record) for record in records]
    client.request("/logout", method="POST", expected=204)
    client.request("/session", expected=401)
    return {"schema": SCHEMA, "https_secure_cookie_csrf": True, "restart_bytes": hashlib.sha256(payload).hexdigest(),
            "logout_revocation": True, "non_root_api_web": True, "process_privileges": privileges,
            "generated_preview_restart_sha256": hashlib.sha256(thumbnail).hexdigest()}
