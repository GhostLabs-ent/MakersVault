# Gate 4A Baseline and Entry Record

**Gate:** 4A — Observable mounted-library ingestion

**Status:** In progress — current behavior captured; implementation not yet changed

**Opened:** 2026-08-21

**Publication state:** Local only; owner deferred pushes until the coordinated v5.1 rollout

## Entry truth

Gate 4A begins from accepted Gate 3 commit `e7f50c6`. Mounted import is currently a
startup-only background task. It scans one configured, read-only mount, mirrors source
directories as MakersVault folders, and either copies each eligible file into managed
storage or indexes it in place.

Source inspection and the executable security baseline establish the following behavior:

| Area | Current behavior | Gate 4A gap |
|---|---|---|
| Trigger | A daemon thread starts during API startup when a mount path is configured and the persisted startup setting is enabled | No explicit rescan action exists |
| Result | Imported, skipped, and failed counts are local variables printed to container logs | No durable status, timestamps, mode snapshot, counts, or UI-visible failures exist |
| Repeat safety | An exact resolved `source_path` match skips an existing record | The behavior is undocumented in-product; concurrent scans are not excluded; moved or renamed sources remain path-distinct |
| Failure isolation | Most per-file validation, copy, indexing, and preview failures increment a counter and continue | Directory traversal and setup failures can escape the per-file boundary, and the failed path/reason is discarded |
| Copy ownership | The source is opened beneath the configured root and copied into managed storage; the source path remains recorded for repeat-scan compatibility | The UI does not explain that MakersVault owns the managed copy while leaving the mounted source untouched |
| Index-in-place ownership | No primary bytes are copied; reads fall back to the mounted source, rename is disabled, and deleting the entry removes the database record and derived thumbnail without deleting the source | The UI mentions read-only behavior but does not fully state availability and deletion consequences before execution |
| Extension filtering | Hidden paths and disallowed extensions are omitted; unchanged eligible source paths count as skipped | Operators cannot distinguish filtering, unchanged files, and failures |
| Root failure | A missing or invalid mount path prints one log line and returns | The operator sees no failed scan record or actionable result |

The path is the compatibility identity for Gate 4A. Content hashing and changed-source
detection belong to optional Gate 4B and will not be smuggled into this slice.

## Gate 4A implementation contract

1. Persist each scan as a durable record with trigger, immutable copy/index mode,
   status, start/end timestamps, imported/skipped/failed counts, and bounded failure
   details. Store only relative source paths in failure details.
2. Treat stale `running` records as interrupted after process restart. A repeat scan is
   the resume mechanism: already-recorded exact source paths are skipped.
3. Serialize scans in-process. A second startup or manual request must report the
   active scan instead of starting overlapping work.
4. Add an authenticated manual rescan endpoint and an Imports-settings action. Manual
   scans use the last saved mode and may run only when a mount path is configured and
   mounted.
5. Count every eligible file as exactly one of imported, skipped, or failed. Hidden and
   unsupported files remain excluded by policy rather than inflating the skipped count.
6. Bound persisted failure details to 50 entries and record the omitted count. One bad
   file or unreadable directory must not abort remaining traversal.
7. Preserve existing source-path compatibility and source ownership. Gate 4A does not
   reorganize, rename, overwrite, merge, or delete mounted sources.
8. Explain before execution:
   - **Copy into MakersVault:** MakersVault keeps a managed copy; the mounted source is
     read-only and is never modified or deleted.
   - **Index in place:** no primary bytes are copied; the mount remains authoritative
     and must stay available; deleting the MakersVault entry does not delete the source.
9. Keep scan polling bounded and active only while the Imports settings view is open.
   The browser receives aggregate state and at most the bounded failure list, never an
   unbounded per-file event stream.

## Baseline verification

The pre-change mounted-source security suite was rerun in the pinned API test image:

```text
python -m pytest -q tests/test_mount_security.py
2 passed in 0.51s
```

It proves regular-file containment and rejection of symlink traversal. Gate 4A will
retain those tests and add lifecycle, repeat-scan, failure-isolation, mode-ownership,
API, and browser contract coverage.

## Exit evidence required

- A manual scan exposes its running and terminal state without reading container logs.
- A second scan of unchanged fixtures creates no duplicate assets and reports skips.
- One bad file and one unreadable traversal location produce bounded details while
  later valid files still import.
- Copy mode survives removal of the source fixture; index-in-place never deletes or
  relocates its source and reports the ownership consequence before scanning.
- Restart recovery marks abandoned running work interrupted and permits a safe repeat.
- The full repository verification harness passes with schema migration 5.

Gate 4B remains closed until this evidence is complete and Gate 4A stability is
assessed explicitly.
