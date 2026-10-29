"""The ZFS provider and its probe, with no real ``zfs`` and no real pool.

Every test here injects a fake runner and works under ``tmp_path``: nothing
invokes the ``zfs`` binary, reads a live dataset, or touches a mounted pool, so
this module runs in CI on a host with no ZFS at all. The fake answers the four
subcommands the provider uses (``list``, ``allow``, ``snapshot``, ``destroy``)
and records every argv, which is how the command *shape* is pinned: a list, a
``--`` before the first positional operand, and never ``-r``, ``-R`` or ``-d``.

Real-pool verification is a documented manual procedure (see
``makervault/docs/architecture/CONFIGURATION.md``, "Snapshots (ZFS)"), not CI
evidence: delegation, ``/dev/zfs`` inside a container and ``snapdir``
visibility cannot be proven without a pool, so they are checked by hand on a
real deployment.
"""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import pytest

import snapshot_zfs
import snapshots
import storage_capabilities

STORE = (snapshot_zfs.ZFS_DIRNAME, snapshot_zfs.SNAPSHOT_SUBDIR)
MANUAL_NAME = "20260101T000000Z-manual-abc123"
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
FORBIDDEN_FLAGS = {"-r", "-R", "-d"}

ALLOW_OUTPUTS = {
    "user": "---- Permissions on tank/library ----\nLocal permissions:\n\tuser alice snapshot,destroy,mount\n",
    "group": "Descendent permissions:\n\tgroup staff snapshot,mount,destroy\n",
    "everyone": "everyone snapshot,destroy,mount\n",
    "permission-set": "Sets of permissions:\n\t@vault snapshot,mount,destroy\n",
}


DENIED_ALLOW_OUTPUTS = {
    "permission-set": "sets of permissions:\n\t@perms snapshot,mount,!destroy\n",
    "user": "Local permissions:\n\tuser alice snapshot,mount,!destroy\n",
}


# --- helpers ----------------------------------------------------------------


def completed(argv: Sequence[str], stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)


class FakeZfs:
    """Scripted ``zfs``: answers by subcommand and records every argv it saw."""

    def __init__(
        self,
        *,
        dataset: str = "tank/library",
        allow_output: str = "",
        allow_error: Optional[BaseException] = None,
    ) -> None:
        self.dataset = dataset
        self.allow_output = allow_output
        self.allow_error = allow_error
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        subcommand = argv[1]
        if subcommand == "list":
            return completed(argv, stdout=f"{self.dataset}\n")
        if subcommand == "allow":
            if self.allow_error is not None:
                raise self.allow_error
            return completed(argv, stdout=self.allow_output)
        if subcommand in ("snapshot", "destroy"):
            return completed(argv)
        raise AssertionError(f"unexpected argv: {list(argv)}")


def forbidden(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"zfs must not run here, but ran with {list(argv)}")


def tree_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    return root


def mounted(monkeypatch: pytest.MonkeyPatch, mount_point: Path, fstype: str) -> None:
    """Answer S1's mount lookup with one fixed mount entry."""
    monkeypatch.setattr(storage_capabilities, "resolve_mount", lambda path, device: (Path(mount_point), fstype))


# --- probe_zfs --------------------------------------------------------------


def test_probe_on_a_non_zfs_volume_is_unavailable_and_runs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "ext4")
    runner = FakeZfs()

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.UNAVAILABLE
    assert "ext4" in probe.reason
    assert probe.dataset is None
    assert probe.remedy is None
    assert runner.calls == []


def test_probe_on_a_subdirectory_of_a_dataset_is_library_not_mountpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, tmp_path, "zfs")
    runner = FakeZfs()

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.LIBRARY_NOT_MOUNTPOINT
    assert probe.mountpoint == str(tmp_path)
    assert probe.remedy == snapshot_zfs.MOUNTPOINT_REMEDY
    assert "mountpoint" in probe.reason
    assert runner.calls == []


@pytest.mark.parametrize("allow_output", ALLOW_OUTPUTS.values(), ids=ALLOW_OUTPUTS.keys())
def test_probe_reports_delegated_for_each_allow_output_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow_output: str
) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_output=allow_output)
    library = root.resolve()

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.DELEGATED
    assert probe.dataset == "tank/library"
    assert probe.mountpoint == str(library)
    assert probe.remedy is None
    assert runner.calls == [
        [snapshot_zfs.ZFS_BIN, "list", "-H", "-o", "name", "--", str(library)],
        [snapshot_zfs.ZFS_BIN, "allow", "--", "tank/library"],
    ]


def test_probe_names_the_missing_permissions_and_the_allow_remedy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_output="Local permissions:\n\tuser alice snapshot\n")

    probe = snapshot_zfs.probe_zfs(root, runner=runner, user="alice")

    assert probe.state is snapshot_zfs.ZfsState.AVAILABLE_BUT_NOT_DELEGATED
    assert "destroy" in probe.reason
    assert "mount" in probe.reason
    assert probe.remedy == "zfs allow -u alice snapshot,destroy,mount tank/library"


def test_probe_parses_permission_tokens_rather_than_matching_a_substring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    # The dataset name and the principal both contain "snapshot"; no permission
    # field grants it, so a substring check would wrongly report delegated.
    allow_output = "---- Permissions on tank/snapshot ----\nLocal permissions:\n\tuser snapshot snapshot_hold\n"
    runner = FakeZfs(allow_output=allow_output)

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.AVAILABLE_BUT_NOT_DELEGATED
    assert "snapshot" in probe.reason
    assert snapshot_zfs.permission_tokens(allow_output) == frozenset()


def test_probe_reports_unavailable_when_the_zfs_binary_cannot_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_error=FileNotFoundError("zfs"))

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.UNAVAILABLE
    assert probe.dataset == "tank/library"
    assert "could not be run" in probe.reason


@pytest.mark.parametrize("allow_output", DENIED_ALLOW_OUTPUTS.values(), ids=DENIED_ALLOW_OUTPUTS.keys())
def test_an_explicitly_denied_permission_is_never_counted_as_a_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow_output: str
) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_output=allow_output)

    probe = snapshot_zfs.probe_zfs(root, runner=runner, user="alice")

    assert probe.state is snapshot_zfs.ZfsState.AVAILABLE_BUT_NOT_DELEGATED
    assert "destroy" in probe.reason
    assert "destroy" not in snapshot_zfs.permission_tokens(allow_output)
    assert probe.remedy == "zfs allow -u alice snapshot,destroy,mount tank/library"


def test_probe_falls_back_to_the_uid_when_the_user_lookup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_output="Local permissions:\n\tuser alice snapshot\n")

    def no_user() -> str:
        raise OSError("no passwd entry")

    monkeypatch.setattr(snapshot_zfs.getpass, "getuser", no_user)

    probe = snapshot_zfs.probe_zfs(root, runner=runner)

    assert probe.state is snapshot_zfs.ZfsState.AVAILABLE_BUT_NOT_DELEGATED
    assert probe.remedy is not None
    assert str(os.getuid()) in probe.remedy


# --- ZfsProvider ------------------------------------------------------------


def test_construction_is_probe_free_and_degrades_like_the_null_provider(tmp_path: Path) -> None:
    root = tree_root(tmp_path)

    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=forbidden)

    assert zfs_provider.snapshot_dir == (root / snapshot_zfs.ZFS_DIRNAME / snapshot_zfs.SNAPSHOT_SUBDIR).resolve()
    assert zfs_provider.method == storage_capabilities.ZFS_DATASET
    assert (zfs_provider.supports_browse, zfs_provider.supports_restore) == (True, True)
    assert zfs_provider.list() == []
    with pytest.raises(snapshots.SnapshotUnavailable):
        zfs_provider.create()


def test_create_snapshots_the_resolved_dataset(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root.joinpath(*STORE)).mkdir(parents=True)
    runner = FakeZfs()
    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=runner)

    created = zfs_provider.create()

    assert runner.calls == [
        [snapshot_zfs.ZFS_BIN, "list", "-H", "-o", "name", "--", str(root.resolve())],
        [snapshot_zfs.ZFS_BIN, "snapshot", "--", f"tank/library@{created.snapshot.name}"],
    ]
    for argv in runner.calls:
        assert "--" in argv
        assert not FORBIDDEN_FLAGS & set(argv)


def test_delete_destroys_exactly_the_named_snapshot(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root.joinpath(*STORE)).mkdir(parents=True)
    runner = FakeZfs()
    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=runner)

    zfs_provider.delete(MANUAL_NAME)

    assert runner.calls == [
        [snapshot_zfs.ZFS_BIN, "list", "-H", "-o", "name", "--", str(root.resolve())],
        [snapshot_zfs.ZFS_BIN, "destroy", "--", f"tank/library@{MANUAL_NAME}"],
    ]
    assert not FORBIDDEN_FLAGS & set(runner.calls[-1])


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_a_hostile_name_is_refused_before_any_cli_call(tmp_path: Path, name: str) -> None:
    root = tree_root(tmp_path)
    (root.joinpath(*STORE)).mkdir(parents=True)
    runner = FakeZfs()
    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=runner)

    with pytest.raises(snapshots.SnapshotPathError):
        zfs_provider.delete(name)

    assert runner.calls == []


def test_a_foreign_snapshot_directory_is_invisible_and_survives_create_and_prune(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    store = root.joinpath(*STORE)
    store.mkdir(parents=True)
    foreign = store / "zfs-auto-snap_hourly-2026-01-01-0000"
    foreign.mkdir()
    assert snapshots.parse_name(foreign.name) is None
    runner = FakeZfs()
    policy = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=1, hard_cap=1)
    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=policy, runner=runner)

    assert zfs_provider.list() == []
    created = zfs_provider.create()

    assert created.prune.pruned == 0
    assert zfs_provider.list() == []
    assert foreign.is_dir()
    assert [argv[1] for argv in runner.calls] == ["list", "snapshot"]


# --- run_zfs ----------------------------------------------------------------


def test_run_zfs_is_a_list_no_shell_with_a_timeout_and_a_c_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def spy(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return completed(argv)

    monkeypatch.setattr(snapshot_zfs.subprocess, "run", spy)
    argv = [snapshot_zfs.ZFS_BIN, "list", "--", "/library"]

    result = snapshot_zfs.run_zfs(argv)

    assert result.returncode == 0
    assert captured["argv"] == argv
    assert isinstance(captured["argv"], list)
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == snapshot_zfs.ZFS_TIMEOUT_SECONDS
    assert captured["kwargs"]["env"]["LC_ALL"] == "C"
    assert captured["kwargs"]["check"] is False
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


def test_a_failing_snapshot_reports_the_zfs_stderr(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root.joinpath(*STORE)).mkdir(parents=True)

    def failing(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "list":
            return completed(argv, stdout="tank/library\n")
        return completed(argv, stderr="cannot create snapshot 'tank/library@x': dataset is busy\n", returncode=1)

    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=failing)

    with pytest.raises(snapshots.SnapshotError) as caught:
        zfs_provider.create()

    assert not isinstance(caught.value, snapshots.SnapshotUnavailable)
    assert "dataset is busy" in str(caught.value)


def test_the_probe_never_takes_a_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree_root(tmp_path)
    mounted(monkeypatch, root, "zfs")
    runner = FakeZfs(allow_output=ALLOW_OUTPUTS["user"])

    snapshot_zfs.probe_zfs(root, runner=runner)

    assert [argv[1] for argv in runner.calls] == ["list", "allow"]


def test_a_snapshot_time_is_still_the_templates_name(tmp_path: Path) -> None:
    root = tree_root(tmp_path)
    (root.joinpath(*STORE)).mkdir(parents=True)
    runner = FakeZfs()
    zfs_provider = snapshot_zfs.ZfsProvider(root, policy=snapshots.RetentionPolicy(), runner=runner)

    created = zfs_provider.create(snapshots.SnapshotReason.PRE_DELETE)

    assert created.snapshot.reason is snapshots.SnapshotReason.PRE_DELETE
    assert snapshots.parse_name(created.snapshot.name) is not None
    assert created.snapshot.created_at <= datetime.now(timezone.utc)
