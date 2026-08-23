# Gate 6 Closeout Results

**Gate:** 6 — Establish revisions and recoverable deletion

**Status:** Accepted by the owner

**Date:** 2026-08-22

**Publication state:** Local commits only; nothing in Gate 6 has been pushed

**Accepted:** 2026-08-22

## Exit-evidence traceability

| Required Gate 6 exit claim | Evidence | Result |
|---|---|---|
| Existing Assets migrate without byte relocation | Gate 6A migration/content tests; schema-7→8 preservation test in Gate 6D | Pass |
| Revision creation never overwrites historical bytes | `test_revisions.py` replacement, restore-as-new, rename, preview, and export cases | Pass |
| Restore is tested | Revision restore creates a new revision; Trash restore preserves byte identity and handles folder/name conflicts explicitly | Pass |
| Permanent deletion is tested | Trash confirmation, external preservation, quarantine rollback, cleanup retry, reconciliation, and capacity/time policy cases | Pass |
| Mounted changed/missing content has explicit states | Gate 6A content-job tests and recovery external-state fixtures | Pass |
| Backup manifests represent all revisions | Gate 6D schema-8 round trip and missing/changed historical-byte rejection | Pass |

## Accepted architecture delivered

- ADR 0006: SHA-256 is content identity and duplicate behavior remains suggestion
  only—never automatic merge or deletion.
- ADR 0007: artifact metadata is stable across immutable revisions; restore creates
  a new revision; supporting and prepared ownership is explicit; history exports
  are complete and self-describing.
- ADR 0008: ordinary deletion is metadata-only Trash; retention defaults to Until
  space is needed; permanent deletion is explicit and journaled; external sources
  are never deleted.
- Legacy Asset projections remain during the compatibility window. Gate 6 did not
  contract them or introduce Project records prematurely.

## Subgate record

| Subgate | Implementation | Owner state | Evidence |
|---|---|---|---|
| 6A — content truth and revision expansion | `c7e8743` | Accepted 2026-08-22 | `SUBGATE_6A_RESULTS.md` |
| 6B — immutable revision workflows | `c6ddcfe` | Accepted 2026-08-22 | `SUBGATE_6B_RESULTS.md` |
| 6C — recoverable Trash | `71c3d82` | Accepted 2026-08-22 | `SUBGATE_6C_RESULTS.md` |
| 6D — recovery and compatibility | `642735d` | Accepted 2026-08-22 | `SUBGATE_6D_RESULTS.md` |

Supporting evidence-only commits follow each implementation in local history. The
immutable v5.1 release boundary remains source `f6ff55b`; Gate 6 is later local
history and is not part of that frozen candidate.

## Complete-gate verification

The post-6D `make verify` run passes with 112 API tests, 13 web tests plus type/build,
Go bridge test/build, every canonical/compatibility/security/benchmark Compose
check, non-root schema-8 container smoke, and the immutable v5.1 release contract.

## Boundaries carried into Gate 7

- Operational rollback is a matched database/storage restore, not schema
  contraction.
- Trash restores artifacts, not deleted folder trees.
- Historical revisions cannot be independently erased.
- Unknown quarantine is operator-diagnosed and never auto-deleted.
- No-copy external bytes remain externally owned and outside server backups.
- Gate 6 does not add Projects, arbitrary relationships, multi-user permissions,
  printer control, or visible prepared G-code browsing.

## Final owner checkpoint

Accepted on 2026-08-22. The owner confirmed that Gate 6 meets its exit evidence and
separately authorized Gate 7 to begin.
