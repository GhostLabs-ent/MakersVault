# Gate 13C — on-demand sidebar folder menus

**Date:** 2026-09-10. **Status:** approved application slice implemented and verified
with explicit limits. Baseline startup and stress API failures remain; Gate 13C is OPEN.

## Change and boundaries

The owner approved the bounded next step in the
[residual diagnosis](RESIDUAL_DIAGNOSIS.md). Application `82cb2cc` introduces
[FolderActionMenu](../../../web/src/ui/FolderActionMenu.tsx): a native disclosure
whose action contents are constructed only while open. Local open state avoids
rerendering the full sidebar on each menu toggle. Closing removes the contents;
Escape and action activation return focus to the trigger before the next action.
Native Enter/Space and normal tab order remain available.

The sidebar still expands roots by default and shows the same paths, folder actions,
permissions and upload/drop targets. Menus are keyed by their owning folder and use
current folder/capability/busy props. Subfolder, rename/edit, ZIP download and
confirmed deletion are unchanged workflows. No initial-expansion change, tree
virtualization, folder/upload quota, parser/viewer rewrite, schema, API, dependency,
authentication, Compose or release-pin change is included.

The measured folder-search input now uses the sidebar-scoped textbox role with
exact accessible name. The timer still starts before the real fill/actionability
work and ends after the expected result is visible. No selector prewarming, forced
click, historical-metric subtraction or timing-budget relaxation is used.
Organization schema 5 retains conservative start-time/legacy/overlap long-task
attribution and adds sidebar counts and a zero-closed-menu-content assertion.
Application DOM savings and this measurement correction are separate changes;
elapsed before/after results do not isolate either one's contribution.

## Exact source and image identities

- Application/full verification: `82cb2cc873fb5c9a1b5ed58c1f14ca36495869a0`.
- Final API: `sha256:a099ec86206c9e9204267e63ed4953f86f6ecb217077994f6488a536500ba27b`.
- Final web: `sha256:a833cb7fc959b27979c9d7e89fe02680913b61375d158aeebd43129d4fcc0352`.
- Browser: `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`,
  local `makersvault-gate13-browser-fixed`, Playwright 1.62.1 / Chromium 151.0.7922.34.
- Historical helper version label: `development-gate13b`; schema remains 17.

Harness-only follow-ups retain the application unchanged: `a3e3504` corrects the
new functional-test dropdown lookup, `74232d6` records precise failure stages,
`e841b79` preflights synthetic entries and records the WebKit FileList boundary,
`7551745` tries a native-branded FileList fixture, and `7b0bb6e` uses an explicit
FileList-only DOM event with a completion-aware highlight assertion. These are
not additional application fixes or changes to organization timing.

## Functional verification and retained development failures

The old `76b526d` control fails the new closed-menu assertion at nine menus instead
of zero, before any new scenario can pass. The first new-image attempt A passed
keyboard/lazy-mount and exact duplicate-leaf rename tests in each engine, then failed
the new test's exact-label lookup for the location dropdown. A scoped combobox
lookup resolves that test issue. A's ordering case never starts: concurrent full
verification rebuilt the same local image tags and the earlier API image reference
became unavailable. A is not final-image qualification. The same rebuild interrupted
the initial advisory audit after its development API scan; its web image was unavailable.

B passes all 17 scenarios in Chromium/Firefox and all seven ordering cases, but
WebKit times out in a combined drop/download scenario. The dedicated debug run
narrows this to synthetic upload, before download. A standalone about:blank probe
on the pinned Playwright base records: Chromium has no filesystem entry and reads
its item file; Firefox's synthetic entry reads its file; WebKit's entry reports
`NotFoundError` for that in-memory file, without MakersVault loaded.

H records that preflight explicitly. Chromium/Firefox and ordering pass again;
WebKit's separate plain-object FileList fixture fails the native DragEvent type
check. I keeps a native DataTransfer but fails the immediate drop-highlight assertion.
J uses an explicit FileList-only DOM event and waits for the highlight before drop.
The original WebKit failures remain failures. This explicitly tests a FileList-only
event input, not WebKit synthetic filesystem-entry success or native
OS drag support. Unexpected preflight failures still fail, not silently skip.
No application's file traversal, browser trust or certificate policy is bypassed.

The menu scenarios cover initial closed DOM, open/close/reopen and coalesced native
toggle events; Enter/Space/Tab/Escape/focus; action ordering; duplicate-name ownership;
subfolder creation; current folder data while another menu triggers refresh;
drop-target/byte preservation and ZIP download; cancelled/confirmed deletion;
collapse/filter cleanup; and a real Viewer account with independent API refusal.
The existing ten picker and seven request-order regressions remain enforced.
H passes all 17 picker/sidebar checks in Chromium and Firefox and all seven
Chromium ordering cases. J passes all 17 in WebKit with the explicit FileList-only
event boundary above. These are the same final application images, with the named
functional-harness revisions recorded separately; no failed attempt is replaced.

## Verification and reproducibility

### DOM and performance observations

The post-action snapshots confirm the approved DOM reduction without changing the
initial expansion policy or the number of visible rows:

| Fixture, 40 cards loaded | Previous whole-page elements | Current elements | Closed menu descendants before → after | Visible folder rows |
| --- | --- | --- | --- | --- |
| 600 Artifacts / 104 folders | 3,659 | 2,779 | 880 → 0 | 40, unchanged |
| 600 Artifacts / 1,040 folders | 17,411 | 8,611 | 8,800 → 0 | 400, unchanged |

Historical comparisons are the [picker](FOLDER_PICKER_RESULTS.md) and
[residual diagnosis](RESIDUAL_DIAGNOSIS.md) fixtures. The 1,040-folder initial
20-card page also falls from 16,399 to 7,599 elements; filtered one-card DOM falls
from 291 to 225. Per-card folder destination options remain zero. Current sidebar
element counts exclude `<aside>` itself; the older diagnostic sidebar count included
it, so those two sidebar fields differ in counting convention by one element.

All current timed runs use final `82cb2cc` images / harness `7b0bb6e`, without profiling.

| Chromium run | Folders | First cards (ms) | Folder search (ms) | Max interaction task (ms) | Folders API p95 (ms) | Result |
| --- | --- | --- | --- | --- | --- | --- |
| C | 104 | 511.3 | 16.4 | 0 | 17.2 | PASS enforced budgets |
| D | 1,040 | 532.4 | 74.8 | 0 | 113.3 | FAIL folders API |
| E | 104 | 1,368.5 | 18.1 | 0 | 20.6 | FAIL first cards |
| F | 104 | 589.6 | 16.4 | 0 | 12.9 | PASS enforced budgets |
| G | 1,040 | 534.0 | 72.7 | 0 | 108.3 | FAIL folders API |

C completes all three organization engines and the preview/mounted-import probes.
Its Chromium baseline passes unchanged enforced budgets at 511.3 ms first cards,
16.4 ms folder search, zero observed interaction tasks and folders API p95 17.2 ms.
Firefox/WebKit organization functional checks pass, but their first-card observations
are 1,219 / 2,987 ms. Their browser performance guard is explicitly unavailable/not
enforced, not a cross-engine performance pass or an invented zero.

D's first large-folder stress run passes the browser timing guards at 532.4 ms
first cards, 74.8 ms folder search and zero observed interaction tasks. **D still
fails overall:** folders API p95 is 113.3 ms against the unchanged <100 ms target.
All exact-ID mixed-move, original-byte, supporting/prepared and Trash checks pass.
The API failure is not removed or attributed to the eliminated DOM.
G repeats the result: browser timing passes at 534.0 ms first cards / 72.7 ms
search / zero observed interaction tasks, but folders API p95 is 108.3 ms and the
overall run fails. All five Chromium organization runs match the post-change DOM
counts for their respective fixtures and retain selection/byte/Trash checks and
unchanged thresholds. Navigation tasks of 52 ms (C),
55 ms (D), 652 ms (E), and 53/84 ms (G) remain recorded; zero interaction tasks is
not a claim that no navigation tasks occurred.

The baseline repeats are mixed, not uniformly passing: E fails first cards at
1,368.5 ms with a 652 ms navigation long task, despite 18.1 ms folder search and
zero observed interaction tasks. F passes at 589.6 ms first cards and 16.4 ms search,
with no recorded long tasks. The unprofiled E record identifies the phase, not a
responsible application function or native wait. Keep startup as an unresolved
track alongside historical detail waits and the separate folders API failure.

C's mixed preview probe records 340.1 ms detail readiness with one original-file
request and zero observed cold/warm/detail/LightBurn long tasks. Warm original-file
requests and generated-thumbnail uploads are both zero. That single good sample
does not resolve the historical intermittent viewer pause or qualify arbitrary
large/prepared 3MF files. Its corpus remains 20 files / 66,037,534 bytes and the
detail target is the same four-triangle STL. Mounted-import source preservation passes.

### Repository checks

[Full repository verification](sidebar-menu-verification.json) passes on committed
`82cb2cc` throughout: **351 API / 58 web tests**, typecheck/build, bridge tests/build,
Compose/security checks, cookie/CSRF/non-root smoke, virtual Chromium passkeys,
19 Python / 28 Node harness tests, seven browser syntax checks and static release
contract. Joined production-HTTPS upgrade, raw restore, portable startup and exact
stopped rollback pass on the final images above. A separate direct invocation
confirms all 58 web tests. The two new server-render tests prove that closed action
factories are not evaluated, including a 400-row fixture.

Use the [browser runtime instructions](../../../benchmarks/browser-runtime/README.md)
with those exact image/revision/version values and a fresh private output directory.
`--workflows folder-picker --browsers chromium firefox webkit` runs the functional
matrix; `ordering` runs Chromium. `organization` defaults to 600 Artifacts / 104
folders; `--folder-stress --workflows organization --browsers chromium` is the
separate 600 / 1,040 case. Preview runner exit zero is functional collection, never
automatic performance acceptance. No profiling is used in these performance runs.

All fixtures are disposable, production-HTTPS and isolated from the real vault.
Valid-host trust and wrong-host rejection are enforced in each case. Browser limits
remain 4 GiB memory / 1 GiB shared memory without an explicit CPU cap. Timed runs
are sequential, after other owned build/audit/functional jobs finish. The unrelated
host workload remains untouched; this is not a controlled idle workstation or
native Windows/macOS/Safari/physical-passkey qualification. Raw keys and credentials
are excluded from committed evidence. The unrelated desktop draft is untouched.

The [browser evidence](sidebar-menu-browser-runs.json) contains **all twelve** named
attempts, including the old-image control, failed development cases, dedicated WebKit
debug attempts, final functional coverage and all five timed organization runs.
The [read-only reducer](sidebar-menu-analysis.cjs) refuses unknown run IDs,
in-progress summaries, symlinks/unexpected artifacts and files over 128 MiB. It
hashes private log/screenshot files without publishing their bodies. From repo root:

```sh
node makervault/docs/evidence/gate-13/sidebar-menu-analysis.cjs browser control a b debug h i j c d e f g
node makervault/docs/evidence/gate-13/sidebar-menu-analysis.cjs audit initial
node makervault/docs/evidence/gate-13/sidebar-menu-analysis.cjs audit final
```

The [initial audit](sidebar-menu-initial-audit.json) is explicitly incomplete, not
silently replaced. One-off about:blank probe setup also encountered a read-only
nested-mount refusal and the fixture image's required-CA precondition before running
successfully on the same pinned Playwright base. It never contacted the vault or
qualified HTTPS; all actual application runs retain the full trusted fixture entrypoint.

### Final exact-image advisory check

The [completed final-image scan](sidebar-menu-audit.json), Grype 0.118.0 with its
valid database built September 10 at 06:30:24 UTC, reports **181 API / 3 web matches**.
Web reduced records exactly match the historical inventory. API match identities,
packages, installed versions and severities are unchanged, but full-record equality
is **false**: the newer database changes `fix_state` from empty to `fixed` and adds
`3.15.0rc2` for CVE-2026-17084, CVE-2026-15806 and CVE-2026-15310. All three still
match installed Python 3.11.16. This is scanner fix metadata, not an installed patch,
new mitigation, risk waiver or Python migration recommendation. Exact changed fields
and the complete current API records are retained. No new language-lock scan is claimed.

Final evidence verification regenerates all twelve browser records and both audit
records field-for-field, including 104 browser artifact hashes. Six invalid reducer
invocations are refused; application/bridge/Compose/lock sources match the full-gate
inputs. All owned fixture/audit containers are gone; no unrelated workload was stopped.
All 204 local links checked across the governing/current evidence documents resolve;
reducer syntax and `git diff --check` pass. Frozen release pins remain unchanged.

## Remaining checkpoint

**Follow-up:** the owner authorized one bounded pass and then a stop to further
performance tuning. [Results and disposition](BOUNDED_PERFORMANCE_RESULTS.md)
record `c42614e`, the remaining failures and that decision. The proposal below is
historical; it is not authorization for another open-ended investigation.

Next proposed bounded work: profile the repeatable folder-list API miss separately
(authentication, SQL, conversion/serialization, proxy and host elapsed time), and
capture the intermittent startup/detail wait without treating it as DOM-bound by
default. Propose application changes only after attribution and owner approval.
This slice does not fix those waits or partition folder-API latency. Preserve every
old and new failed sample and the separate security/platform/
release obligations. Gate 13C is not accepted; Gate 12 remains desktop-deferred.
Nothing is pushed, published, tagged as a release or deployed.
