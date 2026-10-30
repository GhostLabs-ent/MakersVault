"""Containment for the privileged BTRFS snapshot sidecar (Mf-o6si).

This module is the whole containment argument for the sidecar. The helper runs
as root with ``CAP_SYS_ADMIN`` -- btrfs cannot snapshot without it -- so the only
thing between an HTTP request and ``btrfs subvolume delete`` on an arbitrary
path is this file. Nothing here touches the filesystem, spawns a process or
opens a socket: it validates a name, resolves a destination and builds an argv
list, and every filesystem action the server takes goes through one of them.

The API is *not* trusted to have validated the name. It applies the same rules in
``snapshots.assert_library_path``, but the sidecar is a separate process
reachable by anything on the compose network, so it re-validates and
re-contains every name it is given rather than trusting its caller.

``NAME_RE`` mirrors ``snapshots.NAME_RE`` on purpose and is deliberately NOT
imported: this container is built from ``curiarium/snapshot-sidecar`` and must
never depend on the API's package layout or its dependencies. Drift between the
two patterns is caught by the host-only test
``curiarium/api/tests/test_snapshot_sidecar_guard.py``, which compares the two
compiled patterns.

Deliberate anti-patterns, all refused before a name reaches a command:

* ``/`` and ``\\`` -- path separators, so no name can address another path.
* a NUL byte -- a truncated string in any C consumer below us.
* ``..`` -- traversal, refused even though the separators already stop it.
* a leading ``-`` -- ``btrfs`` would parse the name as a flag, not an operand.
* an absolute path -- the store is always relative to the mount.
* anything the pattern below does not match, so the shape of a name is fixed
  by the snapshot scheme rather than by whoever called the helper.
"""

from __future__ import annotations

import re
from pathlib import Path

STORE_DIRNAME = ".snap"
BTRFS_BIN = "btrfs"

# Mirrors ``snapshots.NAME_RE``: ``<UTC stamp>-<reason>-<random suffix>``. The
# reason alternation is spelled out instead of built from an enum, because the
# sidecar must not import anything from the API.
NAME_PATTERN = r"^(?P<stamp>\d{8}T\d{6}Z)-(?P<reason>manual|scheduled|predelete|prepurge|prebulk)-(?P<suffix>[0-9a-f]{6})$"
NAME_RE = re.compile(NAME_PATTERN)

FORBIDDEN_TOKENS = ("/", "\\", "\0", "..")


class GuardError(ValueError):
    """A name or destination the sidecar refuses; the server answers 400."""


def valid_name(name: object) -> bool:
    """True only for a name in the snapshot scheme that carries no path syntax."""
    if not isinstance(name, str) or not name:
        return False

    # A leading "-" is an operand that btrfs would read as a flag.
    if name.startswith("-"):
        return False

    for token in FORBIDDEN_TOKENS:
        if token in name:
            return False

    return NAME_RE.fullmatch(name) is not None


def mount_root(mount: str | Path) -> Path:
    """The mount's resolved root: the only base any path here may climb to."""
    return Path(mount).resolve()


def snapshot_path(mount: str | Path, name: object) -> Path:
    """The resolved ``<mount>/.snap/<name>``, proven to be inside ``<mount>``.

    Resolution happens before the containment check, so a ``..`` sequence or a
    symlink planted in the store has nothing left to slip through: the resolved
    path must still have the resolved mount among its parents.
    """
    if not valid_name(name):
        raise GuardError(f"{name!r} is not a valid snapshot name")

    root = mount_root(mount)
    resolved = (root / STORE_DIRNAME / str(name)).resolve()
    if root not in resolved.parents:
        raise GuardError(f"the snapshot path {resolved} is not inside the mount {root}")
    return resolved


def show_argv(mount: str | Path) -> list[str]:
    """The boot check: prove the mount really is a btrfs subvolume."""
    return [BTRFS_BIN, "subvolume", "show", str(mount_root(mount))]


def create_argv(mount: str | Path, name: object) -> list[str]:
    """A read-only (``-r``) snapshot of the whole mount into the store.

    ``-r`` is not optional: the snapshot must be a frozen view, because a
    writable snapshot of the live subvolume could be modified through the store.
    """
    root = mount_root(mount)
    return [BTRFS_BIN, "subvolume", "snapshot", "-r", str(root), str(snapshot_path(root, name))]


def delete_argv(mount: str | Path, name: object) -> list[str]:
    """Remove exactly one snapshot directory inside the store.

    No ``-r``, ``-R``, ``--recursive`` or ``-d``: a snapshot is one subvolume, so
    a delete that needs a recursive flag is a delete of something else, and the
    command must fail rather than remove a tree.
    """
    return [BTRFS_BIN, "subvolume", "delete", str(snapshot_path(mount, name))]
