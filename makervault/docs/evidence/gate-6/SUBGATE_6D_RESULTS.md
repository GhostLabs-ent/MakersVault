# Gate 6D Recovery and Compatibility Results

**Gate:** 6D — Recovery, compatibility, and Gate 6 closeout

**Status:** Accepted by the owner

**Date:** 2026-08-22

**Entry commit:** `ae6f5ac`

**Implementation commit:** `642735d`

**Accepted:** 2026-08-22

## Delivered recovery truth

- The outer `makersvault-backup` format remains version 1. New manifests carry a
  separate recovery-contract version 2, while the verifier accepts valid format-1
  manifests produced by the earlier schema-5 recovery implementation.
- Database summaries count revision, content-job, and purge-operation tables when
  present without changing the legacy summary shape for databases that predate
  those tables.
- Backup creation and verification now fail when SQLite and managed storage are
  inconsistent. The prior recovery implementation reported this state but could
  still create or verify the outer archive successfully.
- Schema-aware inspection covers active and trashed artifacts, every historical
  revision, current-revision ownership, artifact/revision prepared pointers,
  artifact-wide and revision-scoped files, managed digest/size identity, derived
  thumbnails, external no-copy references, and durable purge operations.
- Known `moving`/`quarantined` journal mappings let a matched crash snapshot locate
  authoritative bytes at either their source or quarantine path. Known
  `database_committed`/`cleanup_pending` quarantine is retained as journal-owned
  recovery content. Unknown quarantine is a hard inconsistency and is never
  modified by inspection.
- External no-copy revisions remain outside the archive. Available, unavailable,
  outside-mapping, and unknown states are reported; an offline external mount does
  not invalidate otherwise complete managed recovery.
- Missing derived thumbnails are reported but remain non-authoritative because the
  bounded preview system can regenerate them.

## Focused evidence

`api/tests/test_recovery.py` proves:

1. the existing schema-5 backup, verify, extract, and exact restored-component
   round trip still passes;
2. older format-1 manifest shapes remain verifiable;
3. schema-8 active/Trash multi-revision history, visible supporting files, hidden
   prepared data, derived previews, external no-copy content, and pending quarantine
   cleanup round-trip together;
4. row counts and the consistency manifest enumerate all five fixture revisions and
   its purge journal;
5. missing historical Trash bytes, cross-artifact current pointers, mismatched
   revision/file ownership, and unknown quarantine produce an inconsistent audit;
6. backup creation refuses that inconsistent matched pair; and
7. a managed historical digest mismatch is detected and cannot produce a backup.

`api/tests/test_migrations.py` proves a schema-7 database reaches schema 8
idempotently while preserving every artifact/revision ID, primary/source path,
prepared pointer, current pointer, and preview path. Existing artifacts receive
null Trash fields and remain active; no purge record is invented.

`api/tests/test_gate5_fixture.py` continues to prove the representative schema-4
library reaches schema 8 without data loss. Its recovery assertions now distinguish
the stable legacy content counts from the additional revision-aware report rather
than requiring both report shapes to be textually identical.

`api/tests/test_trash.py::test_delete_is_metadata_only_hidden_and_restorable` is the
old-client compatibility proof: the unchanged legacy `DELETE /asset/{id}` request
soft-deletes metadata, preserves bytes, hides the artifact, and remains restorable.

## Verification record

From repository root:

```text
make verify
```

Result: pass on 2026-08-22.

- API: `112 passed`
- Web: `13 passed`; TypeScript and production build passed
- Slicer bridge: Go tests and build passed
- Compose/security: canonical, deploy, compatibility, smoke, benchmark, and
  mount-scan manifests passed
- Container smoke: passed with schema 8 and non-root API/web processes
- Release contract: passed; immutable v5.1 source and artifacts remain unchanged
- `git diff --check` and Python compile checks passed before the implementation
  commit

Existing frontend dependency-age and bundle-size warnings remain non-blocking and
unchanged in class from the accepted v5.1 candidate.

## Recovery and rollback boundary

The supported rollback remains a verified, matched SQLite plus managed-storage
restore. Database-only rollback, storage-only rollback, manual migration-ledger
editing, and schema contraction are unsupported. An older application version must
start only after its matching pre-upgrade pair and configuration are restored with
services left stopped during image selection.

## Owner checkpoint

Accepted on 2026-08-22. This acceptance also closes Gate 6. The owner separately
authorized Gate 7 to begin.
