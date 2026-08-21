# Gate 3 Baseline and Entry Record

**Gate:** 3 — Complete scalable organization workflows

**Status:** In progress — reproducible baseline captured; workflow behavior unchanged

**Opened:** 2026-08-14

**Publication state:** Local only; owner deferred pushes until the coordinated v5.1 rollout

## Entry truth

Gate 3 begins from accepted Gate 2 commit `537fa58`. The current product already
has nested folders, folder search, deterministic API pagination, per-card selection,
metadata, model-name uniqueness within a folder, supporting files, and prepared-print
summaries. This gate is not replacing those capabilities; it is making their scope
and failure behavior understandable at library scale.

Source inspection and the executable baseline establish the following behavior:

| Area | Current behavior | Gate 3 gap |
|---|---|---|
| Folder location | The sidebar highlights the selected folder and searches full ancestor paths | The content pane has no breadcrumb; location depends on sidebar state and indentation |
| Nested folders | A three-level tree is rendered and ancestor nodes remain visible in search | A folder with no direct assets does not guide the user to its child folders |
| Pagination | The browser requests a responsive batch and appends with **Load more**; the API orders by name, filename, and ID and permits at most 1,000 rows per request | Client sorting only reorders loaded cards, and the UI does not define a selectable “page” |
| Selection | Checkboxes hold explicit loaded asset IDs; an item refresh prunes IDs that are no longer present | No selected count, select-loaded action, clear action, or visible bulk toolbar exists |
| Bulk discovery | Download, tag replacement, and permanent deletion become bulk actions only when invoked from an already-selected card | Users must discover bulk behavior through an individual card; move remains single-item only |
| Partial failure | Tag and delete operations loop through IDs in the browser and alert failed filenames after successful mutations have already committed | There is no progress, success list, structured result, or failed-only retry scope |
| Deletion | Single and multi-asset deletion permanently remove the record and managed files after a browser confirmation | Multi-delete is irreversible, implicit, and more powerful than the current recovery model |
| Folder deletion | Direct assets become unassigned and child folders move to the root; assets are not deleted | The confirmation mentions unassigned assets but not child-folder reparenting |
| Identity | A case-insensitive database index enforces model-name uniqueness within a folder; renaming also renames the primary filename and managed path | Concurrent conflicts need an intentional `409` result and UI evidence rather than an unhandled database failure |
| Supporting/prepared files | Supporting documents are visible inside the model entry; prepared payloads remain hidden behind their summary and slicer handoff | Gate 3 must prove organization changes do not expose or detach either role |

The current selection-pruning effect prevents hidden IDs from surviving a result
replacement. That is a useful safety property, but it is accidental rather than an
observable contract. Existing bulk tag editing also replaces every selected model's
tags with one card's edited list, which can silently discard distinct tags.

## Reproducible large-library contract

`benchmarks/organization/organization-baseline.mjs` creates a disposable library
through the supported API with:

- 600 OpenSCAD model records;
- 104 folders across three levels (8 roots, 32 branches, and 64 leaves);
- deterministic names, notes, and twelve tag buckets; and
- no automatic geometry-preview work, so the result isolates organization behavior.

The runner starts fresh project-scoped Docker volumes, measures API list/search and
folder queries, drives a 1440×900 headless Chromium session through login, incremental
loading, selection, filtering, folder search, and nested navigation, writes a local
JSON report, and removes the containers and volumes on exit.

Run from the repository root with:

```sh
./makervault/scripts/organization-benchmark.sh
```

Chromium must be installed for the pinned Playwright version. Raw machine-specific
output is written to `makervault/benchmarks/organization/.artifacts/baseline.json`
and is not committed. `MAKERSVAULT_ORGANIZATION_ASSETS` may raise the corpus size;
600 is the versioned representative baseline, not a product maximum or upload cap.

## Captured baseline

The uncontaminated run was captured at `2026-08-15T00:31:50Z` using Chromium 151 on
a 16-logical-core, 32 GiB host. Seeding all 600 assets and 104 folders through the
public API took 12.9 seconds.

| Measure | Baseline |
|---|---:|
| API first 25 assets, p50 / p95 | 8.3 / 9.7 ms |
| API exact title search, p50 / p95 | 7.7 / 60.3 ms |
| API nine-item leaf folder, p50 / p95 | 7.0 / 9.1 ms |
| API list 104 folders, p50 / p95 | 8.5 / 10.8 ms |
| Login to first 25 cards | 430 ms |
| Append next 25 cards | 208 ms |
| Exact browser search | 108 ms |
| Folder-path search | 92 ms |
| Open three-level leaf folder | 113 ms |
| JavaScript heap after workflow | 12.4 MiB |
| Long tasks | 0 |

The browser selected two cards, found no visible toolbar, then observed zero selected
cards after replacing the result with an exact search. Folder-path search correctly
showed the matching leaf and its two ancestors. The selected leaf displayed its nine
direct models. No breadcrumb landmark was present.

These numbers are comparative evidence from one machine, not universal timing
guarantees. Gate 3 verification will use the same corpus and require no long task
above 50 ms plus the following conservative targets on this profile: first cards
within 1 second; incremental load within 500 ms; exact search, folder-path search,
and folder open within 300 ms; and measured API p95 below 100 ms.

## Implementation constraints derived from the baseline

1. “Current page” will be labeled **loaded models** because the interface appends
   batches rather than replacing numbered pages.
2. Selection will contain explicit loaded IDs only. Loading another batch preserves
   selection; changing folder, search, or tag scope clears it; sorting the same loaded
   set preserves it.
3. There will be no “select every match” action and no arbitrary cap on non-destructive
   loaded-ID selection in Gate 3.
4. Move and tag operations will be idempotent per ID. Bulk tags will add or remove
   tags rather than replacing unrelated tags across different models.
5. Mutation progress will name the operation and completed count. Successful IDs
   leave the selection; failed IDs remain selected and receive per-item reasons.
   Blind retry of the original full set will not be offered.
6. Download is non-mutating and preserves selection. The existing server archive
   endpoint receives only the explicit selected IDs.
7. Database uniqueness remains authoritative. Rename and move conflicts must return
   an intentional `409` without overwriting files or leaving ambiguous UI state.
8. Supporting documents remain visible within their model. Prepared-print payloads
   remain non-browsable and are represented only by their summary and slicer action.

## Checkpoint still required

The baseline is captured and no organization behavior has changed. The owner decision
on irreversible deletion is requested in [OWNER_CHECKPOINT.md](OWNER_CHECKPOINT.md).

## Historical record disposition

The checkpoint was subsequently approved in [OWNER_CHECKPOINT.md](OWNER_CHECKPOINT.md),
and the verified implementation comparison is recorded in [RESULTS.md](RESULTS.md).
This file remains the unchanged-before-implementation measurement record.
