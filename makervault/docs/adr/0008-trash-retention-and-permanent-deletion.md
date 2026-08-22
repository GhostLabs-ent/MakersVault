# ADR 0008: Trash retention and permanent deletion

**Status:** Accepted with owner amendment

**Proposed:** 2026-08-22

**Accepted:** 2026-08-22

## Context

Deleting an Asset currently deletes related-file rows, the Asset row, managed
primary and related bytes, and the derived thumbnail immediately. Filesystem cleanup
is best effort and is not atomic with SQLite. Deleting a no-copy Asset leaves its
external source untouched, but the library record still disappears immediately.

Gate 6 must make deletion recoverable before broader destructive bulk workflows are
allowed.

## Proposed decision

- Delete moves an artifact to Trash by setting its deletion time and original folder
  reference. All revisions, visible attachments, internal prepared payloads, and
  previews remain associated and recoverable.
- Trashed artifacts are excluded from normal navigation, search, selection, and
  duplicate suggestions unless the Trash view is active.
- Default retention is **Until space is needed**. Trashed content is retained
  indefinitely unless a new managed write would otherwise breach the configured
  storage free-space reserve. MakersVault then permanently deletes the oldest
  eligible trashed artifacts, one complete artifact at a time, only until the
  predicted write and reserve fit.
- Settings also offer **1 day**, **1 week**, **1 month**, and **Never**. Time-based
  policies permanently delete eligible Trash after the selected age. **Never**
  disables automatic purge even when a write lacks space; that write fails safely
  instead. Explicit permanent deletion and Empty Trash remain available for every
  policy.
- “Until space is needed” is capacity-triggered deletion, not byte overwriting. It
  runs before the storage filesystem is completely full so an upload, import,
  attachment, or revision write cannot be allowed to fail halfway merely to trigger
  cleanup.
- Restore returns the artifact to its original folder when it still exists. If the
  folder is gone, the UI requires confirmation to restore as Unassigned. A
  case-insensitive name conflict returns a choice to rename or select another folder;
  MakersVault does not silently replace the existing artifact.
- Permanent deletion is available only from Trash, names the number of artifacts and
  managed files affected, requires explicit destructive confirmation, and reports
  per-item results for bulk work.
- Permanent deletion removes every artifact revision, artifact/revision attachment,
  internal prepared payload, and derived preview. It never deletes an external
  no-copy source.
- Folder deletion keeps its existing non-content behavior for Gate 6: direct assets
  become Unassigned and child folders move to the root. Trash protects artifacts;
  a recoverable folder-tree feature is not implied.

## Filesystem transaction policy

Soft deletion changes only metadata and does not move bytes. Permanent deletion uses
a durable operation record and exact resolved paths:

1. Validate that every target is still in Trash and inventory managed versus
   external content.
2. Move managed files to an operation-specific quarantine on the same storage
   filesystem.
3. Delete database records in one transaction.
4. Remove quarantined bytes after the database commit.
5. If the database transaction fails, restore the quarantined paths. If final byte
   removal fails, retain a retryable cleanup record rather than claiming success.

Reconciliation reports orphaned quarantine content without silently deleting it.
Shared physical blobs are out of scope; if later introduced, reference counting and
garbage collection require a superseding ADR.

Automatic selection is oldest-deletion-time first with a stable UUID tie-breaker.
It never partially purges an artifact, never touches active artifacts or external
no-copy source bytes, and records which capacity request or age policy caused each
purge. If eligible Trash cannot satisfy the requested reserve, the write returns the
existing storage-capacity error without purging anything outside Trash.

## Alternatives considered

- **Never delete by default:** maximizes retention, but cannot recover space for a
  user who expects desktop-style capacity management and may leave uploads failing
  while reclaimable Trash exists.
- **Fixed-time deletion by default:** familiar and simple, but destroys content even
  when the installation has abundant space.
- **Move bytes when entering Trash:** makes a physical Trash tree but turns a
  reversible metadata action into a large partial-failure surface.
- **Delete database first, then files:** can orphan bytes and lose the information
  required for safe retry.
- **Delete files first, then database:** can leave a visible record whose only copy is
  already gone.
- **Trash folder trees:** broader and attractive, but adds hierarchy restoration and
  name-conflict policy without being necessary to protect artifact content.

## Consequences

Delete becomes fast and reversible regardless of library size. Storage is reclaimed
only through explicit, age-based, or capacity-triggered permanent deletion. The
Trash view must display deletion time, original location, total managed size,
external-source status, active retention policy, and permanent-delete consequences.

Backup manifests include trashed artifacts and all of their revisions until they are
permanently deleted. Restore from a vault backup preserves Trash state.

## Migration and rollback

Trash columns are additive and existing Assets begin active. Before any permanent
deletion implementation is enabled, the migration and API must prove that old
clients cannot accidentally invoke irreversible behavior through the former delete
route. Rollback may treat trashed records as active only if explicitly documented;
the supported operational rollback remains restoration of the matched pre-upgrade
database/storage snapshot.

## Superseding conditions

Revisit before adding quota-based retention, recoverable folder trees, multi-user
ownership, legal holds, remote/object storage, or shared physical blobs.
