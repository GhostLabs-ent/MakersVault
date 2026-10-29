"""The BTRFS sidecar provider and its probe, with no Docker and no real btrfs.

Everything here is in-image and hermetic: the transport is either an injected
recording stub or a monkeypatched ``urllib.request.urlopen``, snapshots are real
directories under ``tmp_path``, and the audit assertions run against the
migrated test database. Nothing opens a socket, runs ``btrfs``, or needs a
mounted btrfs volume, so this module gives the same evidence inside the API
container as on a host.

What is covered here: the transport contract (status mapping, bearer token, JSON
body), the snapshot-name guard and what the wire carries, the disabled and
unreachable verdicts, and the three-clause docs/manifest invariant for the two
opt-in keys.

What is not covered here is host-only and documented as a manual procedure in
``makervault/docs/architecture/CONFIGURATION.md``, "Snapshots (BTRFS sidecar)":
that a real sidecar with ``CAP_SYS_ADMIN`` takes a real subvolume snapshot of a
real btrfs mount, that the read-only ``.snap/<name>`` view is browsable, and that
a real deployment accepts the token. Those need a real btrfs filesystem, so they
are checked by hand, never in CI.
"""

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest
import yaml
from sqlmodel import Session, select

import audit
import config
import snapshot_btrfs
import snapshots
import storage_capabilities
from db import engine
from migrations import run_migrations
from models import AuditEvent

BASE_URL = "http://sidecar.test:8765"
TOKEN = "s3cr3t-sidecar-token"
CTX = audit.AuditContext(
    actor=audit.Actor("tester", "admin", "user", None),
    request_id="req-snapshot-btrfs",
    method="POST",
    path="/snapshots",
)
FROZEN = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
MANUAL_NAME = "20260101T000000Z-manual-abc123"
FAILING_NAME = snapshots.snapshot_name(snapshots.SnapshotReason.MANUAL, FROZEN, suffix="f00000")
SIDECAR_KEYS = ("SNAPSHOT_BTRFS_SIDECAR_URL", "SNAPSHOT_BTRFS_SIDECAR_TOKEN")
HOSTILE_NAMES = (
    "%002f",
    "#`",
    "tank/other@x",
    "..",
    "-r",
    "../../etc",
    "20260101T000000Z-manual-ZZZZZZ",
    "20260101T000000Z-manual-ab,c12",
)


# --- fixtures and helpers ---------------------------------------------------


@pytest.fixture(autouse=True)
def database():
    """Every test starts from the migrated test database the audit rows need."""
    run_migrations(engine)
    yield


def sidecar_configured(monkeypatch: pytest.MonkeyPatch, url: str = BASE_URL) -> str:
    """Point the provider at a sidecar with a token, overriding the environment."""
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", url)
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_TOKEN", TOKEN)
    return url


def tree_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    return root


def with_store(root: Path) -> Path:
    """The base provider never creates ``.snap``; tests that reach the wire do."""
    store = root / snapshots.SNAPSHOT_DIRNAME
    store.mkdir()
    return store


def provider_with(root: Path, sidecar) -> snapshot_btrfs.BtrfsProvider:
    return snapshot_btrfs.BtrfsProvider(root, policy=snapshots.RetentionPolicy(), call=sidecar)


def audit_rows(target: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.target == target)))


def env_example_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, _ = line.partition("=")
        if separator:
            keys.add(name.strip())
    return keys


class FakeSidecar:
    """A recording transport that also writes the snapshot directories.

    It answers the shared contract as a real sidecar would: POST creates the
    read-only subvolume directory, DELETE removes it, and every call is recorded
    so the wire shape can be asserted. ``status`` overrides the answer for the
    failure-mapping tests.
    """

    def __init__(self, store: Path, *, status: Optional[int] = None, body: str = "") -> None:
        self.store = store
        self.calls: list[tuple[str, str, Optional[dict[str, str]]]] = []
        self.status = status
        self.body = body

    def __call__(self, method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
        self.calls.append((method, path, payload))
        if self.status is not None:
            return self.status, self.body
        if method == "POST":
            assert payload is not None
            (self.store / payload["name"]).mkdir()
            return 201, "{}"
        if method == "DELETE":
            (self.store / path.rsplit("/", 1)[-1]).rmdir()
            return 200, "{}"
        raise AssertionError(f"unexpected sidecar call: {method} {path}")


def forbidden_transport(method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
    raise AssertionError(f"the transport must not be called here, but was called with {method} {path}")


def forbidden_socket(*args, **kwargs):
    raise AssertionError("a socket was opened where none may be")


class FakeResponse:
    """Just enough of an ``http.client`` response for ``http_call``."""

    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


# --- AC-1: create, list, delete and the audit rows --------------------------


def test_create_list_delete_round_trip_and_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    store = with_store(root)
    sidecar_configured(monkeypatch)
    sidecar = FakeSidecar(store)
    provider = provider_with(root, sidecar)

    assert provider.snapshot_dir == (root / snapshots.SNAPSHOT_DIRNAME).resolve()

    created = provider.create(ctx=CTX)
    name = created.snapshot.name
    assert [snapshot.name for snapshot in provider.list()] == [name]

    create_rows = [row for row in audit_rows(name) if row.request_id == CTX.request_id]
    assert [row.action for row in create_rows] == [audit.SNAPSHOT_CREATE]
    assert json.loads(create_rows[0].detail_json) == {"method": "btrfs_subvol", "pruned": 0, "reason": "manual"}

    provider.delete(name, ctx=CTX)
    delete_rows = [row for row in audit_rows(name) if row.request_id == CTX.request_id]
    assert [row.action for row in delete_rows] == [audit.SNAPSHOT_CREATE, audit.SNAPSHOT_DELETE]
    assert json.loads(delete_rows[-1].detail_json) == {"method": "btrfs_subvol"}
    assert provider.list() == []


def test_a_failed_wire_call_writes_no_audit_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    store = with_store(root)
    sidecar_configured(monkeypatch)
    monkeypatch.setattr(snapshots, "snapshot_name", lambda reason, now: FAILING_NAME)
    provider = provider_with(root, FakeSidecar(store, status=500, body="the sidecar is unwell"))

    with pytest.raises(snapshots.SnapshotUnavailable):
        provider.create(ctx=CTX)

    assert audit_rows(FAILING_NAME) == []


# --- status mapping ---------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (409, snapshots.SnapshotExists),
        (404, snapshots.SnapshotNotFound),
        (500, snapshots.SnapshotUnavailable),
        (503, snapshots.SnapshotUnavailable),
        (418, snapshots.SnapshotError),
        (400, snapshots.SnapshotError),
    ],
)
def test_the_wire_status_maps_to_the_template_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, expected: type
) -> None:
    root = tree_root(tmp_path)
    sidecar_configured(monkeypatch)
    provider = provider_with(root, FakeSidecar(with_store(root), status=status, body="answer"))

    with pytest.raises(expected) as caught:
        provider._call("GET", "/snapshots")

    assert type(caught.value) is expected


def test_a_transport_error_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    sidecar_configured(monkeypatch)

    def refuse(method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
        raise urllib.error.URLError("connection refused")

    provider = provider_with(root, refuse)

    with pytest.raises(snapshots.SnapshotUnavailable) as caught:
        provider._call("GET", "/health")

    assert "unreachable" in str(caught.value)


def test_a_malformed_url_is_unavailable_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    with_store(root)
    monkeypatch.setattr(snapshots, "snapshot_name", lambda reason, now: FAILING_NAME)
    monkeypatch.setattr(socket, "socket", forbidden_socket)
    provider = snapshot_btrfs.BtrfsProvider(root, policy=snapshots.RetentionPolicy())

    # ``sidecar:8765`` is the operator typo from the ticket: urllib reads
    # ``sidecar`` as a scheme and answers URLError, while a URL with no colon at
    # all makes ``urllib.request.Request`` raise ValueError before any socket.
    # Both are the provider's "unreachable", never a bare crash.
    for url in ("sidecar:8765", "sidecar"):
        sidecar_configured(monkeypatch, url=url)

        with pytest.raises(snapshots.SnapshotUnavailable) as caught:
            provider.create(ctx=CTX)

        assert "unreachable" in str(caught.value)
        assert audit_rows(FAILING_NAME) == []


# --- the wire shape ---------------------------------------------------------


def test_the_wire_carries_a_name_and_nothing_else(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    store = with_store(root)
    sidecar_configured(monkeypatch)
    sidecar = FakeSidecar(store)
    provider = provider_with(root, sidecar)

    created = provider.create(ctx=CTX)
    name = created.snapshot.name
    provider.delete(name)

    posts = [call for call in sidecar.calls if call[0] == "POST"]
    deletes = [call for call in sidecar.calls if call[0] == "DELETE"]
    assert len(posts) == 1
    assert posts[0][1] == "/snapshots"
    assert set(posts[0][2]) == {"name"}
    assert posts[0][2]["name"] == name
    assert [call[1] for call in deletes] == [f"/snapshots/{name}"]


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_a_hostile_name_is_refused_before_any_wire_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    root = tree_root(tmp_path)
    store = with_store(root)
    sidecar_configured(monkeypatch)
    sidecar = FakeSidecar(store)
    provider = provider_with(root, sidecar)

    with pytest.raises(snapshots.SnapshotPathError):
        provider.delete(name)
    with pytest.raises(snapshots.SnapshotPathError):
        provider._materialise(provider.snapshot_dir / name)

    assert sidecar.calls == []


# --- the verdict ------------------------------------------------------------


def test_disabled_opens_no_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    with_store(root)
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", "")
    monkeypatch.setattr(snapshot_btrfs, "http_call", forbidden_transport)
    monkeypatch.setattr(socket, "socket", forbidden_socket)

    probe = snapshot_btrfs.probe_sidecar()

    assert probe.state is snapshot_btrfs.BtrfsState.DISABLED
    assert "disabled" in probe.reason
    assert "CONFIGURATION.md" in probe.reason

    calls: list[tuple[str, str, Optional[dict[str, str]]]] = []

    def recorder(method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
        calls.append((method, path, payload))
        raise AssertionError("a disabled provider must not call its transport")

    provider = provider_with(root, recorder)
    with pytest.raises(snapshots.SnapshotUnavailable) as create_error:
        provider.create()
    with pytest.raises(snapshots.SnapshotUnavailable):
        provider.delete(MANUAL_NAME)

    assert calls == []
    assert "disabled" in str(create_error.value)


@pytest.mark.parametrize(
    "url,answer,expected,word",
    [
        ("", None, snapshot_btrfs.BtrfsState.DISABLED, "disabled"),
        (BASE_URL, urllib.error.URLError("no route"), snapshot_btrfs.BtrfsState.UNREACHABLE, "unreachable"),
        (BASE_URL, (200, '{"state": "starting"}'), snapshot_btrfs.BtrfsState.UNREACHABLE, "unreachable"),
        (
            BASE_URL,
            (200, '{"state": "ready", "store": "/library/.snap", "store_exists": false}'),
            snapshot_btrfs.BtrfsState.READY,
            "ready",
        ),
    ],
    ids=["disabled", "unreachable-error", "unreachable-not-ready", "ready"],
)
def test_the_probe_has_exactly_three_states(
    monkeypatch: pytest.MonkeyPatch, url: str, answer, expected: snapshot_btrfs.BtrfsState, word: str
) -> None:
    assert {state.value for state in snapshot_btrfs.BtrfsState} == {"disabled", "unreachable", "ready"}
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", url)
    # The same path on both sides: the one shape where the store check can compare
    # the two literals, so the ready row pins the store contract without a tree.
    monkeypatch.setattr(snapshots, "library_root", lambda: Path("/library"))

    def answer_call(method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(snapshot_btrfs, "http_call", answer_call)

    probe = snapshot_btrfs.probe_sidecar()

    assert probe.state is expected
    assert word in probe.reason


def test_the_probe_never_raises_on_a_garbage_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar_configured(monkeypatch)
    monkeypatch.setattr(snapshot_btrfs, "http_call", lambda method, path, payload=None: (200, "not json"))

    probe = snapshot_btrfs.probe_sidecar()

    assert probe.state is snapshot_btrfs.BtrfsState.UNREACHABLE
    assert "unreachable" in probe.reason


def test_a_sidecar_writing_a_store_the_api_cannot_read_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The deployment B1 found: the sidecar serves /library from a host directory
    # the API never mounts, so it writes /library/.snap while this API's library
    # root has no store at all. Without the store check this reports ready, every
    # create then succeeds, and list() stays empty forever.
    root = tree_root(tmp_path)
    sidecar_configured(monkeypatch)
    monkeypatch.setattr(
        snapshot_btrfs,
        "http_call",
        lambda method, path, payload=None: (
            200,
            json.dumps({"state": "ready", "mount": "/library", "store": "/library/.snap", "store_exists": True}),
        ),
    )

    probe = snapshot_btrfs.probe_sidecar(root)

    assert probe.state is snapshot_btrfs.BtrfsState.UNREACHABLE
    assert "/library/.snap" in probe.reason
    assert str(root / snapshots.SNAPSHOT_DIRNAME) in probe.reason
    assert "CONFIGURATION.md" in probe.reason


def test_one_host_directory_mounted_at_two_paths_is_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The documented override: the sidecar's /library and the API's FILE_STORAGE
    # are one host directory, so the store the sidecar created is visible here
    # even though the two containers spell the path differently.
    root = tree_root(tmp_path)
    with_store(root)
    sidecar_configured(monkeypatch)
    monkeypatch.setattr(
        snapshot_btrfs,
        "http_call",
        lambda method, path, payload=None: (
            200,
            json.dumps({"state": "ready", "mount": "/library", "store": "/library/.snap", "store_exists": True}),
        ),
    )

    probe = snapshot_btrfs.probe_sidecar(root)

    assert probe.state is snapshot_btrfs.BtrfsState.READY


# --- http_call --------------------------------------------------------------


def test_http_call_sends_a_bearer_token_and_a_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar_configured(monkeypatch)
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(200, "{}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    status, body = snapshot_btrfs.http_call("POST", "/snapshots", {"name": MANUAL_NAME})

    request = captured["request"]
    assert status == 200
    assert body == "{}"
    assert request.full_url == f"{BASE_URL}/snapshots"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert json.loads(request.data.decode("utf-8")) == {"name": MANUAL_NAME}
    assert captured["timeout"] == config.SNAPSHOT_BTRFS_TIMEOUT_SECONDS


# --- construction -----------------------------------------------------------


def test_construction_is_probe_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    monkeypatch.setattr(snapshot_btrfs, "http_call", forbidden_transport)
    monkeypatch.setattr(socket, "socket", forbidden_socket)

    provider = snapshots.provider_for(root, storage_capabilities.BTRFS_SUBVOL, policy=snapshots.RetentionPolicy())

    assert isinstance(provider, snapshot_btrfs.BtrfsProvider)
    assert provider.method == storage_capabilities.BTRFS_SUBVOL
    assert provider.snapshot_dir == (root / snapshots.SNAPSHOT_DIRNAME).resolve()


# --- the docs and manifest invariant ----------------------------------------


def test_the_sidecar_keys_are_documented_and_not_forwarded() -> None:
    api_root = Path(__file__).resolve().parents[1]
    env_keys = env_example_keys(api_root / ".env.example")
    for key in SIDECAR_KEYS:
        assert key in env_keys, f".env.example does not document {key}"

    makervault_root = api_root.parent
    configuration = makervault_root / "docs" / "architecture" / "CONFIGURATION.md"
    manifest = makervault_root / "docker-compose.deploy.yml"
    if not configuration.exists() or not manifest.exists():
        pytest.skip("host-only: makervault/docs and the deploy manifest are outside the API image build context")

    rows = [line for line in configuration.read_text(encoding="utf-8").splitlines() if line.startswith("| `")]
    for key in SIDECAR_KEYS:
        assert any(row.startswith(f"| `{key}`") for row in rows), f"CONFIGURATION.md has no table row for {key}"

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    environment = data["services"]["api"]["environment"]
    forwarded = {entry.partition("=")[0] for entry in environment}
    for key in SIDECAR_KEYS:
        assert key not in forwarded, f"docker-compose.deploy.yml forwards {key}, which is deliberately opt-in"
