"""Pure path-derivation rules for folders: no filesystem, no HTTP.

Migrations 1-4 are immutable, so `migrations._folder_path_segment` and
`migrations._effective_folder_parent` are a frozen API: they can never change to
match new runtime behaviour. The runtime therefore imports them instead of
keeping a second copy that could silently drift away from what migration 004
wrote into the database. `tests/test_folder_crud_filesystem.py` pins the parity
between these helpers and migration 004's backfill.

Everything here only reads and mutates ORM state; creating, renaming and pruning
directories is `folder_service`'s job.
"""

from typing import Optional

from sqlmodel import Session, select

from migrations import _effective_folder_parent as effective_folder_parent
from migrations import _folder_path_segment as folder_path_segment
from models import Folder

__all__ = [
    "allocate_segment",
    "converge_ancestor_paths",
    "derive_subtree_paths",
    "effective_folder_parent",
    "folder_path_segment",
    "folder_subtree",
    "join_relative",
    "sibling_scope",
]


def sibling_scope(session: Session, parent_id: Optional[str], exclude_ids: set[str]) -> tuple[set[str], set[str]]:
    """Return the (used, reserved) directory-name scopes of a parent folder.

    `used` holds the directory names already taken in that scope and `reserved`
    holds every non-excluded child's derived name, so a newcomer never takes the
    literal name of a sibling. Both sets are casefolded.

    `used` deliberately diverges from migration 004 for children whose
    `storage_path` is NULL: those contribute their *derived* name instead of
    nothing. Every folder created through the API has a NULL path until it is
    converged, so without the divergence two same-named siblings would both want
    the same directory name and the second one would die on the unique index.
    """
    children = session.exec(select(Folder).where(Folder.parent_id == parent_id))
    used: set[str] = set()
    reserved: set[str] = set()
    for child in children:
        if child.id in exclude_ids:
            continue
        derived = folder_path_segment(child.name).casefold()
        reserved.add(derived)
        if child.storage_path:
            used.add(child.storage_path.rsplit("/", 1)[-1].casefold())
        else:
            used.add(derived)
    return used, reserved


def allocate_segment(name: str, used: set[str], reserved: set[str], sanitized: bool = False) -> str:
    """Pick a directory segment that is unique inside its parent scope.

    This is migration 004's allocation loop verbatim, so a runtime rename lands
    on exactly the name the backfill would have chosen. The suffix is appended
    *after* the 120-character truncation, so a segment may reach 124 characters;
    that is also what makes `Foo` plus a literal `Foo (2)` push a newcomer to
    `Foo (3)`.
    """
    segment = name if sanitized else folder_path_segment(name)
    candidate = segment
    suffix = 2
    while candidate.casefold() in used or (
        candidate.casefold() != segment.casefold() and candidate.casefold() in reserved
    ):
        candidate = f"{segment} ({suffix})"
        suffix += 1
    return candidate


def join_relative(parent_relative: str, segment: str) -> str:
    """Append a segment to a parent's relative storage path."""
    return f"{parent_relative}/{segment}" if parent_relative else segment


def folder_subtree(session: Session, folder_id: str) -> list[Folder]:
    """Return `folder_id`'s subtree breadth-first, every parent before its children.

    All folders are loaded once. A dangling `parent_id` (a parent row that no
    longer exists) is treated as root scope, which is how migration 004's
    `effective_folder_parent` resolves it too. Children are ordered by
    (casefold(name), id) so the result never depends on row order, and a cycle
    cannot make the walk loop forever.
    """
    folders = list(session.exec(select(Folder)))
    known_ids = {folder.id for folder in folders}
    children: dict[Optional[str], list[Folder]] = {}
    for folder in folders:
        parent_key = folder.parent_id if folder.parent_id in known_ids else None
        children.setdefault(parent_key, []).append(folder)
    for siblings in children.values():
        siblings.sort(key=lambda sibling: ((sibling.name or "").casefold(), sibling.id))

    root = next((folder for folder in folders if folder.id == folder_id), None)
    if root is None:
        return []

    ordered: list[Folder] = []
    seen: set[str] = set()
    queue = [root]
    while queue:
        current = queue.pop(0)
        if current.id in seen:
            continue
        seen.add(current.id)
        ordered.append(current)
        queue.extend(children.get(current.id, []))
    return ordered


def converge_ancestor_paths(session: Session, folder_id: Optional[str]) -> str:
    """Give every path-less ancestor of `folder_id` a `storage_path`, root first.

    Returns `folder_id`'s relative path, or "" when there is no folder. Persist
    only: nothing is created, moved or renamed on disk. Folders that already have
    a path keep it exactly.
    """
    if not folder_id:
        return ""

    folders = {folder.id: folder for folder in session.exec(select(Folder))}
    chain: list[Folder] = []
    seen: set[str] = set()
    current = folders.get(folder_id)
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        current = folders.get(current.parent_id) if current.parent_id else None
    chain.reverse()

    for folder in chain:
        if folder.storage_path:
            continue
        parent = folders.get(folder.parent_id) if folder.parent_id else None
        parent_relative = (parent.storage_path or "") if parent else ""
        # A folder is excluded from its own scope: otherwise its own NULL name
        # segment counts as `used` and pushes it to `Name (2)`.
        segment = allocate_segment(folder.name, *sibling_scope(session, folder.parent_id, {folder.id}))
        folder.storage_path = join_relative(parent_relative, segment)
        session.add(folder)

    if not chain:
        # `folder_id` no longer exists (deleted while we were looking at it).
        return ""
    return chain[-1].storage_path or ""


def derive_subtree_paths(
    session: Session,
    folder: Folder,
    new_parent_relative: str,
    new_segment: str,
) -> dict[str, str]:
    """Map every folder in `folder`'s subtree to its new relative path.

    The walk follows `folder_subtree`'s breadth-first order so a parent's path is
    always known before its children's. Siblings that move in the same operation
    are not reflected in the database yet, so segments are allocated against a
    per-scope overlay seeded once from `sibling_scope`; every derived or reused
    segment is added to that overlay immediately. This is the runtime equivalent
    of migration 004's in-loop `sibling_used.add(...)`: without it two NULL-path
    casefold-colliding siblings would each derive `Name (2)` and the rename would
    die on `idx_folder_storage_path_unique`.

    Descendants that already have a path keep their last segment verbatim - the
    directory on disk keeps that exact name, so it must never be re-sanitised or
    re-truncated. A reused segment could in principle collide in the new scope;
    such a collision can only come from pre-existing bad data and surfaces as an
    IntegrityError, which the caller maps to a 409.
    """
    subtree = folder_subtree(session, folder.id)
    subtree_ids = {subtree_folder.id for subtree_folder in subtree}
    overlay: dict[Optional[str], tuple[set[str], set[str]]] = {}

    def overlay_for(parent_id: Optional[str]) -> tuple[set[str], set[str]]:
        if parent_id not in overlay:
            overlay[parent_id] = sibling_scope(session, parent_id, subtree_ids)
        return overlay[parent_id]

    paths: dict[str, str] = {}
    for current in subtree:
        parent_key = current.parent_id
        if current.id == folder.id:
            parent_relative = new_parent_relative
            segment = new_segment
        else:
            parent_relative = paths[current.parent_id]
            if current.storage_path:
                segment = current.storage_path.rsplit("/", 1)[-1]
            else:
                used, reserved = overlay_for(parent_key)
                segment = allocate_segment(current.name, used, reserved)
        paths[current.id] = join_relative(parent_relative, segment)
        overlay_for(parent_key)[0].add(segment.casefold())
    return paths
