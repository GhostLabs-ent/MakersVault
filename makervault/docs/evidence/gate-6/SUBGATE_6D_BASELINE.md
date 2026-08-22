# Gate 6D Recovery and Compatibility Baseline

**Gate:** 6D — Recovery, compatibility, and Gate 6 closeout

**Status:** Approved to begin

**Date:** 2026-08-22

**Entry commit:** `92447a3`

## Purpose

Close Gate 6 by proving that its additive schema and storage behavior remain
recoverable. This subgate changes recovery inspection and documentation where
needed; it does not add another user-facing data model or contract legacy columns.

## Compatibility contract

- Schema 7 upgrades to schema 8 without relocating bytes. Every existing artifact
  starts active, and its current revision, supporting files, prepared file, preview,
  and source ownership remain unchanged.
- The backup container remains `makersvault-backup` format version 1. Verifiers stay
  able to inspect older schema backups whose tables or columns predate revisions and
  Trash.
- Schema-aware manifests count active and trashed artifacts, all immutable
  revisions, related files, content-hash work, and durable purge operations when
  those tables exist.
- Consistency inspection validates every managed revision byte, revision and
  artifact current/prepared pointers, related-file ownership, and known purge
  quarantine. A current managed byte missing from the matched storage snapshot is a
  hard inconsistency whether the owning artifact is active or in Trash.
- Mounted no-copy revisions remain references, not backup payload. Their availability
  is reported as available, unavailable, outside the configured mapping, or unknown;
  an unknown/offline external source does not make a matched managed backup corrupt.
- Derived thumbnails may be regenerated. Referenced revision thumbnails are
  inventoried when present, but a missing thumbnail is reported separately and does
  not invalidate authoritative model content.
- A purge operation whose database deletion committed but quarantine cleanup is
  pending owns its recorded quarantine files. Those bytes are included in the
  storage snapshot and must not be mislabeled as unknown orphan content.
- Legacy clients using `DELETE /asset/{id}` receive the Gate 6C soft-delete behavior.
  No compatibility path may restore immediate destructive deletion.

## Required evidence

1. Focused schema-7-to-8 upgrade and migration-idempotence tests.
2. A format-1 backup/verify/extract/restore round trip containing multiple active
   and trashed revisions, revision and artifact attachments, prepared metadata,
   previews, external no-copy content, and a pending quarantine cleanup.
3. Negative checks for missing historical revision bytes, broken current/prepared
   pointers, cross-artifact revision/file ownership, and unknown quarantine paths.
4. Verification that existing schema-5 backup fixtures still create and verify.
5. A documented operator recovery sequence and explicit matched-pair rollback
   boundary for schema 8.
6. The complete repository verification harness and release immutability contract.

## Stop conditions

- Do not bump or silently reinterpret the outer backup format in a way that rejects
  already-produced format-1 backups.
- Do not copy mounted external content into managed backup storage.
- Do not delete, repair, or adopt unknown quarantine content during verification.
- Do not contract legacy Asset columns or authorize a database-only/storage-only
  rollback.
- Do not publish or push Gate 6 commits while the owner keeps v5.1 work local.

## Exit checkpoint

Gate 6D is ready for owner review only when every required evidence item is recorded
and the Gate 6 exit claims are traceable to passing tests. Owner acceptance closes
Gate 6; Gate 7 must not begin automatically.
