"""The opt-in privileged BTRFS snapshot sidecar (Mf-o6si).

BTRFS cannot take a snapshot without ``CAP_SYS_ADMIN``, so this helper is a
separate, deliberately tiny container that holds the capability and nothing
else. The API keeps running unprivileged and talks to it over the compose
network. Without the helper the API degrades cleanly: it still reports
``btrfs_subvol`` as the detected method, reports it unusable, and never opens a
socket to this process.

Four routes exist -- ``GET /health``, ``GET /snapshots``, ``POST /snapshots``
and ``DELETE /snapshots/<name>`` -- and the only client-supplied field in the
whole API is the snapshot name. ``guard`` owns every rule about that name, so the
``Sidecar`` methods below carry the behaviour and ``Handler`` is a thin HTTP
shell over them; the tests drive ``Sidecar`` directly and never open a socket.

The server refuses to boot without ``SNAPSHOT_BTRFS_SIDECAR_TOKEN``: it is
reachable by anything on the compose network, and an unauthenticated helper
would let any container snapshot or delete at will. It also refuses to boot when
``btrfs subvolume show <mount>`` fails, because that is the only proof the bind
mount really is the subvolume it is supposed to be. Every command is an argv list
through ``subprocess.run`` with ``shell=False``, the token is compared with
``hmac.compare_digest``, and the token is never logged, echoed or included in a
response.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import guard

TOKEN_ENV = "SNAPSHOT_BTRFS_SIDECAR_TOKEN"
MOUNT_ENV = "SNAPSHOT_BTRFS_SIDECAR_MOUNT"
PORT_ENV = "SNAPSHOT_BTRFS_SIDECAR_PORT"

DEFAULT_MOUNT = "/library"
DEFAULT_PORT = 8765
BIND_HOST = "0.0.0.0"

# The only accepted body is ``{"name": "<name>"}``; anything larger is abuse of
# a route whose entire payload is one 40-character string.
MAX_BODY_BYTES = 4096

EXIT_REFUSED = 2

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

logger = logging.getLogger("snapshot-sidecar")


class BootError(RuntimeError):
    """The sidecar refuses to start: no token, a bad mount, or an unusable store."""


class SidecarError(RuntimeError):
    """A request the sidecar answers with ``status``; the message is client-safe."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def run_btrfs(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one ``btrfs`` command as an argv list, without a shell."""
    return subprocess.run(list(argv), capture_output=True, text=True, check=False, shell=False)


class Sidecar:
    """The helper's whole behaviour: containment, auth, listing and the two verbs."""

    def __init__(self, mount: str | Path, token: str, runner: Runner = run_btrfs) -> None:
        self.mount = guard.mount_root(mount)
        self.store = self.mount / guard.STORE_DIRNAME
        self.token = token
        self.runner = runner

    # --- boot ---------------------------------------------------------------

    def ensure_store(self) -> None:
        """Create ``<mount>/.snap`` when it is missing; never modify an existing one."""
        if self.store.is_dir():
            return
        try:
            self.store.mkdir()
        except OSError as error:
            raise BootError(f"could not create the snapshot store {self.store}: {error}") from error
        logger.info("created the snapshot store %s", self.store)

    # --- auth ---------------------------------------------------------------

    def authorised(self, header: str | None) -> bool:
        """True only for ``Authorization: Bearer <token>`` with the exact token."""
        if not self.token or not header:
            return False
        scheme, separator, value = header.partition(" ")
        if not separator or scheme.lower() != "bearer":
            return False
        candidate = value.strip()
        if not candidate:
            return False
        return hmac.compare_digest(candidate.encode(), self.token.encode())

    # --- read-only answers --------------------------------------------------

    def health(self) -> dict[str, object]:
        """The liveness answer: no secret, and nothing that can fail."""
        return {
            "state": "ready",
            "mount": str(self.mount),
            "store": str(self.store),
            "store_exists": self.store.is_dir(),
            "snapshots": len(self.list_snapshots()),
        }

    def list_snapshots(self) -> list[str]:
        """The names in the store that the guard accepts, oldest first.

        A plain ``os.scandir`` with nothing executed: only real directories whose
        name passes the guard count, so a stray file, a symlink or a directory
        another tool left behind is invisible and can never be deleted through
        this API. A missing store is an empty list, not an error.
        """
        try:
            entries = list(os.scandir(self.store))
        except FileNotFoundError:
            return []
        names = (entry.name for entry in entries if entry.is_dir(follow_symlinks=False) and guard.valid_name(entry.name))
        return sorted(names)

    # --- the two verbs ------------------------------------------------------

    def create(self, payload: object) -> str:
        """Take one read-only snapshot of the mount; return the name it wrote.

        The name is the only accepted field, and it is validated by ``guard``
        after the body has been narrowed to exactly one key, so no other
        client-supplied value can influence the command.
        """
        name = self.name_from(payload)
        target = guard.snapshot_path(self.mount, name)
        self.require_success(self.runner(guard.create_argv(self.mount, name)), "create", name, conflict_on_exists=True)
        logger.info("created the snapshot %s", target)
        return name

    def delete(self, name: object) -> None:
        """Remove exactly one snapshot; a name that is not there is a 404."""
        target = guard.snapshot_path(self.mount, name)
        if not target.is_dir():
            raise SidecarError(404, f"the snapshot {target.name!r} does not exist")
        self.require_success(self.runner(guard.delete_argv(self.mount, name)), "delete", target.name, conflict_on_exists=False)
        logger.info("deleted the snapshot %s", target)

    # --- shared helpers -----------------------------------------------------

    @staticmethod
    def name_from(payload: object) -> str:
        """The one ``name`` field of a request body, and nothing else."""
        if not isinstance(payload, dict):
            raise SidecarError(400, "the request body must be a JSON object carrying one key, name")
        extra = sorted(set(payload) - {"name"})
        if extra:
            raise SidecarError(400, f"the request body carries the unexpected key {extra[0]!r}; name is the only accepted field")
        name = payload.get("name")
        if not isinstance(name, str):
            raise SidecarError(400, "the request body must carry a string name")
        return name

    @staticmethod
    def require_success(
        result: subprocess.CompletedProcess[str],
        verb: str,
        name: str,
        *,
        conflict_on_exists: bool,
    ) -> None:
        """Map one btrfs failure onto the documented status, with a message only."""
        if result.returncode == 0:
            return
        message = (result.stderr or "").strip() or (result.stdout or "").strip() or f"btrfs exited {result.returncode}"
        lowered = message.lower()
        if "already exists" in lowered:
            raise SidecarError(409, f"a snapshot named {name!r} already exists")
        if not conflict_on_exists and ("no such file" in lowered or "not found" in lowered):
            raise SidecarError(404, f"the snapshot {name!r} does not exist")
        raise SidecarError(500, f"btrfs could not {verb} the snapshot {name!r}: {message}")


class Handler(BaseHTTPRequestHandler):
    """Routing and JSON only: every rule lives in ``Sidecar`` or ``guard``."""

    @property
    def sidecar(self) -> Sidecar:
        # ``self.server`` is always the ``SidecarServer`` built in ``main``.
        return self.server.sidecar  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def do_DELETE(self) -> None:
        self.dispatch("DELETE")

    def dispatch(self, method: str) -> None:
        try:
            status, payload = self.route(method)
        except guard.GuardError as error:
            self.respond(400, {"error": str(error)})
        except SidecarError as error:
            self.respond(error.status, {"error": str(error)})
        except Exception:
            # A bug must be a 500 with a generic message, never a traceback on the
            # wire and never a half-sent response.
            logger.exception("unhandled error while serving %s", self.path)
            self.respond(500, {"error": "the sidecar failed to handle the request"})
        else:
            self.respond(status, payload)

    def route(self, method: str) -> tuple[int, dict[str, object] | None]:
        """The one place routes are decided; raises instead of returning an error."""
        if not self.sidecar.authorised(self.headers.get("Authorization")):
            raise SidecarError(401, "a valid bearer token is required")

        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self.require_method(method, "GET")
            return 200, self.sidecar.health()
        if path == "/snapshots":
            if method == "GET":
                return 200, {"snapshots": self.sidecar.list_snapshots()}
            if method == "POST":
                return 201, {"name": self.sidecar.create(self.body())}
            raise SidecarError(405, f"POST or GET is required for {path}, not {method}")
        if path.startswith("/snapshots/"):
            self.require_method(method, "DELETE")
            name = unquote(path[len("/snapshots/") :])
            self.sidecar.delete(name)
            return 204, None
        raise SidecarError(404, f"there is no route {path}")

    def body(self) -> object:
        """The request body as JSON; a body that is not JSON is a 400."""
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise SidecarError(400, "Content-Length is not a number") from None
        if length <= 0:
            raise SidecarError(400, "the request body must be a JSON object carrying one key, name")
        if length > MAX_BODY_BYTES:
            raise SidecarError(413, f"the request body is larger than {MAX_BODY_BYTES} bytes")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SidecarError(400, f"the request body is not JSON: {error}") from error

    @staticmethod
    def require_method(method: str, expected: str) -> None:
        if method != expected:
            raise SidecarError(405, f"{expected} is required, not {method}")

    def respond(self, status: int, payload: dict[str, object] | None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class SidecarServer(ThreadingHTTPServer):
    """The threaded HTTP server, carrying the sidecar the handler delegates to."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], sidecar: Sidecar) -> None:
        super().__init__(address, Handler)
        self.sidecar = sidecar


def boot(mount: str, token: str, runner: Runner = run_btrfs) -> Sidecar:
    """Refuse an unusable configuration, prove the mount, prepare the store.

    ``main`` turns a ``BootError`` into a non-zero exit, so the container fails
    loudly instead of starting a helper that can delete the wrong thing.
    """
    if not token or not token.strip():
        raise BootError(f"{TOKEN_ENV} is empty; the sidecar refuses to start without a token")

    sidecar = Sidecar(mount, token, runner)
    result = runner(guard.show_argv(sidecar.mount))
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip() or f"btrfs exited {result.returncode}"
        raise BootError(f"the mount {sidecar.mount} is not a btrfs subvolume: {detail}")

    logger.info("the mount %s is a btrfs subvolume", sidecar.mount)
    sidecar.ensure_store()
    return sidecar


def port_from_env() -> int:
    """The listen port; ``SNAPSHOT_BTRFS_SIDECAR_PORT`` overrides the default."""
    raw = os.environ.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise BootError(f"{PORT_ENV} is not a port number: {raw!r}") from None
    if not 1 <= port <= 65535:
        raise BootError(f"{PORT_ENV} is not a port number: {raw!r}")
    return port


def main() -> int:
    """Read the environment, boot, and serve until interrupted."""
    logging.basicConfig(level=logging.INFO, format="[snapshot-sidecar] %(message)s", stream=sys.stderr)
    mount = os.environ.get(MOUNT_ENV, "").strip() or DEFAULT_MOUNT
    token = os.environ.get(TOKEN_ENV, "")

    try:
        port = port_from_env()
        sidecar = boot(mount, token)
    except BootError as error:
        logger.error("refusing to start: %s", error)
        return EXIT_REFUSED

    server = SidecarServer((BIND_HOST, port), sidecar)
    logger.info("serving the mount %s on %s:%s", sidecar.mount, BIND_HOST, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("interrupted")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
