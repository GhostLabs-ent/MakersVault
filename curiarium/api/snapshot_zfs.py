"""ZFS snapshots, driven through the ``zfs`` CLI with delegated, unprivileged rights.

This module supplies only the two mechanics ``snapshots.SnapshotProvider`` asks
for -- materialise one snapshot, destroy one snapshot -- plus a read-only probe
that says whether this process may do either. Naming, retention, containment
and listing are *not* overridden here: they come from S2's template provider, so
a ZFS deployment behaves exactly like the CephFS one, and a snapshot name is
always the template's ``<UTC stamp>-<reason>-<random suffix>``, used verbatim
as the ZFS snapshot name (never prefixed, never normalised). Because ``.zfs`` is
not one of ``snapshots.RESERVED_COMPONENTS``, the template's containment check
accepts ``<root>/.zfs/snapshot`` as the store.

Only this application's snapshots are visible and prunable: the template lists
``<root>/.zfs/snapshot`` and keeps only the directories whose names its own
parser wrote, so ``zfs-auto-snapshot``, ``sanoid`` or a cron job's snapshots are
invisible to ``list()`` and immune to retention. They are real ZFS snapshots on
the same dataset, and this module never enumerates the dataset, so it cannot
prune them by accident.

The rights are delegated rather than root: ``zfs allow -u <user>
snapshot,destroy,mount <dataset>`` grants exactly the three subcommands used
here. ``mount`` is required even though nothing is mounted, because ``zfs
destroy`` checks the dataset's descendents before it removes a snapshot and that
check fails without it. ``probe_zfs`` reads ``zfs allow`` to report what the
deployment actually granted; detection is read-only and takes no snapshot.

``<root>/.zfs/snapshot/<name>`` is the read-only view of a snapshot: the kernel
materialises it on access, so browsing reads files from it directly and a
restore *copies out* of it. Nothing here ever runs ``zfs rollback``: a rollback
would discard every change since the snapshot for the whole dataset, including
everything this app did not write, so restore is a copy of the wanted files and
never a rewind of the dataset.

The library root must BE the dataset mountpoint (``zfs create -o
mountpoint=<library> <pool>/<name>``). A subdirectory of a dataset has no
``.zfs`` directory of its own, and the template refuses a snapshot store outside
the root, so a ``/dataset/subdir`` deployment has no usable provider at all;
``probe_zfs`` reports that as its own state rather than as a generic failure.
"""

from __future__ import annotations

import getpass
import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Sequence

import snapshots
import storage_capabilities

ZFS_BIN = "zfs"

# The kernel's snapshot view of one dataset: ``<root>/.zfs/snapshot/<name>``.
# ``.zfs`` is not in ``snapshots.RESERVED_COMPONENTS``, so the template's
# containment check accepts it as the store.
ZFS_DIRNAME = ".zfs"
SNAPSHOT_SUBDIR = "snapshot"

ZFS_TIMEOUT_SECONDS = 10

# ``mount`` is not used to mount anything: ``zfs destroy`` checks the dataset's
# descendents first, and that check needs it.
REQUIRED_PERMISSIONS = frozenset({"snapshot", "destroy", "mount"})

# Pinned literals: the docs quote them verbatim and the docs test fails if
# either drifts, so an operator pastes the same command the code would recommend.
ALLOW_REMEDY = "zfs allow -u <user> snapshot,destroy,mount <dataset>"
MOUNTPOINT_REMEDY = "zfs create -o mountpoint=<library> <pool>/<name>"

_PERMISSION_TOKEN = re.compile(r"[a-z]+")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class ZfsState(str, Enum):
    """What ``probe_zfs`` found, in the vocabulary the docs and UI use."""

    DELEGATED = "delegated"
    AVAILABLE_BUT_NOT_DELEGATED = "available_but_not_delegated"
    UNAVAILABLE = "unavailable"
    LIBRARY_NOT_MOUNTPOINT = "library_not_mountpoint"


@dataclass(frozen=True)
class ZfsProbe:
    """One read-only answer about one library root."""

    state: ZfsState
    dataset: Optional[str]
    mountpoint: Optional[str]
    reason: str
    remedy: Optional[str]


def run_zfs(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one ``zfs`` command: an argv list, no shell, a timeout, and an ASCII locale.

    ``LC_ALL=C`` is not cosmetic: the permission parser reads ``zfs allow``
    output, and a translated locale would change the words it matches.
    """
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=ZFS_TIMEOUT_SECONDS,
        env={**os.environ, "LC_ALL": "C"},
    )


def permission_tokens(allow_output: str) -> frozenset[str]:
    """The permission tokens a ``zfs allow`` listing grants, by permission field.

    Parsed by token, never by substring: a dataset or permission-set whose name
    contains "snapshot" grants nothing and must not be mistaken for a grant.
    Section headers (``Local permissions:``, or a ``---- Permissions on ... ----``
    banner) are skipped; for an entry line the permission field follows the
    principal, so ``user <name> perms`` and ``group <name> perms`` start at field
    two while ``everyone perms`` and ``@setname perms`` start at field one.
    A leading ``!`` marks an explicitly denied permission and is skipped rather
    than counted, so a dataset that grants ``snapshot,mount`` but denies
    ``destroy`` is never mistaken for one that grants all three. Every remaining
    token must be a bare lowercase word; anything else is ignored.
    """
    tokens: set[str] = set()
    for raw in allow_output.splitlines():
        line = raw.strip()
        if not line or line.endswith(":") or line.startswith("----"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        if fields[0] in ("user", "group"):
            permission_fields = fields[2:]
        elif fields[0] == "everyone" or fields[0].startswith("@"):
            permission_fields = fields[1:]
        else:
            continue
        for field in permission_fields:
            for token in field.split(","):
                candidate = token.strip()
                if candidate.startswith("!"):
                    continue
                if _PERMISSION_TOKEN.fullmatch(candidate):
                    tokens.add(candidate)
    return frozenset(tokens)


def current_user() -> str:
    """The running user's name, or its uid when the passwd lookup is unavailable.

    ``getpass.getuser()`` reads the environment and the passwd database, so it
    raises ``KeyError`` or ``OSError`` in a minimal container -- exactly the
    deployment where the ``/dev/zfs`` caveat matters. ``probe_zfs`` promises
    never to raise, so the remedy falls back to the numeric uid.
    """
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return str(os.getuid()) if hasattr(os, "getuid") else "unknown"


def resolve_dataset(root: Path, runner: Runner = run_zfs) -> Optional[str]:
    """The dataset that holds ``root``, or None when ``zfs list`` cannot say."""
    try:
        completed = runner([ZFS_BIN, "list", "-H", "-o", "name", "--", str(Path(root))])
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        dataset = line.strip()
        if dataset:
            return dataset
    return None


def _unavailable(reason: str, *, dataset: Optional[str] = None, mountpoint: Optional[str] = None) -> ZfsProbe:
    """One UNAVAILABLE answer: always remediless, so the shape cannot drift."""
    return ZfsProbe(state=ZfsState.UNAVAILABLE, dataset=dataset, mountpoint=mountpoint, reason=reason, remedy=None)


def probe_zfs(root: Optional[Path] = None, *, runner: Runner = run_zfs, user: Optional[str] = None) -> ZfsProbe:
    """Report whether this process may snapshot ``root``; read-only and never raises.

    The mount point comes from S1's mount table rather than from ``zfs get
    mountpoint``, so the answer agrees with the capability report the UI already
    shows. Nothing is created, no snapshot is taken, and every failure is a
    state with a reason.
    """
    library = Path(root if root is not None else snapshots.library_root()).resolve()

    mount = storage_capabilities.resolve_mount(library, storage_capabilities.device_id(library))
    if mount is None:
        return _unavailable(f"the library root {library} is not on a mounted volume, so no zfs dataset can back it")

    mount_point, fstype = mount
    if storage_capabilities.normalised_fstype(fstype) != "zfs":
        return _unavailable(
            f"the library root {library} is on {fstype}, not zfs, so there is no dataset to snapshot",
            mountpoint=str(mount_point),
        )

    if Path(mount_point).resolve() != library:
        return ZfsProbe(
            state=ZfsState.LIBRARY_NOT_MOUNTPOINT,
            dataset=None,
            mountpoint=str(mount_point),
            reason=(
                f"the library root {library} is a subdirectory of the dataset mounted at {mount_point}; "
                "the library root must be the dataset mountpoint, because a subdirectory has no .zfs snapshot view"
            ),
            remedy=MOUNTPOINT_REMEDY,
        )

    dataset = resolve_dataset(library, runner)
    if dataset is None:
        return _unavailable(
            f"could not resolve the zfs dataset behind the library root {library}", mountpoint=str(mount_point)
        )

    try:
        completed = runner([ZFS_BIN, "allow", "--", dataset])
    except (OSError, subprocess.SubprocessError) as error:
        return _unavailable(
            f"the zfs binary could not be run to read the delegated permissions on {dataset}: {error}",
            dataset=dataset,
            mountpoint=str(mount_point),
        )
    if completed.returncode != 0:
        return _unavailable(
            f"could not read the delegated permissions on the zfs dataset {dataset}",
            dataset=dataset,
            mountpoint=str(mount_point),
        )

    granted = permission_tokens(completed.stdout)
    missing = REQUIRED_PERMISSIONS - granted
    if not missing:
        return ZfsProbe(
            state=ZfsState.DELEGATED,
            dataset=dataset,
            mountpoint=str(mount_point),
            reason=f"the zfs dataset {dataset} delegates the required snapshot permissions to this principal",
            remedy=None,
        )
    return ZfsProbe(
        state=ZfsState.AVAILABLE_BUT_NOT_DELEGATED,
        dataset=dataset,
        mountpoint=str(mount_point),
        reason=f"the zfs dataset {dataset} does not delegate {', '.join(sorted(missing))} to this principal",
        remedy=ALLOW_REMEDY.replace("<user>", user or current_user()).replace("<dataset>", dataset),
    )


class ZfsProvider(snapshots.SnapshotProvider):
    """The ZFS provider: two ``zfs`` calls, and the template does the rest.

    Construction is probe-free -- no subprocess, no ``zfs`` call, no mount table
    read -- because ``snapshots.provider_for`` builds a provider on every volume
    it is asked about, including ones that are not ZFS at all. The dataset is
    resolved lazily, on the first create or delete.

    Only ``_materialise`` and ``_delete`` are overridden: ``list``,
    ``create``, ``delete``, ``path_for``, naming and retention all come from
    ``snapshots.SnapshotProvider``. A root with no ``<root>/.zfs/snapshot`` is
    therefore a create-time ``SnapshotUnavailable`` and an empty ``list()``,
    which is exactly how the null provider degrades.
    """

    method = storage_capabilities.ZFS_DATASET
    supports_browse = True
    supports_restore = True

    def __init__(
        self,
        root: Path,
        *,
        policy: Optional[snapshots.RetentionPolicy] = None,
        snapshot_root: Optional[Path] = None,
        runner: Runner = run_zfs,
    ) -> None:
        self.runner: Runner = runner
        self._dataset_cache: Optional[str] = None
        super().__init__(
            root,
            policy=policy,
            snapshot_root=snapshot_root if snapshot_root is not None else Path(root) / ZFS_DIRNAME / SNAPSHOT_SUBDIR,
        )

    def dataset(self) -> str:
        """The dataset behind the library root, resolved once and then cached."""
        if self._dataset_cache is None:
            listing = self._zfs([ZFS_BIN, "list", "-H", "-o", "name", "--", str(self.root)])
            dataset = next((line.strip() for line in listing.splitlines() if line.strip()), None)
            if dataset is None:
                raise snapshots.SnapshotUnavailable(f"the zfs dataset behind {self.root} could not be resolved")
            self._dataset_cache = dataset
        return self._dataset_cache

    def _zfs(self, argv: list[str]) -> str:
        """Run one argv and return stdout; a failure is a snapshot error, not a crash."""
        try:
            completed = self.runner(list(argv))
        except (OSError, subprocess.SubprocessError) as error:
            raise snapshots.SnapshotUnavailable(f"the zfs binary could not be run: {error}") from error
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            if "already exists" in stderr.casefold():
                raise snapshots.SnapshotExists(f"zfs {argv[1]} failed: {stderr}")
            raise snapshots.SnapshotError(f"zfs {argv[1]} failed: {stderr}")
        return completed.stdout

    def _materialise(self, target: Path) -> None:
        """Take the snapshot the template named, using that name verbatim."""
        if snapshots.parse_name(target.name) is None:
            raise snapshots.SnapshotPathError(f"{target.name!r} is not a snapshot name")
        self._zfs([ZFS_BIN, "snapshot", "--", f"{self.dataset()}@{target.name}"])

    def _delete(self, target: Path) -> None:
        """Destroy one snapshot of this dataset; never ``-r``, ``-R`` or ``-d``."""
        if snapshots.parse_name(target.name) is None:
            raise snapshots.SnapshotPathError(f"{target.name!r} is not a snapshot name")
        self._zfs([ZFS_BIN, "destroy", "--", f"{self.dataset()}@{target.name}"])
