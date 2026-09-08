# Gate 13C — approved browser corrections

**Status:** approved corrections verified; performance qualification still OPEN.
Captured 2026-09-08 UTC / America/New_York. This is not Gate 13C acceptance.
Owner authorized the diagnosed corrections with “Okay please go ahead.” All work
remains local. Frozen Gate 5 release pins and the deferred Gate 12 scope are unchanged.

## Bounded changes

- Grid requests now belong to a specific active view and applied query. A newer
  refresh invalidates older asset/tag and pagination results, errors and loading
  updates. View cleanup invalidates departed requests. Pagination uses the applied
  filter, not unsubmitted search text; current authorization failures still work.
- Disposable HTTPS uses a unique CA plus a separate server-authentication leaf.
  Firefox installs the public CA through its startup environment policy. Browser
  and Node preflight require valid-host success and wrong-host certificate failure;
  no certificate bypass, host trust change or production-authentication change.
- First-card timing records browser-side visible layout at an animation frame,
  retaining the old locator-wait duration separately. Navigation and automated
  login are still included and the Chromium <1000 ms budget is unchanged. This is
  not a claim about physical screen presentation or hardware acceleration.

The prior diagnosis reproduced the stale grid with a delayed asset response and,
independently, with only delayed tags. The restored record remained present in
the API. Firefox required **both** a valid leaf and policy selection before startup.
Locator retry time inflated the first-card measurement in controlled samples;
that does not explain every earlier millisecond or erase historical failures.

Historical [attempts A–D](BROWSER_WORKFLOW_RESULTS.md) remain intact. Private local
diagnostics are at `/tmp/makersvault-browser-diagnosis-20260907-a/DIAGNOSIS.md`;
the surrounding private fixture directory is not a publishable evidence bundle.

## Source identity and complete gate

Implementation and harness are committed locally at clean
`12559336e6dfdc99b1761b2a62d80616d957020c`. Schema 17, API behavior, runtime bases,
dependency locks and frozen release pins are unchanged. The full `make verify`
exits 0: **351 API / 51 web tests**, web type/build, Go tests/build, Compose/security,
container smoke, Chromium virtual-passkey ceremonies, **19 Python harness / 10
Node tests**, five browser-script syntax checks and static release contract.
The web test build reused its successful cache; an additional direct invocation
executed all 51 web tests. No incomplete/truncated command is counted as a pass.

The joined HTTPS lifecycle passes schema 4→17 upgrade, contract-6 raw restore,
pre-start credential/session/challenge handling, exact stopped rollback, portable
17→12→17 startup with a fresh identity, all 18 portable members, refusal/no-mutation
checks and fresh-install security/persistence. [Verification and exact image IDs](browser-fix-verification.json)
bind the browser and subsequent image-audit evidence to those same lifecycle images.
The helper label `development-gate13b` is historical, not the evidence revision.

Browser runtime is pinned local image
`sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`.
Fresh per-case HTTPS/database/storage fixtures retain 4 GiB browser memory, 1 GiB
shared memory and no CPU cap. Other host workloads were not stopped or modified.
Browser versions are Chromium 151.0.7922.34, Firefox 153.0 and WebKit 26.5, all Linux
headless. These are local observations, not universal performance guarantees.

## Regression and trust proof

[Seven request-order checks pass](browser-fix-ordering-chromium.json): late assets,
late tags, stale 401 after restore/search, superseded pagination, unsubmitted query
text, departed-view 401, and current 401 still requiring sign-in. Unit coverage
adds six request-ownership, five visibility-probe and three certificate tests.

The same new regression on the old `ddf8cf4` images fails exactly at **20 cards
instead of two** after releasing the held unfiltered response. Preserve this
[negative-control identity](browser-fix-negative-summary.json) and
[failure](browser-fix-negative-ordering.json); it is expected evidence, not a new
failure of the fixed build. No later test assertion was claimed as reached there.

All three engines pass valid fixture HTTPS, secure-context and wrong-host rejection;
Node also requires the specific hostname-validation error. Firefox then completes
the full organization workflow. Neither a CA-as-leaf certificate nor late
`firefoxUserPrefs` policy selection remains in the active fixture.

## Browser attempts — failures retained

[Attempt A](browser-fix-attempt-a.json) completes all six cases. Five pass; Chromium
organization completes every functional assertion but fails its interaction budget.
[Attempt B](browser-fix-attempt-b.json) is a fresh Chromium-only repeat on identical
images/harness and also fails. It is not substituted for A.

| Organization run | First visible frame / old wait return | Interaction long task | Disposition |
| --- | --- | --- | --- |
| [Chromium A](browser-fix-organization-chromium.json) | 584.4 / 1042.0 ms | 56 ms during load-more | FAIL: >50 ms interaction limit |
| [Chromium B](browser-fix-repeat-chromium.json) | 1433.2 / 1445.7 ms | 55 ms during folder navigation | FAIL: first cards ≥1000 ms and interaction >50 ms |
| [Firefox](browser-fix-organization-firefox.json) | 1335.0 / 1792.2 ms | unavailable, not zero | Functional PASS; existing harness does not enforce Chromium budgets |
| [WebKit](browser-fix-organization-webkit.json) | 2931.0 / 2687.3 ms | unavailable, not zero | Functional PASS, not native Safari qualification |

Both Chromium reports also record navigation long tasks: **81 ms in A and 713 ms
in B**. Thus locator timing inflation is real, but **not the complete performance
explanation**. New schema-3 browser-frame timing exposes a genuine remaining budget
miss; it does not justify a claimed speedup over schema-2 historical measurements.
Browser-frame and driver-wait clocks are separate observations; the frame probe may
also report later than locator detection. Neither measures physical display output.

Both Chromium runs retain all selection, pagination, tag preservation, mixed move,
selected ZIP, supporting-document, prepared-summary and current Trash/cancel/restore
assertions. Firefox/WebKit do too. Prepared payload links remain zero; restored
IDs, folder/name and primary bytes are checked. API/other elapsed interaction
budgets pass; the recorded long tasks cannot be dismissed on that basis.

## Preview and mounted-import observations

[Preview corpus](browser-fix-preview-corpus.json): 20 files / 66,037,534 bytes.
[Fresh preview report](browser-fix-preview-chromium.json): cold/warm settle without
timeout; 16 cold original requests, 14 persisted thumbnails, three skipped and
three failed states from the deliberately mixed corpus. Warm original requests
and generated-thumbnail uploads are **zero**. Maximum observed original-request
concurrency is one. Detail is ready in 391.2 ms with one request; LightBurn uses one
cold request/upload and zero warm originals. All four probes record zero long tasks.
These observations meet the measured preview long-task/cache controls; exit 0
alone is not a blanket budget pass. Cold cards' legacy driver metric is 1050.9 ms
(warm 210.1 ms), not the corrected organization frame metric and not a new startup
qualification. Preview timings and policy were not modified in this slice.

SwiftShader is software rendering, not hardware acceleration. Sampled JS heap and
reported device memory are not total browser/native/worker memory. One 401 console
message and two GPU ReadPixels stall warnings remain visible in the report.
No manual thumbnail uploads were introduced.

[Mounted-import repeat](browser-fix-mount-chromium.json) imports two files, then
skips both; each scan rejects the fixture symlink. UI copy/index ownership and
failure details pass. The runner verifies every source byte and symlink target
remain unchanged. This is copy-mode fixture proof, not every real NAS/provider.

All public generated reports, startup measurements and
[raw artifact hashes](browser-fix-raw-artifact-hashes.json) are retained, including
failed runs. Private fixture keys/credentials are excluded. Disposable stacks are
cleaned; no user library, host trust store or unrelated desktop draft was changed.

## Next owner checkpoint

The [fresh images-only advisory scan](browser-fix-audit.json) completes on the
exact lifecycle/browser images using Grype 0.118.0 and its validated database built
2026-09-08 06:30:10 UTC. It retains **181 API / 3 web package matches**. All reduced
advisory/package/version/severity/source/namespace/location/match/fix records equal
the retained remediation inventory; this is checked, not inferred from totals.
Raw report hashes and unchanged language-lock hashes are recorded. Language scans
were not rerun in this invocation. No finding was suppressed, patched away by the
browser changes, or accepted as a release risk.

The three approved corrections are implemented and verified, but **13C stays open**.
Proposed next bounded slice: capture Chromium startup/load-more/folder-navigation
performance traces on the same 600-Artifact/104-folder fixture, separate script,
layout/render, GC and scheduling costs, and propose the smallest evidence-backed
optimization. The 713 ms observation is not yet a function-level root cause.
Do not raise budgets, discard failed samples or presume GPU/API/host blame.

**Subsequent owner-authorized follow-up:** [profiling results and proposal](CHROMIUM_PROFILE_RESULTS.md)
complete that diagnostic slice on these same images. Repeated folder controls and
driver queries are concrete targets; two unprofiled controls pass without erasing
the failures above. Application optimization now awaits owner review of the bounded
proposal; the original 713 ms observation is not assigned a speculative root cause.

G13-04 image residuals, physical passkeys/native Windows/macOS/mobile/local-app
evidence, supported-platform decisions, release scope/revision and matched
bridge/distribution qualification remain explicit checkpoints. No residual-risk
waiver, 13C acceptance, push, tag, publication or deployment is implied.
