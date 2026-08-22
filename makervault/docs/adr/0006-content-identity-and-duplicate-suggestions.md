# ADR 0006: Content identity and duplicate suggestions

**Status:** Accepted

**Proposed:** 2026-08-22

**Accepted:** 2026-08-22

## Context

The schema-5 `Asset` record identifies a user's library entry by UUID and records
size and a managed or external path, but it does not identify the bytes. Mounted
scans use exact source path as compatibility identity. MakersVault therefore cannot
reliably distinguish a renamed file, changed external content, or a byte-for-byte
duplicate.

Gate 6 needs content truth for revision detection, integrity checks, changed-source
states, duplicate suggestions, and revision-aware backup manifests. It must not
turn duplicate detection into automatic merging or impose a collection-size limit.

## Proposed decision

- SHA-256 identifies exact bytes. It does not identify an artifact, model, project,
  filename, or semantic equivalence.
- The digest belongs to an artifact revision, not to the mutable artifact record.
- New managed ingestion calculates size and SHA-256 in the existing streaming write,
  avoiding a second full read.
- Existing managed and no-copy records are backfilled by a bounded, durable,
  resumable job. The worker processes one file at a time by default and records
  aggregate progress plus bounded failures.
- No library-wide file-count quota is introduced. Per-file safety and free-space
  reserve policies remain independent of how many files a user selects or owns.
- A revision records an explicit content state: `pending`, `ready`, `unavailable`,
  `changed`, or `failed`, with a stable reason and last-check time.
- External no-copy bytes remain externally owned. A later verification that differs
  from the recorded digest marks the revision `changed`; it does not overwrite the
  recorded digest or silently create, merge, or delete a revision.
- Matching SHA-256 and size may produce a duplicate suggestion. MakersVault does not
  auto-merge, replace, hard-link, or delete either entry.
- Hashing is local and does not upload digests or filenames to a remote service.

The content fields should be introduced with the revision expansion so content
identity is not first attached to `Asset` and immediately migrated again. Gate 6A
may seed one revision per existing Asset with a pending digest while retaining the
legacy Asset read/write columns through the compatibility window.

## Alternatives considered

- **Path identity only:** preserves current behavior but cannot prove integrity or
  revisions and fails the Gate 6 dependency.
- **Hash on first comparison:** avoids a backfill but leaves backups and mounted
  change detection indefinitely incomplete.
- **Physical content-addressed storage now:** can deduplicate bytes, but forces a
  broad storage-layout migration before the logical identity is proven.
- **Automatic duplicate merge:** saves space but violates the product invariant and
  can destroy distinct metadata or intent.

## Consequences

Hashing a large existing library consumes time and I/O, but remains bounded and
restartable. Progress and individual failures must be visible; other library work
continues while it runs. A ready digest allows exact duplicate suggestions and
manifest verification but does not prove that two files represent the same design.

The first implementation remains filesystem-backed. Physical blob deduplication or
content-addressed storage requires a later ADR and independent recovery evidence.

## Migration and rollback

Expansion creates the revision/content-state records without moving existing bytes.
Backfill updates only new fields and job records. It can stop and resume without
changing file ownership. Rollback may leave additive tables ignored by the older
application; operational rollback still restores the matched database/storage
snapshot when old code cannot safely interpret a newer schema.

## Superseding conditions

Revisit before introducing physical deduplication, S3/object storage, remote digest
lookup, another hash algorithm, or cross-vault synchronization.
