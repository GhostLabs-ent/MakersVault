# Gate 13C — large-folder and detail-preview diagnosis

**Date:** 2026-09-10. **Status:** diagnostic slice complete; application changes
below are proposals, not implemented fixes. Gate 13C remains OPEN.

## Outcome

There are **two confirmed actionable costs**: the sidebar mounts thousands of
closed-menu elements, and the browser test's label lookup can itself take hundreds
of milliseconds. Separately, a one-second detail-preview pause was reproduced,
but its exact browser/native wait mechanism remains **unresolved**. The captured
pause precedes the model-file request and is not a second of STL parsing or
WebGL-context creation. Do not infer GPU, Docker, network or host blame from that.

The final unprofiled stress control still fails folder search, interaction and
folder-list API p95. No timing limit, failure, security obligation or release pin
was changed to obtain a pass. There are no application, dependency, schema,
authentication or deployment changes in this slice. Nothing was pushed or published.

## Identity and complete attempt history

All six fresh synthetic fixtures use the same application as the
[picker verification](FOLDER_PICKER_RESULTS.md):

- Application `76b526d2a740bd33d04c92b06073b30063b0b9f8`.
- API `sha256:323acc46322c65dd6f64b11efdd3bb2361da9acc1a42265843d93e58d0c92a50`.
- Web `sha256:c223700def24cb46555446238c86c28208ca9b722b9e65709c9bdabe0ef0a4cb`.
- Browser `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`,
  local `makersvault-gate13-browser-fixed`, Playwright 1.62.1 / Chromium 151.0.7922.34,
  Linux headless. Historical helper version label: `development-gate13b`.

A uses harness `cfd3c2f`; B/C use `2738a00`, adding opt-in warm-metrics/detail
profiling. D/E/F use `3101b68`, adding diagnostic sidebar DOM counts and read-only
locator comparisons. Sources remain fixed during each run. Default workflow
actions, metric boundaries and budget enforcement are unchanged; diagnostic code
only runs with the explicit profiling flag. Preview reports add an explicit
`diagnosticProfile` field. These commits do not rebuild or alter application images.

[All six reduced records and raw hashes](residual-profile-runs.json) retain every
attempt. Preview runner exit 0 means functional probes and collection succeeded,
not that performance passed. Organization rows all finish their functional
assertions, including exact mixed-move IDs and original-byte/Trash checks.

| Run | Mode / fixture | Key observations | Disposition |
| --- | --- | --- | --- |
| A | Profile, 600 Artifacts / 1,040 folders | First cards 972.2 ms; folder search 934.9 ms; max interaction task 163 ms; folders API p95 119.6 ms | FAIL folder search, interaction, folder API; diagnostic timings |
| B | Warm-metrics/detail profile, 20-file mixed preview corpus | Detail ready 1,414.6 ms; 1,039 ms detail task; cold/warm/LightBurn zero observed tasks | Functional complete; detail target missed; diagnostic timings |
| C | Unprofiled preview control | Detail ready 369.5 ms; detail max task 71 ms; cold max task 232 ms | Functional complete; preview target missed |
| D | Profile + locator/DOM probes, 600 / 1,040 | First cards 1,658.1 ms; search 459.1 ms; max interaction 110 ms; folders API p95 110.5 ms | FAIL first cards, search, interaction, folder API; diagnostic timings |
| E | Second warm-metrics/detail profile, same corpus | Detail ready 258.5 ms; no detail tasks; cold max task 58 ms | Functional complete; cold target missed; no blanket preview pass |
| F | Unprofiled 600 / 1,040 control | First cards 562.0 ms; search 554.8 ms; max interaction 61 ms; folders API p95 101.7 ms | FAIL search, interaction, folder API |

Warm original-model requests and generated-thumbnail uploads remain zero in all
three preview runs; each detail probe requests its one model once. The corpus is
the same 20 fixtures / 66,037,534 bytes, including malformed/large/prepared examples;
the chosen detail model is the 417-byte, four-triangle ASCII STL. It does not
qualify arbitrary 3MF assemblies or hardware/native-platform behavior. Successful
E detail timing does not replace B/C or the previous 1,074 ms observation.

## 1. Confirmed application cost: eager sidebar DOM

D records the following post-action DOM. No folder-picker dialog is open.

| State | Whole-page elements | Sidebar elements | Folder rows | Closed menus | Elements inside those closed menus |
| --- | --- | --- | --- | --- | --- |
| 20 cards | 16,399 | 15,354 | 400 | 400 | 8,800 |
| 40 cards | 17,411 | 15,354 | 400 | 400 | 8,800 |
| Filtered one-card folder | 291 | 192 | 3 | 3 | 66 |

The previous per-card destination duplication remains removed: zero closed-card
folder options even at 1,040 folders. This is a **different remaining cost**.
[Sidebar.tsx](../../../web/src/ui/Sidebar.tsx) lines 462–470 expand every root by
default; with 80 roots and four branches each, 400 rows mount. Lines 530–565 render
all menu buttons/icons inside native `<details>`, whether the menu is open or not.
Those 8,800 hidden descendants are real DOM, not unloaded menu templates.

The trace confirms real application rendering work: A has a **90.0 ms wall /
84.6 ms renderer-thread CPU** application callback, and D a **98.7 / 95.7 ms**
callback with React creation/append stack witnesses. D's following rendering task
is 96.9 / 95.8 ms, including 31.2 ms style update and 23.4 ms layout events. These
are measured costs, but not an isolated assignment of every millisecond to menus.
A's 90 ms callback occurs after its first visible-card observation; it must not
be reported as causing that run's first-card latency.

There are also large wall/CPU gaps: A navigation 407.9 / 6.3 ms; D navigation
732.7 / 19.1 ms. Those pauses are not explained by equivalent CPU-bound DOM work.
The trace does not establish one sidebar function accounting for all startup time.

**Proposed bounded application change:** mount folder action-menu contents only
when opened. Preserve existing expansion, visible folder paths, action ordering,
keyboard/focus behavior, Viewer permissions, confirmation and upload/drop targets.
Test open/close/reopen, folder refresh/deletion and exact action ownership. Do not
change initial expansion policy, add a folder/upload quota, or introduce full tree
virtualization in the same slice. Memoization/path caching is a later target if
post-change traces justify it, not a demonstrated fix already delivered here.

## 2. Confirmed measurement cost: finding the search input

The measured folder-search action starts with
`sidebar.getByLabel("Search folders").fill(...)`. In A its utility-world lookup
contains a **474.9 ms wall / 472.2 ms CPU** task; in D's actual search it is
**405.2 / 407.5 ms**, with stacks in Playwright's `getElementLabels` / selector
evaluation. These are driver queries, not MakersVault's folder filtering function.
They materially inflate the 934.9 / 459.1 ms end-to-end test observations.

D separately reads the same input's `aria-label` through three locators, rotating
their order over three rounds. It does not type, change app state or replace any
normal workflow step:

| Locator | First read | Later reads |
| --- | --- | --- |
| Scoped label | 463.2 ms | 26.9 / 27.3 ms |
| Scoped textbox role and exact accessible name | 27.8 ms | 47.0 / 37.5 ms |
| Scoped `input[aria-label=…]` | 24.4 ms | 23.7 / 26.2 ms |

The cold/warm difference matters: this is not evidence that every label lookup
always costs 460 ms. Locator caching/order and DOM changes affect cost. Nor may
we subtract a trace duration from a failed historic metric and declare a pass.
Other wide role/text queries still have 50–440 ms driver tasks in bulk/Trash flows.
Not every CDP task appears in the page Long Tasks API; they are separate observations.

**Proposed benchmark correction:** use the scoped textbox role with exact
accessible name for this input, keeping the same timer start, real `fill`,
actionability checks and final visible-results assertion. Scope remaining expensive
queries where the trace identifies them. Retain all old reports and distinguish
measurement changes from application improvements. Do not prewarm selectors outside
the timer, force interactions, weaken thresholds or hide API/long-task failures.

## 3. Detail pause narrowed, underlying wait unresolved

The preview benchmark creates a WebGL context to report browser/renderer information
at the end of each warm phase. Its metrics are collected just before detail opens,
so measurement work and delayed observer delivery were plausible confounders.
New opt-in tracing covers **warm metric collection → detail reset → real double
click → ready → close**, all on one page/clock, and observes native context calls
without changing their receiver, arguments, return or exception behavior.

B reproduces the large pause:

- Browser-information WebGL context: 6.8 ms; viewer context: 5.7 ms.
- Detail click completes near page time 5,067.8 ms.
- Long task starts near 5,170.3 ms: **1,039.5 ms wall / 1.0 ms renderer-thread CPU**.
  No long application JS callback, layout or shader-compilation stack is attributed
  within that task. The nested scheduler work recorded is only 0.12 ms.
- `OrbitControls` import begins near 5,121.7 ms; response start is 5,125.1 ms and
  response end 6,162.0 ms, overlapping the pause. This is an observed coincidence,
  **not proof that network transfer or the import caused a synchronous block**.
- Preview-policy/model requests begin after the pause; the STL request starts at
  6,236.0 ms and takes 10.7 ms. STL parsing cannot explain a task before its request.

E, using the same images/corpus/profile settings, records context calls of
7.6 / 5.9 ms, a 2.3 ms OrbitControls request and no detail long task. C, without
profiling, still records 71 ms detail and 232 ms cold tasks; its aggregate report
does not identify their functions. Profiling overhead is not qualification evidence,
and the unprofiled failures cannot be dismissed because E was fast.

**Conclusion:** the captured one-second task is a genuine elapsed main-thread
pause, not a second of renderer CPU, model parsing or observed context creation.
The information-gathering context does not explain B's pause. These captures do
not identify the blocking native/engine operation, scheduling condition or network
mechanism. No parser rewrite, eager module preload, renderer replacement, GPU
configuration change or host-priority adjustment is justified by this evidence alone.
Next preview investigation should isolate browser/host scheduling and module-fetch
completion with a controlled native/quiet-host comparison or narrower engine/network
instrumentation, retaining the same application and data. Do not stop unrelated
workloads or change production deployment settings without explicit direction.

## 4. Folder-list API remains a separate failed metric

The 1,040-folder endpoint p95 is 119.6 / 110.5 / 101.7 ms in A/D/F, above the
unchanged <100 ms target. These probes run **before** browser tracing starts; they
cannot be explained away as profiler overhead. The baseline A/D/F asset-list,
exact-search and folder-page API probes remain below 30 ms p95. Browser resource
durations include scheduling and are not server execution profiles.

Source review of `list_folders` in [main.py](../../../api/main.py) shows a full
Folder query and output conversion, not a measured SQL bottleneck. The current
captures do not partition authentication, database, serialization, proxy or host
time. Keep this failure visible; separate API timing/profiling is needed before
proposing pagination, caching or another API contract change.

## Evidence limits, reproducibility and verification

All runs are sequential fresh production-HTTPS fixtures, 4 GiB browser memory,
1 GiB shared memory, no explicit browser CPU quota, valid-host trust and wrong-host
rejection. Profile cgroups report no throttling or memory-limit/OOM events.
This excludes observed cgroup throttling, **not** all host scheduling or native
waits. The shared workstation is not a controlled idle host; unrelated workloads
remain untouched. SwiftShader is software rendering, not native GPU qualification.

All four captures complete without reported trace loss. CPU profiles contain
453 / 31 / 482 / 21 negative sample deltas (A/B/D/E); sample points are retained
only as stack witnesses, never duration-weighted CPU percentages. Small wall/thread
CPU discrepancies remain explicit, not normalized. B/E include negative worker
resource durations (-6.6 / -3.0 ms), also retained as instrumentation anomalies,
not usable network latency. Nested event totals overlap and must not be summed
as disjoint percentages. Approximate phase alignment is not an exact display clock.

The [read-only reducer](residual-profile-analysis.cjs) retains allowlisted metrics,
safe script paths, source locations and raw SHA-256 hashes, not raw trace/script
bodies or credentials. It refuses out-of-scope paths, non-regular artifacts,
oversized/incomplete traces and mismatched phase observations. Example, from repo root:

```sh
docker run --rm \
  -v /tmp/makersvault-g13c-diagnose-0910b:/tmp/makersvault-g13c-diagnose-0910b:ro \
  -v "$PWD/makervault/docs/evidence/gate-13/residual-profile-analysis.cjs:/analyse.cjs:ro" \
  node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 \
  node /analyse.cjs /tmp/makersvault-g13c-diagnose-0910b
```

The [runtime instructions](../../../benchmarks/browser-runtime/README.md) document
`--profile-chromium` for organization or preview. Use exact images/revision above,
new private output roots and `--folder-stress` for organization only. Preview
profiling covers warm information collection/detail, not cold or LightBurn.
Normal controls use no profiler flag. Raw roots `...diagnose-0910a` through `0910f`
stay private; attempted early reduction of still-running F was refused rather than
treated as complete. No raw trace, fixture key, credential or host process inventory
is committed. The unrelated desktop draft remains untouched.

`make verify-harness verify-release` passes **19 Python / 28 Node tests**, six
browser syntax checks and static release contract. Seven added tests cover native
context forwarding/null/error/cleanup/bounds, phase marks and read-only locator
identity/order. Full application/lifecycle verification remains the prior named
351 API / 56 web result; it was not rerun or reattributed to diagnostic commits.
Images/locks are unchanged, so no new advisory scan is claimed. The existing
181 API / 3 web image matches remain unwaived.

Final read-only verification regenerates all six reduced records from their private
raw roots and matches them field-for-field, including 49 artifact-hash entries.
Identity/profile/failure and exact mixed-move assertions pass; six invalid reducer
path invocations are refused. All 159 local links checked across this report and
the five updated governing/evidence documents resolve. Reducer syntax and
`git diff --check` pass. Application/bridge/Compose inputs remain unchanged, and
all owned test containers are gone; the unrelated host workload remains untouched.

## Next owner checkpoint

Approve or revise the **lazy sidebar-menu plus scoped accessible-locator** slice,
then repeat unchanged-budget baseline/stress and keyboard/permission/action tests.
Keep detail native-wait and folder-API profiling as explicit unresolved tracks;
do not present that bounded optimization as fixing them. Physical/native-platform,
advisory disposition, release scope and matched-distribution decisions remain open.
Gate 13C is not accepted; Gate 12 stays desktop-deferred and public rollout remains
separately gated.
