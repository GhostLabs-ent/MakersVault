# Gate 6 Owner Checkpoint

**Status:** Awaiting owner decision

**Prepared:** 2026-08-22

Gate 6 changes the meaning of a model entry and introduces irreversible permanent
deletion. The runbook requires these decisions before schema implementation. The
recommendations below form one coherent contract.

## Recommended decision package

1. **Artifact versus revision metadata**
   - Artifact: name/title, folder, tags, collection, creator, and general notes.
   - Revision: primary filename/type/size/hash/location/state, revision note,
     prepared payload and summary, and preview state.

2. **Current revision**
   - Exactly one current revision per active artifact.
   - A verified replacement creates a new immutable revision and then changes the
     current pointer.
   - Identical normal replacement is a no-op.
   - Restoring history creates a new revision from verified old bytes so the restore
     itself remains in history.

3. **Supporting-file ownership**
   - Visible supporting files are artifact-wide by default.
   - An optional revision scope supports version-specific documentation.
   - Prepared files are always revision-specific and remain hidden from normal file
     browsing while their extracted summary remains visible.

4. **Preview retention**
   - Preview state and derived thumbnail identity belong to a revision.
   - Historical previews are retained while the revision exists, but remain
     rebuildable and are not required for restore/export correctness.

5. **Storage layout**
   - Migration references every existing byte in place.
   - New revisions use an immutable, collision-free internal namespace keyed by
     artifact/revision UUID; later name, folder, tag, collection, and template edits
     do not relocate historical bytes.
   - Configured human-readable naming remains relevant to normal organization and
     export, but cannot be allowed to rewrite history.

6. **Revision export**
   - Normal download remains current-first for compatibility.
   - Complete-history export has a versioned manifest, hashes, all available managed
     revisions and attachments, internal-role prepared payloads, and explicit
     missing/changed no-copy references.

7. **Trash and permanent deletion**
   - Normal delete becomes metadata-only Trash for the artifact and everything it
     owns.
   - Default retention is **Never automatically delete**.
   - Restore is conflict-aware and never overwrites another artifact.
   - Permanent deletion exists only inside Trash, requires explicit destructive
     confirmation, uses durable quarantine/reconciliation, and never touches
     external no-copy bytes.
   - Folder deletion retains its current detach/unassign behavior; Gate 6 does not
     add recoverable folder trees.

8. **Compatibility window**
   - Existing Asset IDs and byte locations remain stable through migration.
   - Schema-5 current-file fields remain as a maintained compatibility projection
     for at least one stable release.
   - Gate 6 does not contract them.

## What approval authorizes

Approval accepts ADRs 0006–0008 and authorizes Gate 6A schema and service
implementation under this contract. It does not authorize automatic Trash purge,
physical content deduplication, Project entities, printer control, publication, or
removal of legacy Asset columns.

## Alternative choices requiring direction

The owner may instead choose any of these material alternatives before approval:

- make all supporting documents artifact-wide or revision-specific;
- have restore merely reactivate an old revision instead of recording a new one;
- use a finite automatic Trash retention period such as 30 or 90 days;
- relocate existing bytes into a uniform revision layout during migration; or
- include recoverable folder trees in Gate 6.

Each alternative changes migration, recovery, or user-visible semantics and must be
written into the ADRs before implementation.
