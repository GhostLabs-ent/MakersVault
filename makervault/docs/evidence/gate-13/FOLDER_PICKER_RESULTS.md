# Gate 13C — on-demand folder picker and current browser evidence

**Date:** 2026-09-09 America/New_York (captures span September 9–10 UTC).
**Status:** approved implementation verified locally; Gate 13C remains OPEN.
Three fresh Chromium organization runs pass the unchanged enforced budgets.
The larger-folder stress cases retain first-card/folder-search/interaction failures, and a separate
detail-preview probe records a **1,074 ms long task**. Neither is
performance-qualified. Neither successful workflow completion nor this optimization
is a blanket browser-performance clearance. No push, tag, publication or deployment.

## Delivered scope

The owner approved the [profiling proposal](CHROMIUM_PROFILE_RESULTS.md).
Each card now displays its current folder path and an explicit **Move to folder…**
action. A single searchable destination dialog mounts only when opened; full paths
disambiguate duplicate leaf names, and Unassigned is explicit. Search/selection
alone never moves an Artifact: a separate confirmation is required.

The dialog supports keyboard navigation, focus containment/return, Escape/cancel,
an opaque surface and a narrow viewport. Current-folder and missing destinations
cannot be submitted. Failed moves retain actionable errors and allow deliberate
retry. Duplicate submission and cancellation during a confirmed request are blocked.
Source identity, current view/request ownership and permission are checked before
submission; superseded/departed responses cannot update a new view or sign it out.
Current 401 still requires sign-in. Viewer UI is read-only and the API independently
enforces authorization. Existing bulk selection/move workflows remain intact.

There is no new upload quota, manual thumbnail requirement, slicing, schema,
authentication, retention, storage-layout or dependency change. The picker mounts
one list when open; it is not a virtualized or server-searched folder list. Sidebar
and other controls still have their own DOM costs. No unlimited-scale claim follows.

## Source, image and verification identity

- Application: `76b526d2a740bd33d04c92b06073b30063b0b9f8`.
- Browser measurement harness D–G: `53142f9561edc7a5c417da9bcd61fc2c7b6a27ce`;
  H/I use `10c7481e98dd6bfb05ce01013c897ff31279c5a6` with the explicit bulk-completion wait.
  The ordering/picker matrix C used the same application with harness `76b526d`.
- API: `sha256:323acc46322c65dd6f64b11efdd3bb2361da9acc1a42265843d93e58d0c92a50`.
- Web: `sha256:c223700def24cb46555446238c86c28208ca9b722b9e65709c9bdabe0ef0a4cb`.
- Browser: `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`;
  local `makersvault-gate13-browser-fixed`, Playwright 1.62.1, Linux headless
  Chromium 151.0.7922.34 / Firefox 153 / WebKit 26.5.

The application helper version label `development-gate13b` is historical, not a
release candidate. Frozen Gate 5 identities and scope remain unchanged.

[Complete verification record](folder-picker-verification.json): **351 API tests,
56 web tests in 15 files**, type/build, bridge, Compose/security, fresh-container
smoke and Chromium virtual-passkey checks pass. The joined production-HTTPS drill
passes schema 4→17 upgrade, contract-6 raw restore with pre-start revocation/audit,
exact stopped schema-4 rollback, and portable 17→12→17 fresh-identity startup with
18 compared members and no-mutation refusal cases.

Source truth: the final full `make verify` began its unchanged API phase at
`e88c253`; the two-line TypeScript compatibility fix was committed as `76b526d`
before web/harness/lifecycle phases. API/bridge/Compose/dependency inputs did not
change. All executed inputs match the final revision, but the invocation did not
start at that revision. A direct web test invocation also passes all 56 tests.
That full run had 19 Python / 20 Node harness tests; the later harness-only
initialization-order correction passes **19 Python / 21 Node tests**, six browser
syntax checks and static release verification. It does not reattribute 21 tests
to the earlier full run.

## Browser attempt history — nothing discarded

[All synthetic reports and raw artifact hashes](folder-picker-browser-runs.json)
retain these attempts. IDs here are distinct from earlier browser/profile letters.

| Attempt | Scope and disposition |
| --- | --- |
| A | Development `744886b` Chromium picker pass; screenshot exposed a translucent dialog surface, corrected in `bb0aefe`. Not final-image evidence. |
| B | Mixed-source, unqualified attempt. The command wrapper reached its 120-second limit and its parent ended; raw summary remains `in_progress`. WebKit focus failure and partial organization report remain retained. No case qualifies the final build. |
| Debug A | Diagnostic assertion-location probe on old `744886b` images identified WebKit's Tab focus-wrap failure. Not a final-build performance run. |
| C | Final application: seven Chromium request-order cases and all ten named picker cases in Chromium, Firefox and WebKit PASS. |
| D | Final application/harness: three-engine organization functional matrix, Chromium preview/cache functional probes and mounted-import assertions complete. Chromium organization budgets PASS; preview timing requires the separate disposition below. |
| E / F | Second and third fresh unprofiled Chromium organization runs, same 600 Artifacts / 104 folders and unchanged enforced budgets: PASS. |
| G | Separately labelled 600-Artifact / 1,040-folder Chromium stress: FAIL first cards, folder search and mixed-move selected count (two instead of one). Not a replacement for the baseline. |
| H | Fresh stress with completion-aware harness `10c7481`: exact mixed-move selection and all functional assertions PASS; FAIL folder search and 51 ms interaction task. G is not erased. |
| I | Additional fresh 600/104 Chromium baseline on `10c7481`: exact mixed-move selection, all functional assertions and unchanged enforced budgets PASS. This is separate from D–F. |

`e88c253` added explicit focus wrapping after the WebKit failure; its first compile
failed because NodeList spread and `Array.at` exceeded the existing TypeScript
target. `76b526d` uses `Array.from` and indexed access without changing the target
or dependencies. These failed development checks are not reported as passes.
`53142f9` preserves timing and profile phase setters regardless of initialization
order, with a regression test; application images did not change.

G also exposed a benchmark completion-boundary problem: it waited for the failure
message and immediately counted selected cards. `runBulkMutation` can display that
message before its awaited list refresh and final successful-ID deselection.
`10c7481` waits for the move panel to close at completion, then checks the count
**and the exact successful/failed card selection states**. That strengthens the
final-state assertion without removing G's failed observation, changing application
behavior or relaxing any timing budget. Focused checks again pass 19 Python /
21 Node tests, six browser syntax checks and static release verification.
H observes completion with one selected card: successful ID unchecked, conflict ID
checked. This verifies that final state on H, not a retroactive pass for G.

For B, the exact abandoned disposable project was identified by labels/mounts and
cleaned, including only its generated containers/network/volumes. Its reports were
not rewritten. Remaining runs use the session-capable runner without the short
output-wrapper limit. Real libraries, host certificate trust and unrelated workloads
were untouched. No source changes occurred during qualifying browser runs.

## Functional and measurement boundaries

C verifies real keyboard open/search/select/Enter/cancel/focus return, Tab/Shift-Tab
containment, full-path matching, no-match/current-destination refusal, 390-pixel
dialog fit, exact-ID moves, Unassigned, original bytes, real name conflict/retry,
deleted destination/Artifact errors, permission refusal, double-submit protection,
stale-view/refresh/401 handling, and a real Viewer account plus API denial.
Background refresh/navigation races are explicitly injected lifecycle tests, not
actions available through an inert modal or performance evidence. The dialog
screenshot was visually reviewed; this does not certify the whole app's mobile
layout or assistive-technology behavior.

Organization checks retain pagination, selection reset, exact search, nested
folders/breadcrumbs, prepared summaries with zero prepared-payload links, supporting
documents, mixed bulk failure, tag preservation, selected ZIP and Trash/cancel/restore.
All engines pass valid fixture HTTPS and wrong-hostname rejection. Firefox/WebKit
organization results are functional only: first-card observations are 1,228 /
2,903 ms, respectively, and Long Tasks API metrics are unavailable, **not zero**.
The existing harness does not enforce Chromium timing budgets on those engines.

Organization report schema 4 scopes driver searches to their intended UI regions,
checks response identity and actual folder/card completion, and retains both
browser first-visible-frame and legacy driver-wait clocks. Long-task attribution
schema 2 uses start timestamps and interaction overlap while retaining legacy
delivery-phase attribution. The enforced interaction maximum is the conservative
union of all three: relabelling cannot erase an old-style interaction violation.
Pending observer entries are flushed. Budgets remain API p95 <100 ms, first cards
<1,000 ms, load more <500 ms, search/folder search/open <300 ms and interaction long
tasks ≤50 ms. Old results are neither overwritten nor recalculated as new passes.

## Organization measurements

All qualification runs are unprofiled, in fresh synthetic HTTPS fixtures with
4 GiB browser memory, 1 GiB shared memory and no explicit CPU quota. Runs are
sequential without our builds/scans running alongside them; an unrelated host
workload remains present. This is not an idle-host controlled experiment.

| Chromium run | Artifacts / folders | First visible cards | Load more | Exact search | Folder search / open | Interaction long task | Enforced budgets |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D | 600 / 104 | 603.3 ms | 369.0 ms | 62.2 ms | 44.9 / 68.7 ms | 0 ms observed | PASS |
| E | 600 / 104 | 865.2 ms | 135.3 ms | 60.1 ms | 36.6 / 115.6 ms | 0 ms observed | PASS |
| F | 600 / 104 | 546.9 ms | 109.4 ms | 78.3 ms | 43.8 / 88.5 ms | 0 ms observed | PASS |
| G — stress | 600 / 1,040 | 1,612.4 ms | 164.1 ms | 97.1 ms | 494.9 / 60.7 ms | 50 ms | FAIL first cards / folder search; also selected-count assertion |
| H — stress | 600 / 1,040 | 499.6 ms | 171.2 ms | 76.0 ms | 454.7 / 104.0 ms | 51 ms | FAIL folder search / interaction |
| I — completion recheck | 600 / 104 | 585.6 ms | 108.8 ms | 80.4 ms | 23.5 / 90.0 ms | 0 ms observed | PASS |

E also records a **142 ms navigation long task**, excluded from the existing
interaction-only limit but retained here. Zero interaction tasks is not zero
long tasks everywhere. The first-card budget still passes. Historical failures
at `1255933`, including 1,433.2 ms first cards and 713 ms navigation, remain in
[their original record](BROWSER_FIX_RESULTS.md).

G retains navigation tasks of 591 / 94 / 83 ms and two 50 ms Trash tasks; the latter
meet, but do not beat, the existing ≤50 ms interaction limit. All measured API p95
values pass; the 1,040-folder endpoint is close to its bound at 99.3 ms. G uses
80 roots / 320 branches / 640 leaves at depth 3, with one Artifact in its selected
leaf (baseline: 8 / 32 / 64 and nine Artifacts in the selected leaf).
H also retains a 90 ms navigation task and its 51 ms Trash task. Its folder API p95
is 75.5 ms. Faster startup in H does not erase G's first-card failure; folder search
misses the unchanged bound in both fresh stress attempts.
I passes the additional exact-selection assertions and records zero long tasks;
its DOM counts match D–F. It is an additional final-harness baseline check, not
a substitute for the three earlier baseline attempts or either failed stress run.

The directly comparable closed-control snapshots show the intended reduction:

| 104-folder library | Previous folder options / all elements | Current folder options / all elements |
| --- | --- | --- |
| 20 cards | 2,100 / 4,647 | 0 / 2,647 |
| 40 cards | 4,200 / 7,659 | 0 / 3,659 |
| Selected folder, 9 cards | 945 / 1,594 | 0 / 694 |

Current total option counts are 88 / 168 / 44; remaining options belong to other
controls. Snapshots are post-action observations with no open dialog, not exact
first-frame snapshots. Baseline D–F pass the same functional and timing thresholds,
but application and driver-query changes were delivered together: this is not an
isolated speedup estimate or proof that every earlier pause had one cause.

G still has **zero per-card folder options**, with 88 / 168 total options at
20 / 40 cards; the closed-card cross-product is removed at ten times the folder
count too. Total DOM remains 16,399 / 17,411 elements, falling to 291 in the
searched one-card folder view. This isolates remaining scale work from the removed
card dropdowns, not every millisecond of the failed timings.
H has the same 20/40-card DOM counts and 300 elements in its one-card folder view.

Bounded follow-up source review identifies the existing sidebar as a concrete
candidate: [Sidebar.tsx](../../../web/src/ui/Sidebar.tsx) default-expands every root,
renders its visible descendants recursively, and mounts action-menu contents even
while each `<details>` is closed. Search computes full paths across all folders
and changes the rendered tree. These facts are consistent with the larger DOM;
they are **not a trace-based attribution** of G's elapsed pauses. Sidebar changes
were not bundled into this approved card-picker scope. Profile that path before
proposing lazy menus, cached paths or a changed initial expansion policy; preserve
folder visibility, keyboard behavior and upload/drop targets.

## Separate preview and mounted-import observations

D's 20-file / 66,037,534-byte mixed preview corpus settles without timeout:
16 cold original requests, 14 persisted thumbnails, three skipped and three failed
fixture states; warm original requests and generated-thumbnail uploads are zero.
Maximum observed original-request concurrency is one. LightBurn produces one cold
original request/thumbnail upload and no warm original request. Cold/warm/LightBurn
record zero Long Tasks entries, but maximum event-loop drift is 641.5 / 144.3 ms
in cold/warm probes. These metrics observe different things and are not interchangeable.

The detail preview becomes ready in **1,345.8 ms** with one original request and
records a **1,074 ms long task**. This does not satisfy the ≤50 ms preview target;
its cause has not been attributed to an application function, renderer/driver or
scheduling. The runner's exit 0 asserts functional behavior and collection, **not
preview budget clearance**. Cold/warm card readiness uses the unchanged legacy
driver metric (1,957.1 / 183.9 ms), not the corrected organization frame metric.
SwiftShader is software rendering; one 401 console message and two ReadPixels
warnings remain recorded, not proof of the long task's cause. No arbitrary 3MF,
hardware-accelerated or native-workstation performance qualification is claimed.

Mounted import reports two imported files, then two skipped on repeat; both scans
reject the synthetic symlink. UI copy/index ownership and failure details pass;
the runner verifies all source bytes and the symlink target unchanged. This is a
copy-mode fixture check, not real NAS/provider qualification.

## Security, reproduction and next owner checkpoint

The [fresh exact-image scan](folder-picker-audit.json), Grype 0.118.0 with validated
database built 2026-09-09 06:31 UTC, reports **181 API / 3 web package matches**.
All reduced advisory/package/version/severity/source/namespace/location/match/fix
records equal the retained remediation inventory; equality is checked, not inferred
from totals. Raw hashes and unchanged lock hashes are retained. No language-lock
rescan, scanner suppression or risk acceptance is implied. Remaining OS/interpreter
dispositions stay open under [G13-04](../../security/GATE_13_REVALIDATION.md).

Use the [browser runner instructions](../../../benchmarks/browser-runtime/README.md)
with the exact image IDs above, revision `76b526d2a740bd33d04c92b06073b30063b0b9f8`,
version `development-gate13b`, browser image `makersvault-gate13-browser-fixed`,
a new private output root, and `--workflows organization --browsers chromium`.
Add `--folder-stress` only for the separate larger-folder case. C uses
`--workflows ordering folder-picker --browsers chromium firefox webkit`.
No profiling is used in D–I. Reproduction does not promise identical elapsed times.

The [read-only reducer](folder-picker-analysis.cjs) accepts only the named synthetic
run IDs, hashes log/screenshot artifacts without publishing log bodies, refuses
unexpected files/symlinks, and retains public generated reports. From the repo root:

```sh
node makervault/docs/evidence/gate-13/folder-picker-analysis.cjs browser a b debug-a c d e f g h i
node makervault/docs/evidence/gate-13/folder-picker-analysis.cjs audit
```

Raw output roots are `/tmp/makersvault-g13c-picker-0909a` through `0909i`, plus the
named debug/audit roots in the JSON. Fixture private keys/credentials are excluded
from committed evidence. The unrelated desktop draft remains untouched.

Final read-only checks regenerate both retained JSON records and compare them
field-for-field, including raw hashes, all ten attempts, source/image identities,
baseline/stress boundaries, unavailable metrics, exact-ID completion assertions and
the unwaived audit inventory. Six invalid reducer invocations are refused; all 205
local document links checked resolve. `git diff --check` passes. All owned test
containers are gone; the unrelated host workload was not changed.

The approved folder-picker slice is implemented; no further approval is needed
to describe it as delivered locally. Next proposed bounded work is **profiling
the larger-folder startup/search path and the detail-preview long task on these
exact images before proposing another code change**, retaining failed samples and
existing targets. Broader performance
qualification, physical passkeys/native workstation evidence or explicit support
limits, advisory dispositions, owner-selected release scope/revision and matched
distribution qualification remain checkpoints. Gate 13C is not accepted or ready
for closeout. Gate 12 stays desktop-deferred; publication remains separately gated.

### September 10 diagnostic follow-up

The owner-authorized [residual diagnosis](RESIDUAL_DIAGNOSIS.md) is complete on
these unchanged images. It confirms 8,800 closed sidebar-menu descendants in the
stress fixture and expensive driver label lookups, distinct from the removed
per-card options. The captured one-second detail pause precedes the model request
and consumes about 1 ms of renderer-thread CPU; its exact native wait is unresolved.
Folders API p95 also fails separately. Six new attempts retain all failures;
lazy sidebar menus plus a scoped accessible locator are proposed for approval.
No further application fix or performance acceptance is claimed.

The subsequent owner-approved [sidebar-menu implementation](SIDEBAR_MENU_RESULTS.md)
is delivered at `82cb2cc`; it retains these earlier picker/diagnostic samples and
reports its own functional, timing, image-audit and remaining-failure evidence.
