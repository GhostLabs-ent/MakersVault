# Gate 3 Evidence Review

**Gate:** 3 — Complete scalable organization workflows

**Status:** Accepted

**Evidence date:** 2026-08-21

**Accepted:** 2026-08-21

**Baseline commit:** `02aa49f`

**Approved contract commit:** `ec5dc36`

**Verified implementation:** `188b2e9`

**Publication state:** Local only; owner deferred all pushes until the coordinated
v5.1 rollout

## Objective result

Large-library navigation and bulk work are now explicit. The content pane shows a
clickable folder breadcrumb, child folders remain useful when a parent has no direct
models, and selecting any card opens one visible toolbar with its exact loaded-ID
scope. Move, additive/removal tagging, and download report their progress and preserve
failed IDs for deliberate retry.

Permanent deletion is limited to one named model at a time under the approved
pre-Trash contract. The previous hidden selected-card multi-delete and tag-replacement
paths are removed.

## Implemented contract

- Breadcrumb segments navigate from **All files** through every active-folder
  ancestor; the current segment is exposed as the current page.
- A folder with child folders but no direct models links to those children instead
  of presenting an unexplained blank grid.
- The selection toolbar shows the selected count, **Select loaded**, **Clear**,
  **Move**, **Tags**, **Download**, and **Delete…**.
- Selection contains explicit loaded IDs only. It survives **Load more** and loaded
  sorting, and clears when folder, search, or tag scope changes.
- “All server matches” is absent. The sort label says **Sort loaded** so appended
  client-side scope is not misrepresented as global ordering.
- Bulk move and tag changes execute per ID with bounded sequential progress. Succeeded
  IDs leave selection; failed or unprocessed IDs remain selected with model-specific
  reasons. The original full set is not offered as a blind retry.
- Bulk tag operations add or remove requested tags case-insensitively while preserving
  unrelated tags on each model. Per-card editing remains an intentional replacement
  for that one model only.
- Selected download uses the existing exact-ID archive contract and preserves
  selection.
- One selected model receives a confirmation naming permanent removal of primary and
  supporting files. Two or more selected models receive the approved Trash/restore
  explanation and no confirmation or delete request.
- Folder deletion now states that direct models become unassigned, direct children
  move to root, and model files are retained.
- Name-changing and move transactions are serialized in the supported API process.
  The case-insensitive database index remains authoritative; a late integrity conflict
  restores the prior managed path and returns `409`.
- Card memoization prevents a selection checkbox from rerendering every loaded model.
  The initial responsive batch is based on content width rather than including the
  fixed sidebar width.

## Final deterministic measurement

The clean candidate run was captured at `2026-08-21T20:30:38Z` with Chromium 151 on
a 16-logical-core, 32 GiB host. The disposable corpus contained 600 models and 104
folders at three levels. Four models exercised mixed move conflict, distinct tags,
one visible assembly PDF, and one hidden prepared G-code payload with extracted
printer/material/nozzle/layer/duration metadata.

| Measure | Entry baseline | Gate 3 candidate |
|---|---:|---:|
| API first-page p95 | 9.7 ms | 12.4 ms |
| API exact-search p95 | 60.3 ms | 10.7 ms |
| API leaf-folder p95 | 9.1 ms | 10.0 ms |
| API 104-folder list p95 | 10.8 ms | 12.6 ms |
| Login to first cards | 430 ms / 25 cards | 433 ms / 20 cards |
| Append next batch | 208 ms / 25 cards | 201 ms / 20 cards |
| Exact browser search | 108 ms | 78 ms |
| Folder-path search | 92 ms | 87 ms |
| Open three-level leaf | 113 ms | 105 ms |
| Interaction long tasks | 0 | 0 |
| JavaScript heap after workflow | 12.4 MiB | 15.5 MiB |
| Visible breadcrumb / selection toolbar | No / No | Yes / Yes |

The candidate intentionally loads 20 rather than 25 cards at 1440 px because the
responsive calculation now subtracts the fixed sidebar and main chrome before
requesting five visual rows. The benchmark asserts first cards under 1 second,
incremental load under 500 ms, search/navigation under 300 ms, API p95 under 100 ms,
and no organization-interaction long task above 50 ms.

## Exit-criterion evidence

| Gate 3 exit criterion | Status | Evidence |
|---|---|---|
| Active-folder navigation is unmistakable | Passed | Browser traversed a three-level path, found exactly the leaf plus two ancestors in sidebar search, opened the leaf, and returned to its parent through the breadcrumb. |
| Empty parents preserve nested navigation | Passed | Parent with no direct models displayed both child-folder links; the browser opened the expected child. |
| Selection scope is explicit across pagination and filters | Passed | Two IDs survived **Load more**, the toolbar reported them, and exact search cleared both. Unit tests cover selection result reduction. |
| Bulk operations expose mixed outcomes | Passed | One of two selected moves succeeded and one received a name conflict; the failed model and reason remained selected. |
| Tags preserve model-specific metadata | Passed | Both models gained the requested tag while retaining their different pre-existing tags. |
| Concurrent rename conflict is safe | Passed | Two simultaneous same-folder renames produced one `200` and one `409`; two unique names and both readable files remained. |
| Supporting/prepared roles remain correct | Passed | Assembly PDF was a visible supporting link; prepared summary named Bambu Lab P1S/PLA/0.4 mm/0.2 mm/3h 12m; G-code was not a browsable link. |
| Destructive behavior matches owner decision | Passed | Multi-delete showed the Trash/restore explanation with no browser dialog; single-delete named primary/supporting removal, and cancellation retained selection. |
| Representative large library remains usable | Passed | All timing bounds passed on 600 models/104 folders with zero measured interaction long tasks. |

## Verification

| Check | Result |
|---|---|
| API organization, migration, security, archive, preview, and handoff suite | Pass; 67 tests under Python 3.11 |
| Web type check and unit suite | Pass; 10 tests |
| Production web build | Pass |
| Compose development/deployment/benchmark validation | Pass |
| Fresh container smoke | Pass; schema 4, direct/same-origin API, security headers, 512 MiB ingest policy, non-root API/web |
| Bridge tests/build | Pass; unchanged handoff boundary |
| Complete repository harness | Pass; `make verify` against the `188b2e9` implementation working tree |
| Deterministic organization benchmark | Pass; executable assertions cover navigation, selection, mixed failure, tags, download, file-role visibility, and deletion behavior |

The existing production main-bundle size and stale browser-metadata warnings remain
unchanged release residuals; neither warning invalidated type checking, tests, build,
or container smoke.

## Data, upgrade, and rollback result

Gate 3 adds no schema migration and does not rewrite existing libraries. Breadcrumb,
selection, and progress state live in the browser. Move, rename, and tag changes still
use the established managed-storage relocation rules and database constraints.

Bulk move and tags operate on exact IDs and are idempotent at the requested end state.
If a partial result occurs, succeeded IDs are removed from selection and the exact
failed IDs remain. Rolling back the UI removes the new workflow without transforming
stored metadata; rolling back after an intentional move/tag operation does not undo
that user-requested operation.

## Residuals and next decision

- Permanent multi-model deletion remains deferred until Trash and restore are
  implemented and verified.
- Selecting every server-side match remains deferred until an API bulk contract can
  avoid materializing thousands of IDs in the browser.
- Sorting is intentionally explicit loaded-card sorting in Gate 3; server-global sort
  fields can be added with a future paginated query contract.
- Bulk move/tag mutations are sequential exact-ID requests. This favors observable
  recovery over throughput; a future server job contract must retain per-ID results.

The owner approved Gate 3 closeout on 2026-08-21. Gate 4 may begin from the
accepted organization and deletion contracts when the owner authorizes its start.
