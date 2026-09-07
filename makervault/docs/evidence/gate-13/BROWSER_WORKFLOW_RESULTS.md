# Gate 13C — current browser workflow checkpoint

**Status:** IN PROGRESS; not a complete matrix pass or request to close 13C.
Runs were captured 2026-09-07 UTC (2026-09-06 America/New_York).
Only verification tooling changed after the approved archive guard.

## Identity and method

Application source is clean `ddf8cf4b41cf261e6129fcdace0f789feb573cce`, schema 17.
Both images are the exact full-gate HTTPS lifecycle / subsequent audit images in
[archive verification](archive-guard-verification.json); their historical helper
label `development-gate13b` is not the evidence revision. No Gate 5 pin changed.

The browser runtime is immutable local image
`sha256:72b5b2b184b15e2cdf0135ca0108e1907a3fa2644e6f151fe9df06da18b97105`,
built from the pinned Playwright 1.62.1 Noble image plus NSS tools. Each workflow
used new disposable production-HTTPS services, private database/storage, generated
credentials/certificate and a read-only corpus. Browser memory is limited to 4 GiB
with 1 GiB shared memory and no CPU cap. Other host workloads were not stopped or
modified. These are local measurements, not a universal hardware performance claim.

The TLS probe requires HTTPS, an authenticated health contract and a secure browser
context; valid fixture trust must succeed while a mismatched hostname fails, in
both browser and Node. Trust is container-local. No ignored certificate errors,
host trust changes, weakened cookies, production credentials or real vault data.
Chromium reports 151.0.7922.34; WebKit reports 26.5. WebKit's Safari-like user agent
does **not** make this a native macOS Safari test. Firefox remains unqualified.

The [runner instructions](../../../benchmarks/browser-runtime/README.md) name the
current entry point. The older shell wrappers are not claimed as repaired HTTPS
production browser runners. Each run requires committed verification sources and
records harness revision separately from image/application revision.

## Observed results (initial runs)

| Workflow | Result | Evidence boundary |
| --- | --- | --- |
| Chromium organization | **FAIL**: first cards 1620.3 ms, required <1000 ms | All functional assertions completed; remaining interaction/API budgets passed |
| WebKit organization | Functional assertions PASS | First cards 2700.4 ms recorded; the existing harness does not enforce Chromium timing limits on WebKit; long tasks/heap unavailable, not zero |
| Firefox organization | NOT RUN past TLS preflight | `SSL_ERROR_UNKNOWN` on the valid fixture; no application or timing claim |
| Chromium previews | Functional probes and measured controls PASS | 20 files / 66,037,534 bytes; cold/warm settle without timeout; scope detailed below |
| Chromium mounted import | PASS, including source preservation | First scan imports two files/rejects one symlink; repeat skips two/rejects the symlink again |

Organization corpus is 600 Artifacts / 104 folders / depth three. Chromium API p95
is 26.23 ms first page, 17.93 ms exact search, 12.06 ms folder page and 13.54 ms
folder tree, each from 20 requests. Load more is 179.26 ms; exact search 95.52 ms;
folder search 73.76 ms; opening a folder 94.24 ms. There were no recorded interaction
long tasks. These results do not erase the first-card failure.

Both completed organization engines exercise selection/load more/filter reset,
mixed-success moves, tag preservation, selected ZIP download, supporting PDF
visibility and the prepared-printer summary with zero openable prepared-G-code
links. Current Trash checks cover panel/dialog cancellation preserving selection,
single and bulk move to Trash, restoration through the UI, and exact primary-byte
and original ID/folder/name preservation. Old permanent-delete assertions were
replaced with the accepted recoverable workflow, not removed without replacement.

Preview measurements: 16 cold original-file requests; 14 persisted thumbnails;
three skipped and three failed preview states in the deliberately mixed corpus.
Warm reload makes **zero original-file requests** and zero generated-thumbnail
uploads. Maximum observed concurrent original-file requests is one (not a direct
measurement of every worker's memory). Detail preview is ready in 359.29 ms with
one source request. LightBurn is ready with one cold source request, one generated
thumbnail upload and zero warm source requests. Long-task observation is available
in this Chromium run and records none in cold/warm/detail/LightBurn probes.

The renderer is software SwiftShader, not hardware-acceleration proof. Reported
browser `deviceMemory` is not the 4 GiB container limit; sampled JS heap is not total
browser/native/worker memory. One 401 console message and two GPU ReadPixels stall
warnings remain in the raw report; their presence is not silently suppressed or
treated as a demonstrated preview failure. No manual thumbnail uploads were used.

The mounted scan UI displays copy/index ownership and the rejected-symlink failure.
The runner checks that original source bytes, ignored text and symlink target are
unchanged after both scans. This copy-mode fixture does not newly qualify every
external provider or real mounted-library configuration.

## Attempts retained, not substituted

- An initial command used an unavailable browser-image identifier and failed
  inspection before creating a fixture/output directory. The local tag was then
  resolved to the actual immutable ID above; this was not an application test.
- [Attempt A](browser-attempt-a.json), harness `4fbdcdf`: Chromium completes its
  report but exits 1 for the first-card budget. [Full result](browser-organization-chromium.json).
- [Attempt B](browser-attempt-b.json), same harness: Firefox fails TLS preflight;
  [WebKit](browser-organization-webkit.json), [preview](browser-preview-chromium.json)
  and [mount](browser-mount-chromium.json) complete. Overall attempt remains failed.
  [Preview corpus](browser-preview-corpus.json) retains per-file identities.
- [Attempt C](browser-attempt-c.json), harness `7088162`: explicitly selecting the
  Firefox fixture policy still fails valid-host TLS. Playwright's
  [patched policy provider](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff)
  ignores default distribution policies, but selecting the alternate policy is
  **not a demonstrated complete fix**. It is a harness-only change, not a runtime
  or authentication change.
- [Attempt D](browser-attempt-d.json), harness `2ff886f`: diagnostic-only repeat,
  not a replacement for A/B. Firefox policy-page diagnostics also timed out, so
  no new trust conclusion is justified. Chromium passed TLS and reached single
  Trash/restore, then timed out locating `Select Workflow Bulk Success` after
  returning to the searched library. No final report was produced; startup phase
  measurements were not persisted before that later abort. This is an additional
  **open restore/search visibility or harness-synchronization issue**, not a pass
  or established app root cause. The earlier completed A/B runs are retained.

After D, diagnostics were corrected to preserve the original TLS exception even
if policy inspection fails, cap that inspection, and write startup timings before
later workflow checks. These logging-only changes receive focused harness/syntax
verification, not an invented successful matrix rerun. Final focused verification
passes 16 Python harness tests, 5 Node session-client tests, four script syntax
checks and the static release contract. Application images are unchanged from
the separately completed 351 API / 45 web full gate.

Private raw stdout/stderr/screenshots remain in the named `/tmp/makersvault-g13c-browser-0907*`
directories for local inspection; only generated fixture evidence is in scope.
[Raw artifact SHA-256 records](browser-raw-artifact-hashes.json) cover summaries,
reports, corpus, logs and screenshots from every A–D attempt.
No private key, cookie, live library or credential dump belongs in committed evidence.

## Next checkpoint

First cards currently measures navigation **plus automated form entry/sign-in**.
The measured failure alone cannot establish a model-rendering or API bottleneck.
Keep the existing <1000 ms assertion and profile the phases before proposing an
application change or asking the owner to decide a different benchmark contract.
Capture the restore/search visibility failure with request/state evidence before
deciding whether to repair a test race or application state handling.
Firefox fixture TLS must be corrected with positive and hostname-negative proof,
not bypassed. Any application/performance scope expansion needs a bounded proposal.

G13-04 residual-image review, physical passkeys, native Windows/macOS/mobile and
real local-app launch evidence, supported-platform decisions, release scope/revision
and matched bridge/distribution qualification remain open. Gate 12 remains explicitly
desktop-deferred; that does not automatically defer release blockers. All commits
stay local; no push, tag, publication, deployment, waiver or 13C acceptance.
