# ADR 0007: Artifact revision ownership and immutable history

**Status:** Proposed for Gate 6 owner checkpoint

**Proposed:** 2026-08-22

## Context

Schema 5 stores logical identity, organization, primary-file state, prepared-print
state, and preview state together on `Asset`. Supporting and prepared files use
`AssetFile`, but only one prepared file is current and supporting files cannot be
scoped to a primary-file revision. Replacing or renaming a primary file changes the
single current record; there is no historical state.

Gate 6 must establish trustworthy history without prematurely introducing Projects
or relocating every existing byte.

## Proposed decision

`Asset` remains the compatibility name for the logical artifact during Gate 6.
Internally, it gains exactly one current `ArtifactRevision`; each revision is an
immutable description of one primary-file state.

### Ownership

Artifact-owned metadata:

- human-readable name and title;
- folder, tags, collection, creator, and general notes; and
- created identity and Trash state.

Revision-owned metadata:

- revision number and creation time;
- primary filename, MIME type, size, SHA-256, managed/external location, and content
  availability state;
- revision change note;
- prepared payload pointer and extracted printer/material/nozzle/time summary; and
- preview status, reason, attempts, policy version, source, update time, and derived
  thumbnail identity.

Visible supporting files are artifact-owned by default because assembly PDFs,
licenses, source material, and general notes commonly describe the whole item. The
schema permits an optional revision association for a document that applies only to
one version. Prepared files are always revision-owned and remain hidden from normal
file browsing while their useful summary stays visible.

### Current and restore semantics

- Every non-trashed artifact has exactly one current revision.
- A normal primary-file replacement creates a new revision only after the staged
  bytes, size, and digest are verified. The current pointer changes in the database
  transaction only after the immutable revision record exists.
- Uploading bytes identical to the current revision is a no-op with a clear response,
  not noisy history.
- Historical records and managed bytes are never overwritten in place.
- Restoring a historical revision creates a new current revision from its verified
  bytes and records that origin. It does not rewrite history or merely hide the
  revisions that followed it.
- An unavailable or changed no-copy historical revision cannot be restored until
  its recorded bytes are available and match, or the user deliberately imports a
  managed copy as a new revision.

### Storage and previews

Migration seeds revision 1 with the current Asset paths and does not relocate bytes.
New managed revision bytes use a collision-free internal revision namespace keyed by
artifact and revision UUID. A stored revision path is immutable even if artifact
name, folder, tags, collection, or the operator's storage template later changes.
The configured human-readable layout continues to govern ordinary organization and
export naming; Gate 6 must not repeatedly relocate historical bytes to mirror mutable
metadata.

Each revision has its own derived preview identity. Retention keeps historical
previews while the revision exists, but missing previews remain rebuildable and do
not block revision restore or export.

### Export

The normal artifact download remains current-revision-first for compatibility. A
separate revision-history export includes a versioned manifest, all available
managed primary revisions, artifact-wide attachments, revision-scoped attachments,
prepared payloads as internal-role content, hashes, and explicit missing/changed
external references.

## Alternatives considered

- **Keep metadata snapshots as JSON:** simple to add, but weak referential integrity
  makes recovery, attachment ownership, and backup verification fragile.
- **Put all metadata on revisions:** preserves complete snapshots but makes renaming,
  filing, tagging, and provenance edits create misleading content revisions.
- **Keep all attachments artifact-wide:** simpler UI, but prepared output and
  version-specific documentation can become associated with the wrong geometry.
- **Relocate all existing files into a new layout:** visually uniform but violates
  the no-relocation migration requirement and increases rollback risk.
- **Point restore directly at an old row:** storage-efficient but fails to record the
  restoration as a new historical event.

## Consequences

The UI can keep familiar model/asset terminology during Gate 6 while exposing a
current version and history. Artifact metadata edits do not create revisions.
Primary replacement, prepared payloads, previews, and optionally scoped documents
become version-correct.

The compatibility layer temporarily duplicates current primary fields on `Asset`.
Writes must use one application service that updates the revision record and legacy
projection together; tests and reconciliation detect drift. Contracting the legacy
columns waits for at least one stable release.

## Migration and rollback

Use expand, seed, verify, dual-read/write, and later contract:

1. Add revision tables and a nullable current pointer.
2. Seed one revision for every Asset using existing paths without moving bytes.
3. Verify every Asset maps to one revision and that managed/external resolution is
   unchanged.
4. Enable revision-aware reads and writes while maintaining legacy projections.
5. Contract legacy primary/prepared/preview columns only after a stable release and
   a new owner-approved migration.

Rollback before contraction uses the maintained legacy projection. Release rollback
after schema use restores the matched pre-upgrade database and storage snapshot.

## Superseding conditions

Revisit when Gate 7 introduces Projects, when supporting-file workflows prove the
default scope wrong, or before physical content-addressed/object storage.
