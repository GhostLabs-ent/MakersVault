"""Guard the privileged BTRFS snapshot sidecar, hermetically (Mf-o6si, AC-3).

Host-only: the helper lives in ``curiarium/snapshot-sidecar``, beside the API
directory, and the API image builds from ``curiarium/api`` alone. The helper is
therefore invisible inside the image, so this module skips itself at module
level when ``guard.py`` is absent instead of failing there. It loads the helper
modules with ``importlib`` rather than importing them, because they are not on
the API's import path by design: the sidecar must never depend on the API's
package layout, and the API never imports the helper.

Everything here is hermetic: no Docker, no real btrfs, no real CephFS mount, no
privileged operation and no socket. The mount is a ``tmp_path`` directory and
every command goes to an injected runner that records the argv instead of
running it, which is how the command shape, the containment rules and the
status mapping are pinned. The operator docs
(``curiarium/docs/architecture/CONFIGURATION.md``) are pinned here too, because
this module is the only host-only home for them.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Optional, Sequence

import pytest

import snapshots

SIDECAR_DIR = Path(__file__).resolve().parents[2] / "snapshot-sidecar"
GUARD_PATH = SIDECAR_DIR / "guard.py"
SERVER_PATH = SIDECAR_DIR / "server.py"
CONFIGURATION_DOC = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "CONFIGURATION.md"

# Host-only, and only when BOTH files are missing: a half-deleted helper tree on a
# real checkout must fail loudly instead of skipping.
if not GUARD_PATH.exists() and not SERVER_PATH.exists():
    pytest.skip(
        "the snapshot sidecar guard is host-only (the API image builds from curiarium/api, so "
        "curiarium/snapshot-sidecar/ is absent)",
        allow_module_level=True,
    )


def load_sidecar_module(name: str, path: Path) -> ModuleType:
    """Load a helper module by path; ``snapshot-sidecar`` is not an import root."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so ``server.py``'s own ``import guard`` resolves
    # to the module loaded here rather than to whatever is on sys.path.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guard = load_sidecar_module("guard", GUARD_PATH)
server = load_sidecar_module("snapshot_sidecar_server", SERVER_PATH)

TOKEN = "sidecar-test-token"
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)

HOSTILE_NAMES = (
    "",
    "..",
    "../x",
    "a/b",
    "a\\b",
    "a\0b",
    "-r",
    "/etc/passwd",
    "/library/.snap/x",
    "20260101T000000Z-manual-abc123/../../etc",
    "20260101T000000Z-manual-abc12",
    "20260101T000000Z-manual-abcd12g",
    "20260101T000000Z-whatever-abc123",
    "20260101T000000Z-manual-ab,c12",
)


class RecordingRunner:
    """A btrfs stand-in: records every argv and answers with a canned result."""

    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        recorded = list(argv)
        self.calls.append(recorded)
        return subprocess.CompletedProcess(recorded, self.returncode, self.stdout, self.stderr)


def a_name(reason: snapshots.SnapshotReason = snapshots.SnapshotReason.MANUAL, suffix: str = "abc123") -> str:
    """A name built by the API's own namer, so the guard is tested against it."""
    return snapshots.snapshot_name(reason, STAMP, suffix=suffix)


def booted(tmp_path: Path, runner: Optional[RecordingRunner] = None) -> tuple[server.Sidecar, RecordingRunner]:
    """A sidecar booted against a temporary mount, with only the injected runner."""
    mount = tmp_path.resolve()
    # The boot check itself is asserted in its own test; here it just has to pass,
    # which also creates the store.
    server.boot(str(mount), TOKEN, RecordingRunner())
    recorder = runner or RecordingRunner()
    return server.Sidecar(mount, TOKEN, recorder), recorder


# --- a. name parity with the API -------------------------------------------


def test_the_guard_name_pattern_is_the_api_pattern() -> None:
    assert guard.NAME_RE.pattern == snapshots.NAME_RE.pattern


@pytest.mark.parametrize("reason", list(snapshots.SnapshotReason))
def test_names_the_api_builds_are_accepted(reason: snapshots.SnapshotReason) -> None:
    name = a_name(reason)

    assert snapshots.parse_name(name) is not None
    assert guard.valid_name(name)


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_hostile_names_are_refused_everywhere(name: str, tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    (mount / guard.STORE_DIRNAME).mkdir()

    assert not guard.valid_name(name)
    with pytest.raises(guard.GuardError):
        guard.snapshot_path(mount, name)
    with pytest.raises(guard.GuardError):
        guard.create_argv(mount, name)
    with pytest.raises(guard.GuardError):
        guard.delete_argv(mount, name)


# --- b. containment --------------------------------------------------------


def test_a_valid_name_resolves_inside_the_store(tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    (mount / guard.STORE_DIRNAME).mkdir()
    name = a_name()

    path = guard.snapshot_path(mount, name)

    assert path == mount / guard.STORE_DIRNAME / name
    assert mount in path.parents


def test_a_planted_symlink_cannot_escape_the_mount(tmp_path: Path) -> None:
    mount = (tmp_path / "library").resolve()
    store = mount / guard.STORE_DIRNAME
    store.mkdir(parents=True)
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    name = a_name()
    (store / name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(guard.GuardError):
        guard.snapshot_path(mount, name)


def test_a_symlinked_store_cannot_escape_the_mount(tmp_path: Path) -> None:
    mount = (tmp_path / "library").resolve()
    mount.mkdir()
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (mount / guard.STORE_DIRNAME).symlink_to(outside, target_is_directory=True)

    with pytest.raises(guard.GuardError):
        guard.snapshot_path(mount, a_name())


# --- c. argv shapes --------------------------------------------------------


def test_create_argv_is_the_pinned_read_only_command(tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    (mount / guard.STORE_DIRNAME).mkdir()
    name = a_name()

    argv = guard.create_argv(mount, name)

    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert argv == [
        "btrfs",
        "subvolume",
        "snapshot",
        "-r",
        str(mount),
        str(mount / guard.STORE_DIRNAME / name),
    ]
    # ``-r`` is the read-only flag: a snapshot must never be a writable view of
    # the live subvolume.
    assert "-r" in argv


def test_delete_argv_is_the_pinned_delete_command(tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    (mount / guard.STORE_DIRNAME).mkdir()
    name = a_name()

    argv = guard.delete_argv(mount, name)

    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert argv == ["btrfs", "subvolume", "delete", str(mount / guard.STORE_DIRNAME / name)]
    for flag in ("-r", "-R", "--recursive", "-d"):
        assert flag not in argv


def test_run_btrfs_passes_a_list_and_never_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded["argv"] = argv
        recorded.update(kwargs)
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    server.run_btrfs(("btrfs", "subvolume", "list"))

    assert recorded["argv"] == ["btrfs", "subvolume", "list"]
    assert recorded["shell"] is False


# --- d. auth and boot ------------------------------------------------------


def test_authorised_accepts_only_the_exact_bearer_token() -> None:
    sidecar = server.Sidecar("/library", TOKEN, RecordingRunner())

    assert sidecar.authorised(f"Bearer {TOKEN}")
    assert sidecar.authorised(f"bearer {TOKEN}")


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer ", f"Bearer {TOKEN} extra", "Bearer wrong-token", f"Basic {TOKEN}", TOKEN],
)
def test_authorised_rejects_every_other_header(header: Optional[str]) -> None:
    sidecar = server.Sidecar("/library", TOKEN, RecordingRunner())

    assert not sidecar.authorised(header)


def test_an_empty_token_never_authorises_anything() -> None:
    sidecar = server.Sidecar("/library", "", RecordingRunner())

    assert not sidecar.authorised("")
    assert not sidecar.authorised("Bearer ")


@pytest.mark.parametrize("token", ["", "   "])
def test_boot_refuses_a_missing_token_before_any_command(token: str, tmp_path: Path) -> None:
    runner = RecordingRunner()

    with pytest.raises(server.BootError):
        server.boot(str(tmp_path), token, runner)

    assert runner.calls == []
    assert not (tmp_path / guard.STORE_DIRNAME).exists()


def test_boot_refuses_a_mount_that_is_not_a_subvolume(tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    runner = RecordingRunner(returncode=1, stderr="ERROR: not a subvolume\n")

    with pytest.raises(server.BootError, match="not a btrfs subvolume"):
        server.boot(str(mount), TOKEN, runner)

    assert runner.calls == [["btrfs", "subvolume", "show", str(mount)]]
    assert not (mount / guard.STORE_DIRNAME).exists()


def test_boot_proves_the_subvolume_and_creates_the_store(tmp_path: Path) -> None:
    mount = tmp_path.resolve()
    runner = RecordingRunner(stdout="Name: library\n")

    sidecar = server.boot(str(mount), TOKEN, runner)

    assert runner.calls == [["btrfs", "subvolume", "show", str(mount)]]
    assert (mount / guard.STORE_DIRNAME).is_dir()
    assert sidecar.mount == mount


def test_main_exits_non_zero_when_the_token_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(server.TOKEN_ENV, raising=False)
    monkeypatch.setenv(server.MOUNT_ENV, "/nonexistent-library")

    assert server.main() == server.EXIT_REFUSED


# --- e. create and its refusals -------------------------------------------


@pytest.mark.parametrize("extra_key", ["path", "source", "target", "mount", "args"])
def test_a_body_with_any_other_key_is_rejected_before_any_command(extra_key: str, tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)

    with pytest.raises(server.SidecarError) as refusal:
        sidecar.create({"name": a_name(), extra_key: "/etc/passwd"})

    assert refusal.value.status == 400
    assert runner.calls == []


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"name": 7}, {"Name": "x"}, ["name"], "name"])
def test_a_body_without_one_string_name_is_rejected(payload: object, tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)

    with pytest.raises(server.SidecarError) as refusal:
        sidecar.create(payload)

    assert refusal.value.status == 400
    assert runner.calls == []


def test_a_valid_create_runs_exactly_the_pinned_argv(tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)
    name = a_name()

    created = sidecar.create({"name": name})

    assert created == name
    assert runner.calls == [["btrfs", "subvolume", "snapshot", "-r", str(sidecar.mount), str(sidecar.mount / ".snap" / name)]]
    assert isinstance(runner.calls[0], list)
    assert all(isinstance(part, str) for part in runner.calls[0])


def test_create_of_an_existing_snapshot_is_a_409(tmp_path: Path) -> None:
    sidecar, _runner = booted(tmp_path, RecordingRunner(returncode=1, stderr="ERROR: target path already exists\n"))

    with pytest.raises(server.SidecarError) as refusal:
        sidecar.create({"name": a_name()})

    assert refusal.value.status == 409


def test_any_other_btrfs_failure_is_a_500_with_the_message_only(tmp_path: Path) -> None:
    sidecar, _runner = booted(tmp_path, RecordingRunner(returncode=1, stderr="ERROR: cannot access the subvolume\n"))

    with pytest.raises(server.SidecarError) as refusal:
        sidecar.create({"name": a_name()})

    assert refusal.value.status == 500
    assert "cannot access the subvolume" in str(refusal.value)


def test_delete_runs_exactly_the_pinned_argv(tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)
    name = a_name()
    (sidecar.store / name).mkdir()

    sidecar.delete(name)

    assert runner.calls == [["btrfs", "subvolume", "delete", str(sidecar.store / name)]]


def test_delete_of_a_missing_snapshot_is_a_404_without_a_command(tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)

    with pytest.raises(server.SidecarError) as refusal:
        sidecar.delete(a_name())

    assert refusal.value.status == 404
    assert runner.calls == []


# --- f. listing -----------------------------------------------------------


def test_list_snapshots_sees_only_guard_valid_directories(tmp_path: Path) -> None:
    sidecar, _runner = booted(tmp_path)
    wanted = sorted([a_name(suffix="abc123"), a_name(snapshots.SnapshotReason.PRE_PURGE, suffix="def456")])
    for name in wanted:
        (sidecar.store / name).mkdir()
    (sidecar.store / a_name(suffix="aaa111")).write_text("a stray file, not a snapshot", encoding="utf-8")
    (sidecar.store / "not-a-snapshot").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (sidecar.store / a_name(suffix="bbb222")).symlink_to(outside, target_is_directory=True)

    assert sidecar.list_snapshots() == wanted


def test_health_reports_ready_and_never_the_token(tmp_path: Path) -> None:
    sidecar, runner = booted(tmp_path)

    health = sidecar.health()

    assert health["state"] == "ready"
    assert health["mount"] == str(sidecar.mount)
    assert health["store_exists"] is True
    assert TOKEN not in json.dumps(health)
    assert runner.calls == []


# --- the operator docs ------------------------------------------------------


def configuration_doc() -> str:
    """The operator doc, or a skip when the host-only docs tree is absent."""
    if not CONFIGURATION_DOC.exists():
        pytest.skip("host-only: curiarium/docs/architecture/CONFIGURATION.md is outside the API image build context")
    return CONFIGURATION_DOC.read_text(encoding="utf-8")


def fenced_yaml_block(text: str) -> str:
    """The one fenced ``yaml`` block, so prose mentioning ``ports:`` cannot confuse a check."""
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "```yaml"]
    assert len(starts) == 1, f"expected exactly one ```yaml fence, found {len(starts)}"
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.strip() == "```":
            return "\n".join(body)
        body.append(line)
    raise AssertionError("the ```yaml fence is never closed")


def section_body(text: str, heading: str) -> str:
    """The text under ``heading``, up to the next heading of any level."""
    lines = text.splitlines()
    if heading not in lines:
        raise AssertionError(f"CONFIGURATION.md has no {heading!r} heading")
    body: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def test_the_btrfs_sidecar_section_follows_the_zfs_section() -> None:
    text = configuration_doc()

    assert "## Snapshots (BTRFS sidecar)" in text
    assert text.index("## Snapshots (ZFS)") < text.index("## Snapshots (BTRFS sidecar)")


def test_the_compose_example_keeps_the_privilege_envelope() -> None:
    block = fenced_yaml_block(configuration_doc())

    for token in (
        "SYS_ADMIN",
        "cap_drop",
        "ALL",
        "read_only: true",
        "SNAPSHOT_BTRFS_SIDECAR_URL",
        "SNAPSHOT_BTRFS_SIDECAR_TOKEN",
        "SNAPSHOT_BTRFS_SIDECAR_MOUNT",
        "build: ./snapshot-sidecar",
    ):
        assert token in block, f"the compose example lost {token!r}"

    assert not [line for line in block.splitlines() if line.strip().startswith("ports:")], (
        "the compose example must publish no ports; the sidecar is compose-network only"
    )


def test_the_compose_example_binds_one_host_directory_into_both_services() -> None:
    block = fenced_yaml_block(configuration_doc())
    lines = block.splitlines()

    volume_keys = [index for index, line in enumerate(lines) if line.strip() == "volumes:"]
    assert len(volume_keys) == 2, f"expected one volumes: key per service, found {len(volume_keys)}"

    binds = [line.strip()[2:] for line in lines if line.strip().startswith("- /srv/")]
    assert len(binds) == 2, f"expected one bind mount per service, found {binds}"
    host_paths = {bind.split(":")[0] for bind in binds}
    assert len(host_paths) == 1, f"the two services must bind the same host directory, got {host_paths}"
    targets = {bind.split(":")[1] for bind in binds}
    # The sidecar's mount and the API's FILE_STORAGE are one directory at two paths;
    # a bind on only one of them is the mismatch B1 found.
    assert targets == {"/library", "/app/storage"}, f"unexpected bind targets {targets}"
    assert "FILE_STORAGE: /app/storage" in [line.strip() for line in lines]


def test_the_security_note_names_the_capability() -> None:
    body = section_body(configuration_doc(), "### What the sidecar is allowed to do")

    assert "CAP_SYS_ADMIN" in body


def test_the_manual_verification_is_operator_evidence_not_ci() -> None:
    body = section_body(configuration_doc(), "### Real-btrfs verification (MANUAL)")
    words = " ".join(body.split())

    assert "operator evidence, not CI evidence" in words


def test_both_sidecar_keys_have_a_table_row() -> None:
    rows = [line for line in configuration_doc().splitlines() if line.startswith("| `")]

    for key in ("SNAPSHOT_BTRFS_SIDECAR_URL", "SNAPSHOT_BTRFS_SIDECAR_TOKEN"):
        assert any(row.startswith(f"| `{key}` |") for row in rows), f"CONFIGURATION.md has no table row for {key}"


def test_the_capabilities_row_points_at_the_btrfs_sidecar_section() -> None:
    text = configuration_doc()
    rows = [line for line in text.splitlines() if line.startswith("|") and "btrfs_subvol" in line]

    assert rows, "CONFIGURATION.md has no capabilities table row for btrfs_subvol"
    assert any("Snapshots (BTRFS sidecar)" in row for row in rows)
    assert "No snapshot is taken in this slice." in text
