"""Snapshot capability detection per storage volume (Mf-ib5s).

Reads the filesystem magic with ``statfs(2)`` through ctypes (``os.statvfs`` has
no ``f_type``) and resolves the mount point from ``/proc/self/mounts`` by
longest prefix, cross-checked on ``st_dev``. Detection is read-only: it creates
nothing on disk, takes no snapshot, and never raises.

The canonical deployment pairs a CephFS library root with an ext4 database
directory. That pair reports two answers in one report: ``cephfs_snapdir``
usable (because ``<root>/.snap`` exists and is writable) and ``none`` for the
ext4 volume, which has no snapshot method. Nothing here takes a snapshot; this
slice only says whether one *could* be taken.

Every method is checked as the running process, which is a caveat for the
CephFS answer: ``os.access`` is always true for root, so a root container sees
a ``.snap`` directory as writable whether or not the deployment actually grants
that to the service principal.
"""

import ctypes
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

CEPHFS_MAGIC = 0x00C36400
BTRFS_MAGIC = 0x9123683E
ZFS_MAGIC = 0x2FC12FC1

CEPHFS_SNAPDIR = "cephfs_snapdir"
ZFS_DATASET = "zfs_dataset"
BTRFS_SUBVOL = "btrfs_subvol"
NO_METHOD = "none"

LIBRARY_ROLE = "library"
DATABASE_ROLE = "database"

UNKNOWN_FSTYPE = "unknown"

# The magics we name. Everything else reports "unknown" and claims no method.
FSTYPE_BY_MAGIC = {
    CEPHFS_MAGIC: "ceph",
    BTRFS_MAGIC: "btrfs",
    ZFS_MAGIC: "zfs",
    0xEF53: "ext",  # ext2/ext3/ext4 share this magic
    0x01021994: "tmpfs",
    0x794C7630: "overlay",
    0x6969: "nfs",
    0xFF534D42: "cifs",
    0x58465342: "xfs",
    0x65735546: "fuse",
}

MOUNTS_PATH = Path("/proc/self/mounts")
_STATFS_BUFFER_BYTES = 4096  # struct statfs is ~120 bytes; only f_type is read
_ZFS_PROBE_TIMEOUT_SECONDS = 2
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
_OCTAL_REPLACEMENTS = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
_SQLITE_PREFIXES = ("sqlite:///", "sqlite+pysqlite:///")

_libc: Optional[ctypes.CDLL] = None
if sys.platform.startswith("linux"):
    try:
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.statfs.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        _libc.statfs.restype = ctypes.c_int
    except (OSError, AttributeError):  # pragma: no cover - non-glibc platforms
        _libc = None


@dataclass(frozen=True)
class VolumeCapability:
    """One storage volume and what snapshotting can actually do there."""

    roles: tuple[str, ...]
    path: str
    fstype: str
    mount_point: str
    snapshot_method: str
    usable: bool
    reason: str


def statfs_magic(path: Path) -> Optional[int]:
    """The filesystem magic for ``path``, or None when it cannot be read.

    ``struct statfs`` is ABI-sensitive, so only the first C ``long`` (``f_type``)
    is read out of an oversized buffer instead of hand-rolling the whole layout.
    """
    if _libc is None:
        return None
    # A generous buffer means a larger struct in the future is still safe: the
    # trailing bytes are never inspected.
    buffer = ctypes.create_string_buffer(_STATFS_BUFFER_BYTES)
    try:
        result = _libc.statfs(os.fsencode(str(path)), ctypes.byref(buffer))
    except OSError:
        return None
    if result != 0:
        return None
    first_long = buffer.raw[: ctypes.sizeof(ctypes.c_long)]
    return int.from_bytes(first_long, sys.byteorder, signed=True) & 0xFFFFFFFF


def fstype_name(magic: Optional[int]) -> str:
    """Name the filesystem from its magic; anything unnamed is ``unknown``."""
    return FSTYPE_BY_MAGIC.get(magic, UNKNOWN_FSTYPE)


def normalised_fstype(name: str) -> str:
    """Fold the mount-table spellings onto the names the magic table uses."""
    if name.startswith(("ext2", "ext3", "ext4")):
        return "ext"
    if name.startswith("fuse"):
        return "fuse"
    return name


def device_id(path: Path) -> Optional[int]:
    """The ``st_dev`` of ``path``, or None when it cannot be stat-ed."""
    try:
        return path.stat().st_dev
    except OSError:
        return None


def _decode_octal(text: str) -> str:
    """Decode the octal escapes the kernel writes into ``/proc/self/mounts``."""

    def replacement(match: re.Match[str]) -> str:
        code = match.group(1)
        return _OCTAL_REPLACEMENTS.get(code, chr(int(code, 8)))

    return _OCTAL_ESCAPE.sub(replacement, text)


def mount_table() -> list[tuple[Path, str]]:
    """The (mount point, fstype) pairs from ``MOUNTS_PATH``; empty if unreadable."""
    try:
        lines = MOUNTS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[tuple[Path, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        entries.append((Path(_decode_octal(fields[1])), fields[2]))
    return entries


def resolve_mount(path: Path, device: Optional[int]) -> Optional[tuple[Path, str]]:
    """The mount entry that contains ``path``, preferring one on the same device.

    Longest prefix wins; ``st_dev`` breaks the tie between nested mounts (a
    bind mount of the same device would otherwise shadow the real one). When no
    candidate agrees on the device the deepest one is still the best answer.
    """
    entries = mount_table()
    if not entries:
        return None
    candidates = [
        (mount_point, fstype)
        for mount_point, fstype in entries
        if mount_point == path or mount_point in path.parents
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda entry: len(entry[0].parts), reverse=True)
    for mount_point, fstype in candidates:
        if device_id(mount_point) == device:
            return mount_point, fstype
    return candidates[0]


def binary(name: str) -> Optional[str]:
    """The executable path for ``name``, or None when it is not installed."""
    return shutil.which(name)


def run_bounded(argv: list[str]) -> Optional[str]:
    """Run a read-only probe with a timeout; stdout on success, else None."""
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_ZFS_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def assess_snapshot(fstype: str, path: Path) -> tuple[str, bool, str]:
    """Return (method, usable, reason) for the volume mounted at ``path``."""
    if fstype == "ceph":
        snap = path / ".snap"
        if not snap.is_dir():
            return CEPHFS_SNAPDIR, False, "cephfs root has no .snap directory"
        if not os.access(snap, os.W_OK):
            return CEPHFS_SNAPDIR, False, "the .snap directory is not writable by this process"
        return CEPHFS_SNAPDIR, True, "the .snap directory exists and is writable"

    if fstype == "zfs":
        zfs = binary("zfs")
        if zfs is None:
            return ZFS_DATASET, False, "the zfs binary is not installed"
        listing = run_bounded([zfs, "list", "-H", "-o", "name", str(path)])
        dataset = next((line.strip() for line in (listing or "").splitlines() if line.strip()), None)
        if dataset is None:
            return ZFS_DATASET, False, "the zfs dataset behind this path could not be resolved"
        allowed = run_bounded([zfs, "allow", dataset])
        # `zfs allow` prints the permission set comma-separated ("alice
        # snapshot,destroy"), so a token split would miss it.
        if allowed is not None and "snapshot" in allowed:
            return ZFS_DATASET, True, f"the zfs dataset {dataset} grants snapshot"
        return ZFS_DATASET, False, "the zfs dataset does not grant snapshot to this principal"

    if fstype == "btrfs":
        return _btrfs_verdict(path)

    return NO_METHOD, False, f"no snapshot method for {fstype}"


def _btrfs_verdict(path: Path) -> tuple[str, bool, str]:
    """The btrfs arm of ``assess_snapshot``: ask the sidecar, never the local binary.

    BTRFS needs ``CAP_SYS_ADMIN``, so the API container carries no btrfs binary
    and cannot snapshot anything itself; the answer comes from the opt-in
    sidecar the operator configured (``snapshot_btrfs.probe_sidecar``). This is
    its own seam so a test can drive the probe without a real sidecar, and so a
    probe that raises is still a btrfs answer rather than the blanket
    ``no_method`` report ``capability()`` writes for an unexpected failure.
    """
    try:
        import snapshot_btrfs

        probe = snapshot_btrfs.probe_sidecar(path)
    except Exception:
        return (
            BTRFS_SUBVOL,
            False,
            "btrfs snapshot capability could not be detected; "
            "see CONFIGURATION.md (Snapshots (BTRFS sidecar))",
        )
    return BTRFS_SUBVOL, probe.state is snapshot_btrfs.BtrfsState.READY, probe.reason


def database_directory(database_url: Optional[str]) -> Optional[Path]:
    """The directory that holds a sqlite database, or None for anything else.

    The database's own directory is the volume, so a URL pointing at
    ``/data/app.db`` reports ``/data``. A non-sqlite URL has no local volume.
    """
    if not database_url:
        return None
    remainder = None
    for prefix in _SQLITE_PREFIXES:
        if database_url.startswith(prefix):
            remainder = database_url[len(prefix) :]
            break
    if remainder is None:
        return None
    remainder = remainder.split("?", 1)[0]
    if not remainder or remainder == ":memory:":
        return None
    database_path = Path(remainder)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    return database_path.resolve().parent


def capability(roles: tuple[str, ...], path: Path) -> VolumeCapability:
    """Everything known about one volume; an unexpected failure is a safe answer."""
    resolved = path.resolve()
    try:
        magic = statfs_magic(resolved)
        fstype = fstype_name(magic)
        mount = resolve_mount(resolved, device_id(resolved))
        mount_point = str(mount[0]) if mount is not None else ""
        method, usable, reason = assess_snapshot(fstype, resolved)
    except Exception:
        # Detection must never propagate: an unexpected probe failure is a
        # report, not a crash.
        return VolumeCapability(
            roles=roles,
            path=str(resolved),
            fstype=UNKNOWN_FSTYPE,
            mount_point="",
            snapshot_method=NO_METHOD,
            usable=False,
            reason="capability detection failed",
        )
    return VolumeCapability(
        roles=roles,
        path=str(resolved),
        fstype=fstype,
        mount_point=mount_point,
        snapshot_method=method,
        usable=usable,
        reason=reason,
    )


def _storage_root() -> Path:
    """Resolve the storage root at call time so tests can monkeypatch it."""
    import db

    return Path(db.STORAGE)


def _database_url() -> Optional[str]:
    """The configured database URL at call time; patched by the same idiom."""
    import db

    return db.DB_URL


def detect(library_root: Optional[Path] = None, database_url: Optional[str] = None) -> list[VolumeCapability]:
    """Report the library volume and, when it is a separate volume, the database.

    A sqlite database that lives on the same device as the library is folded into
    one entry with both roles: it is one filesystem. Subtree-scoped methods
    (cephfs, btrfs) still snapshot per path, so the snapshot slice re-derives the
    per-role paths from ``database_directory(db.DB_URL)`` rather than trusting the
    merged entry's ``path``.
    """
    if library_root is None:
        library_root = _storage_root()
    if database_url is None:
        database_url = _database_url()

    library = capability((LIBRARY_ROLE,), library_root)
    database_dir = database_directory(database_url)
    if database_dir is None:
        return [library]

    database = capability((DATABASE_ROLE,), database_dir)
    library_device = device_id(library_root.resolve())
    database_device = device_id(database_dir)
    if library_device is not None and database_device is not None and library_device == database_device:
        return [replace(library, roles=(LIBRARY_ROLE, DATABASE_ROLE))]
    return [library, database]
