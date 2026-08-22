# Gate 6C Recoverable Trash Results

**Gate:** 6C — Recoverable Trash, retention, and permanent deletion

**Status:** Implementation complete; awaiting owner acceptance

**Date:** 2026-08-22

**Entry commit:** `37400ad`

**Implementation commit:** `71c3d82`

## Delivered truth

- The legacy `DELETE /asset/{id}` route now performs metadata-only soft deletion.
  It records a UTC deletion time and the original folder ID/breadcrumb. It does not
  move or delete primary, historical revision, attachment, prepared, preview, or
  external-source bytes.
- Trashed models are excluded from normal models, search, tags, folder downloads,
  bulk downloads, duplicate suggestions, direct primary/revision/preview/supporting
  downloads, handoff, preview mutation, metadata mutation, attachment upload, and
  revision replacement/restore/export surfaces.
- Restore returns to the surviving original folder. A missing folder produces a
  structured conflict that the UI can explicitly retry as Unassigned. A
  case-insensitive active-name conflict produces a separate structured conflict and
  never overwrites or silently renames either model.
- Active models may reuse a name held only in Trash. Managed storage collision
  avoidance gives the new active bytes a deterministic UUID-derived path suffix,
  leaving the recoverable bytes untouched.
- Retention choices are exactly **Until space is needed** (default), **1 day**,
  **1 week**, **1 month** (30 days), and **Never**. An hourly maintenance worker and
  startup pass apply time retention. Saving a time policy also applies already-due
  retention immediately.
- Every managed write reserve check may invoke safe capacity reclamation. Under
  Until space is needed it purges the oldest complete trashed artifact first with
  stable ID ordering and stops as soon as the predicted write and reserve fit.
  Fixed-time policies reclaim only already-expired Trash. Never performs no
  automatic deletion, so the write retains the existing safe `507` failure.
- Permanent delete and Empty Trash accept trashed artifacts only and require the
  exact confirmation phrases `PERMANENTLY DELETE` and `EMPTY TRASH`. Responses name
  each artifact, managed file/byte totals, outcome, and whether an external source
  was preserved.
- Permanent deletion inventories exact managed ownership, records a durable
  operation and source/quarantine map, moves bytes into same-filesystem quarantine,
  commits database ownership deletion, then removes quarantine. A database failure
  restores moved bytes. A cleanup failure records `cleanup_pending` for retry.
- Startup reconciliation restores known incomplete moves when database ownership
  remains and completes quarantine cleanup when deletion committed. Unknown
  quarantine directories are reported through Trash diagnostics and never deleted
  automatically.
- The new Trash view shows deletion time, original location, versions, managed file
  count/size, external ownership, Restore, Permanent delete, Empty Trash, and the
  active retention policy. Normal multi-select deletion now safely moves complete
  selections to Trash. Retention is configurable in Settings.
- Schema 8 is additive. Existing artifacts begin active, existing byte paths remain
  unchanged, and the active-name uniqueness index becomes partial so Trash does not
  reserve an active library name.

## Focused evidence

`makervault/api/tests/test_trash.py` proves:

1. metadata-only deletion and byte preservation;
2. exclusion from normal lists, tags, downloads, mutations, uploads, revisions, and
   handoff;
3. successful restore with byte identity;
4. explicit missing-folder restore-as-Unassigned confirmation;
5. active-name conflict rejection without overwrite;
6. exact permanent-delete and Empty Trash confirmation phrases;
7. per-artifact Empty Trash outcomes;
8. external no-copy source preservation;
9. database-failure rollback from quarantine;
10. retryable cleanup failure and successful reconciliation;
11. unknown-quarantine reporting without deletion;
12. stable oldest-first capacity selection;
13. Never policy capacity behavior;
14. one-day, one-week, and thirty-day eligibility boundaries; and
15. the exact owner-approved settings choices.

Migration, revision, content-identity, and resource-limit suites additionally prove
schema expansion and idempotence, no byte relocation, compatibility permanent
cleanup of all revision paths, and preservation of the existing `507` reserve
contract.

## Verification record

From repository root:

```text
make verify
```

Result: pass.

- API: `107 passed`
- Web: `13 passed`; TypeScript and production build passed
- Slicer bridge: Go tests and build passed
- Compose/security: canonical, deploy, smoke, benchmark, and mount-scan manifests passed
- Container smoke: passed with schema 8
- Release contract: passed; the immutable v5.1 candidate remains unchanged
- `git diff --check`: passed before the implementation commit

Existing non-blocking frontend dependency-age and bundle-size warnings remain the
same class already recorded for the v5.1 candidate.

## Boundaries carried forward

- Gate 6C does not add recoverable folder trees. Deleting a folder keeps the existing
  child-folder/root and active-model/Unassigned behavior; trashed models retain
  their original-location snapshot for restore confirmation.
- Individual historical revisions cannot be deleted independently. Trash and purge
  operate on complete artifacts only.
- Unknown quarantine content requires operator diagnosis. MakersVault reports but
  deliberately does not guess ownership or delete it.
- Durable purge-operation records retain bounded per-operation audit metadata after
  content is removed; Gate 6 does not add an operation-log retention policy.
- Operational rollback remains restoration of the matched database and managed
  storage backup. Schema contraction is not authorized.

## Owner checkpoint

Accept Gate 6C before beginning Gate 6D recovery, compatibility, and closeout.
Acceptance confirms desktop-style metadata-only Trash, the five retention choices,
oldest-complete-artifact capacity cleanup, explicit typed permanent deletion,
external-source preservation, and durable quarantine/reconciliation semantics.
