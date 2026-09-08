# Gate 13C — Chromium profiling and optimization proposal

**Status:** diagnostic slice complete; proposed application changes await owner approval.
Captured 2026-09-08 UTC / America/New_York. Gate 13C performance qualification is
still **OPEN**. No application source, dependency lock, image, budget, security
policy or frozen release pin changed in this slice. Nothing was pushed or published.

## Outcome

The strongest actionable product finding is repeated folder controls: every loaded
card mounts every destination, even with its dropdown closed. In the measured
104-folder library, 40 cards contain **4,200 folder options**. Application DOM
construction is visible in the traces, alongside expensive Playwright queries.
The largest elapsed pauses have much less renderer-thread CPU time; these captures
do **not** establish one CPU-bound application function explaining all prior stalls.

Recommend an on-demand, shared folder destination picker and a separately reviewed
benchmark-search correction, followed by unchanged-budget, unprofiled repeats.
These are proposals, not implemented fixes or demonstrated speedups.

## Identity, scope and complete attempt history

Application revision remains `12559336e6dfdc99b1761b2a62d80616d957020c`:

- API: `sha256:3a2f27a3a81a0c1ec6b12d89b7b8ed0cef0275c57f603b351e1897c50dbbca23`
- Web: `sha256:9758c81b7d068e5e1389c4dda6c811e38e4b209ffb226840872181a4833f05e5`
- Browser: `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`
  (local `makersvault-gate13-browser-fixed`, Playwright 1.62.1, Linux headless
  Chromium 151.0.7922.34). Application helper label `development-gate13b` is historical.

Harness `7d68d183e5c8ef9bbf5ce5885d3057889d474b85` adds opt-in private timeline,
CPU-stack, execution-context, resource, phase and long-animation-frame diagnostics.
`8e116107fd3575f65fe4b3c0943dd66c83f375f0` adds diagnostic-only DOM snapshots and
browser-container cgroup counters. Neither changes default browser behavior or
product code. The [runtime instructions](../../../benchmarks/browser-runtime/README.md)
describe the opt-in flag and trust/data-loss controls.

All five fresh fixtures use 600 Artifacts, 104 folders, depth 3, 20 initial cards,
40 after Load more, and nine in the selected folder. Browser memory remains 4 GiB,
shared memory 1 GiB, no explicit CPU quota. Fixture HTTPS passes valid-host and
wrong-host rejection checks. Real libraries and unrelated workloads were untouched.

[Machine-readable runs, reduced traces and raw hashes](chromium-profile-runs.json)
retain every attempt. Letters here are profiling-run IDs, distinct from the prior
[browser-correction attempts A/B](BROWSER_FIX_RESULTS.md).

| Run / harness | Mode | First cards | Load more / folder open | Page-observed long tasks | Result |
| --- | --- | --- | --- | --- | --- |
| A / `7d68d18` | Profile | 1072.3 ms | 264.9 / 104.8 ms | 58 ms, reported folder-navigation | FAIL: first cards and interaction |
| B / `7d68d18` | Profile | 908.3 ms | 211.4 / 154.1 ms | 312 ms navigation; 982 ms search | FAIL: interaction |
| C / `7d68d18` | Unprofiled control | 495.2 ms | 165.1 / 144.1 ms | Available; zero observed | PASS for this run |
| D / `8e11610` | Profile + DOM/counters | 678.6 ms | 173.9 / 135.0 ms | 703 ms navigation; 722 ms download | FAIL: interaction |
| E / `8e11610` | Unprofiled control | 528.0 ms | 176.1 / 108.3 ms | Available; zero observed | PASS for this run |

All five complete the functional assertions: pagination/selection, search, prepared
summary/supporting document with zero prepared-payload links, mixed move failure,
tag preservation, selected ZIP, Trash/cancel/restore, nested folders and breadcrumbs.
The <1000 ms first-card and ≤50 ms interaction long-task limits were never changed.
Profiling adds overhead and its timings are diagnostic, not qualification evidence.
Controls C/E do not replace prior unprofiled failures (including 1433.2 ms first
cards and a 713 ms navigation task). This small, sequential sample is not a
controlled idle-host experiment or a statistical reliability/performance clearance.

## Findings and confidence

### 1. Confirmed repeated DOM; bounded optimization target

[AssetGrid.tsx](../../../web/src/ui/AssetGrid.tsx) builds one memoized list of
Unassigned + all folders, then renders its entire contents in each card's native
select (lines 468 and 1795 at the application revision above). Memoizing the card
already exists; it does not eliminate the initial options for newly mounted cards.
Run D directly records:

| Snapshot | Cards | 105-option folder selects | Folder options | All options | All DOM elements |
| --- | --- | --- | --- | --- | --- |
| Initial cards | 20 | 20 | 2,100 | 2,188 | 4,647 |
| After Load more | 40 | 40 | 4,200 | 4,368 | 7,659 |
| Selected folder | 9 | 9 | 945 | 989 | 1,594 |

These are post-action snapshots, not identical-instant first-frame DOM measurements.
Other card controls account for the remaining options. The cost scales with
loaded cards × folders, despite pagination. No extra upload limit is proposed.

Run A's return to the library after restore has a **58.815 ms wall / 56.067 ms
renderer-thread CPU** task, a 49.628 ms application-bundle callback, and stack
witnesses in `createElement` / `appendChild` through React. Run B's initial
application-render task is 312.119 / 56.446 ms. These establish real DOM-building
work, but are not an isolated measurement assigning every millisecond to folder
options. A before/after implementation test is still required to establish benefit.

### 2. Confirmed test-driver cost; not all trace tasks are application long tasks

During Load more, renderer tasks spend **144.526 / 144.055 ms** (A),
**71.446 / 71.245 ms** (B), and **67.612 / 66.836 ms** (D) in wall/thread-CPU time.
Sampled stacks are Playwright's utility-world role/name queries, including
`isElementHiddenForAria` and accessible-name computation. Each task contains 40
layout and 40 style-update events. Folder-navigation label queries similarly take
53.609 / 53.581 ms, 56.255 / 56.219 ms, and 50.827 / 50.733 ms.

The corresponding page Long Tasks reports do not list all those query tasks.
Do not treat every CDP `RunTask` as a budget violation or subtract automation costs
blindly from existing failures. Existing whole-page role/label searches amplify
the large DOM; scope them to the intended sidebar, toolbar or card while retaining
real clicks, accessible role/name assertions and existing timer boundaries.

There is also phase-label uncertainty: the current benchmark labels a long task
with the phase at observer delivery. A's 58 ms entry is labelled folder-navigation
in its original report, while its timestamp falls before that phase mark, in the
Trash return-to-library work. Both observations are retained. Propose timestamp-
based phase attribution in a separately versioned metric, without silently
reclassifying historical passes/failures or weakening the interaction check.

### 3. Large elapsed pauses remain only partially explained

Run A's navigation GC task is **562.701 ms wall / 8.767 ms renderer CPU**.
Run B's search task is **982.913 / 22.943 ms**, mostly elapsed time inside a V8
interrupt event. Run D records a deferred application timer at **703.491 / 13.241
ms** and a driver text-selection task at **722.448 / 12.700 ms**. D's timer starts
after the first visible-card frame, despite the navigation label; it cannot be
the cause of that run's time to first visible cards.

Elapsed time is not proof of equivalent CPU computation. These observations may
include engine waits, scheduling or instrumentation costs; they do not identify
which is responsible or prove a GPU, API or other-host-workload cause. Run D's
browser cgroup reports `cpu.max = max 100000`, zero throttling before/after and no
memory-limit/OOM events. That excludes observed throttling in that cgroup, not all
host/ancestor scheduling or native-engine waits. An unrelated container remained
present; its observed uptime changed externally during the series, so the host
was not a controlled constant. We did not stop, restart or reconfigure it.

Initial JS resource duration is 18.9–52.3 ms across profiled runs. Runs B/D fetch
initial folders/assets/tags in roughly 24–36 ms; A's approximately 570 ms resource
durations overlap its GC pause. Resource timings include browser scheduling and
are not server CPU profiles. Two independent folder fetches are a secondary
source-review finding, not the demonstrated primary bottleneck. This organization
fixture uses synthetic SCAD files; it does not qualify arbitrary STL/3MF decoding.
The earlier mixed-preview/cache evidence remains separate.

## Proposed next slice — approval required

1. **Lazy, shared folder picker.** Keep each card's current folder path visible.
   Offer an explicit “Move to folder…” action; only opening it mounts one searchable
   destination picker. Preserve full paths, Unassigned, Viewer read-only behavior,
   keyboard navigation, focus return, Escape/cancel and no mutation before explicit
   confirmation. Retain conflict/error handling and the existing bulk-selection
   workflow. Ensure library refresh, deletion, permission failure or view changes
   cannot submit a move for the wrong Artifact. This adds an explicit move action
   instead of an always-mounted dropdown; review that small UX tradeoff with owner.
2. **Separate benchmark hygiene.** Scope expensive locators to the relevant UI
   region; keep accessible names, real interactions and assertions. Correct phase
   attribution with timestamps and retain old attribution for comparison. Do not
   bypass visibility/actionability, remove failing samples or adjust budgets.
3. **Verification before a performance claim.** Test keyboard/cancel/permission/
   conflict/stale-view behavior, then run the complete application gate and current
   request-order regressions. Capture exact rebuilt images. Repeat the unchanged
   600/104 unprofiled organization checks (at least three fresh Chromium fixtures;
   retain all results), Firefox/WebKit functional checks and a separately labelled
   larger-folder stress case. Verify closed-card folder-option counts no longer
   grow as cards × folders. If any budget still fails, retain the failure and
   continue scoped diagnosis; successful repeats alone do not accept Gate 13C.

No slicing, manual thumbnail obligation, upload quota, schema/authentication,
retention, storage layout or dependency change is included. Folder-fetch sharing
or broader bundle restructuring can be considered later if new evidence warrants it.

## Reproduction, privacy and verification

The five output roots are `/tmp/makersvault-g13c-profile-0908a` through `0908e`.
Use the browser runner with the exact IDs above, `--workflows organization
--browsers chromium`, a new output root, and `--profile-chromium` only for diagnostics.
Its source-identity check requires committed verification sources. Timings remain
environment-specific; reproducing a command is not a promise of identical timings.

Raw timeline/CPU/context observations stay private (0700 case directories,
0600 profile files); no fixture keys, credentials or raw traces are committed.
The [read-only reducer](chromium-profile-analysis.cjs) retains allowlisted metrics,
script paths/stack witnesses and SHA-256 hashes, never script bodies or credentials.
All five reductions were regenerated and compared field-for-field with the retained
JSON; artifact hashes, source/image identities, functional flags, profile/control
boundaries, DOM counts and four out-of-scope input refusals passed independent checks.
For example, from the repository root:

```sh
docker run --rm \
  -v /tmp/makersvault-g13c-profile-0908d:/tmp/makersvault-g13c-profile-0908d:ro \
  -v "$PWD/makervault/docs/evidence/gate-13/chromium-profile-analysis.cjs:/analyse.cjs:ro" \
  node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 \
  node /analyse.cjs /tmp/makersvault-g13c-profile-0908d
```

All three captures report complete tracing with no data loss. Their CPU profiles
contain 396/402/406 negative sample deltas, respectively; the reducer exposes this
and uses sample points only as stack witnesses, **not** time-weighted CPU shares.
It excludes tasks outside the CPU-capture interval and retains renderer `tdur`
separately from wall duration. Nested event totals overlap and must not be summed
as disjoint percentages. Approximate navigation alignment uses paired phase marks;
the original page-relative Long Tasks timestamps remain intact. The ≥45 ms trace
listing retains near-boundary diagnostics, not a replacement for the ≤50 ms gate.

`make verify-harness verify-release` from the repository root passes **19 Python /
14 Node tests**, five browser-script syntax checks and static release contract.
Four new Node tests cover single finalization, data-loss refusal, missing stream
and phase/metric availability. An initial invocation from the nested `makervault/`
directory had no Make target and is not counted as a pass. Full application/lifecycle
verification remains the named **351 API / 51 web** result at `1255933`; it was not
rerun or reattributed to profiling-only commits. Fixture containers were cleaned;
the unrelated desktop draft was not changed. No images changed, so no new advisory
rescan is claimed: the retained 181 API / 3 web matches remain unwaived.

Owner review of the proposed slice is next. Physical/native-platform evidence,
release scope/revision, matched bridge/distribution qualification, security
dispositions and final Gate 13 acceptance remain independent checkpoints.
