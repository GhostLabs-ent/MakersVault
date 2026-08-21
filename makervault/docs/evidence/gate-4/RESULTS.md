# Gate 4 Results

**Gate:** 4 — Make ingestion observable and establish content truth

**Status:** Accepted — required Gate 4A complete; optional Gate 4B explicitly deferred

**Completed:** 2026-08-21

**Publication state:** Local only; owner deferred pushes until the coordinated v5.1 rollout

## Objective result

Mounted-library ingestion is now an observable operator workflow rather than a
startup-only log message. An administrator can deliberately rescan from **Settings →
Imports**, see an immutable copy/index mode snapshot, follow running and terminal
state, and inspect imported, unchanged, and failed counts plus bounded relative-path
failure details without container access.

The scanner retains exact source-path compatibility. A restart marks abandoned work
interrupted, and rerunning safely skips source paths that already have records. One
bad file or unreadable directory is isolated from later files, concurrent scans are
not started, and retained scan history is bounded.

## Delivered contract

| Gate 4A requirement | Result |
|---|---|
| Explicit mounted-library rescan | Authenticated `POST /settings/mount-import/rescan` and a disabled-while-running **Rescan now** action |
| Persistent status and counts | Schema migration 5 adds scan trigger, status, immutable mode, root, timestamps, counts, bounded details, and omitted-detail count |
| Visible results without logs | Settings polls only while a scan is running and displays the last durable result and relative-path failures |
| Safe repeat/recovery | Exact existing source paths are skipped; stale running scans become `interrupted`; a repeat is the resume mechanism |
| Failure isolation | Per-file work and `os.walk` errors are captured independently; one failure does not abort later eligible files |
| Bounded state | At most 50 failure details per scan and 100 scan records are retained |
| Copy ownership | MakersVault owns a managed copy that survives mount loss; mounted source bytes are not changed or deleted |
| Index-in-place ownership | No primary bytes are copied; mount availability remains required; rename stays disabled; deleting the entry leaves its source intact |
| No hidden batch cap | Hidden/unsupported paths remain policy exclusions; ordinary eligible mounted sets keep the existing per-file resource limits without a cumulative file-count cap |

## Executable browser evidence

`scripts/mount-scan-verification.sh` creates a disposable read-only mount containing
two valid STL files, one unsupported file, and one symlink fixture. It starts fresh
project-scoped database/storage volumes, drives the real browser with Playwright,
and removes the containers, volumes, and temporary mount on exit.

The accepted run recorded:

| Workflow | Imported | Unchanged | Failed | Visible detail |
|---|---:|---:|---:|---|
| First manual copy scan | 2 | 0 | 1 | `rejected.stl: Mounted source contains a symbolic link` |
| Repeat of unchanged mount | 0 | 2 | 1 | Same isolated rejected fixture |

The browser also proved that the copy explanation states managed-copy survival and
source immutability, and that switching the unsaved choice to index-in-place states
mount availability, rename, and source-deletion consequences before execution. Raw
machine-local JSON is written under the ignored
`benchmarks/organization/.artifacts/mount-scan.json` path.

## Automated verification

| Check | Result |
|---|---|
| API suite | Pass — 75 tests; repeated immediately with 75 tests passing again |
| Mounted scan lifecycle tests | Pass — copy survival, no-copy deletion ownership, exact-path repeat, bounded 55-failure fixture, unreadable directory continuation, UI/API failure result, one-active-scan coordination, unavailable root, and restart recovery |
| Mounted source security | Pass — regular-file containment and inside/outside symlink rejection retained |
| Migration tests | Pass — fresh and representative pre-v5.1 databases reach schema 5 idempotently with the new table |
| Web unit suite | Pass — 13 tests across 5 files, including copy/index ownership and status labels |
| Web production build | Pass |
| Browser mounted-scan workflow | Pass — first/repeat counts, failure visibility, and both ownership explanations |
| Bridge tests/build | Pass |
| Compose/security validation | Pass — development, canonical production aliases, smoke, preview benchmark, organization benchmark, and mounted-scan overlay |
| Container smoke | Pass — direct and same-origin API, headers, file policy, non-root UIDs, schema 5 |
| Full `make verify` | Pass on local commit `1f3b944` |

The pre-existing JWT tamper test was made deterministic after a repeated run exposed
that changing the final base64url character can alter only ignored padding bits. It
now mutates the first signature character; the API suite then passed twice.

## Gate 4B decision

Gate 4B is deferred from v5.1 at this checkpoint. SHA-256 ingest/backfill,
changed/unavailable no-copy state, provenance, and duplicate suggestions are additive
and remain desirable, but they introduce new long-running migration and recovery
work. The runbook permits them only after Gate 4A and release-critical work are
stable; Gate 5 has not yet proved representative upgrade, backup, restore, and
rollback behavior.

Deferral preserves the v5.1 release-critical path and does not weaken Gate 4A. Gate
4B can reopen as the first content-truth subgate after Gate 5, with bounded restartable
jobs and suggestion-only duplicate behavior. No hash, inferred license, automatic
grouping, merge, or deletion behavior was introduced.

## Data and rollback boundary

- Migration 5 is additive and does not rewrite assets, folders, source paths, or
  stored files.
- Scan records can be ignored by an older application rollback after restoring the
  matched pre-upgrade database snapshot required by the release procedure.
- Removing the rescan API/UI does not alter source ownership or existing assets.
- Copy scans create ordinary managed asset records; index-in-place scans keep the
  existing external-source contract.
- No source file is renamed, reorganized, overwritten, merged, or deleted by a scan.

## Local commit record

- `35d378e` — Gate 4 entry truth and implementation contract
- `6933947` — observable mounted-import implementation and tests
- `b6548a3` — disposable real-browser mounted-scan proof
- `1f3b944` — deterministic verification assertion and schema-5 smoke output
- `34fc875` — reliable cleanup for the existing preview/organization benchmark runners

All commits remain local. Nothing was pushed.
