# MP-1b-9b-3 — Asynchronous local custom-folder consent

**2026-09-14 America/New_York.** Owner authorized this checkpoint with “proceed”.
Entry `cdf7defeb9962e70edf3fbbdf45dccb2835172c3`; implementation
`1399ba4e6ff26a6f8ddf3d2c64845babf1c7b9e1`.
**Local asynchronous session/HTTP integration verified; native qualification and
MP-1b-9b remain open. Production stays inactive.**

## Delivered boundary

- Initial explicit **Allow local reading and choose a folder** consent can bypass
  default hint lookup. Already-consented root selection also offers a custom dialog.
  GET, stale/invalid/wrong-stage actions and pre-cancelled requests cannot launch it.
  The local backend calls the existing bounded `presetui.PickFolder`; no new HTTP
  path, native argument, initial-directory field or external adapter registry.
- Acceptance starts one asynchronous session-owned operation and returns the page.
  The existing 90s picker budget is capped by the original session expiry, not the
  accepting request lifetime. A completed/disconnected request does not cancel an
  accepted dialog. HTTP handler/write deadlines remain 20s; metadata workers remain
  15s. No deadline enlargement, script, auto-polling or new status endpoint.
- Waiting pages provide an explicit same-path GET refresh, picker-only cancellation
  and whole-preview cancellation. Picker cancellation retains the busy slot until
  the callback returns; restart/new work cannot queue behind it. Owner shutdown,
  cancellation and expiry revoke authority; even a late successful result is ignored.
- A successful canonical local path stays in session memory and becomes one
  **unselected opaque-ID choice**. Its label does not disclose the selected path.
  A separate **Use this folder** confirmation starts account enumeration; explicit
  account/system selection still precedes discovery and exact metadata approval.
  Cancellation/failure restores prior unselected roots with fresh IDs, never a scan.
  New selections replace prior roots; restart discards the picked root.
- Empty/unsafe paths, timeout, cancellation and native failure produce fixed
  redacted warnings. Default/configured-root hint labels retain their older local
  path display behavior; the new picker result is not placed in HTML/form fields
  or normalized preview. A separately configured CustomRoot keeps its old semantics.

The [session contract](../../../slicer-bridge/internal/presetconsent/README.md)
details ownership, consent, privacy and cancellation semantics. The native picker
can itself browse/read provider state; “no presets read” does not mean no OS UI I/O.
Selection is not filesystem safety certification or authority to send anything to
a vault. Host teardown does not guarantee arbitrary callback return, immediate
memory erasure, parent-crash cleanup or native provider/service UI cleanup. Native
supervisor kill/reap ownership remains separate from the session's callback slot.

Production main/pairing/protocol dispatch, API/web/schema 17, Go dependencies,
existing file/hint/worker providers, native UI implementations and HTTP server
budgets are unchanged. No real profile, installed handler, device, dialog, package
installation, live vault, remote claim/import, slicing or printing was involved.

## Verification and retained counterevidence

| Capture | Exit / duration | Observed outcome |
|---|---|---|
| `go-preflight` | 0 / 33.640s | 206 units, race, formatting/vet, synthetic HTTP fixture build |
| `browser-preflight` | 1 / 10.673s | Existing global referrer-sample assertion failed before new picker scenarios |
| `browser-preflight2` | 0 / 37.885s | 25 navigation-bound regressions plus 30 asynchronous picker scenarios |
| `go-final` | incomplete | Compression runner exceeded its 120s limit; no closing result record |
| `go-final2` | 0 / 189.188s | 206 units, race/vet/format, 36 cross-builds, 13 short fuzz runs |
| `browser-final` | 0 / 38.533s | 55 actual-HTTP scenarios against the completed final-source fixture |

All six fresh directories use prefix `containment-mp1b9b3-` and suffix `-20260914`
under the private verification root. **One failed and one incomplete capture are
retained, not converted to passes.** No runtime/check-driver edits during captures.
The successful final captures have identical start/end implementation revisions
and clean runtime status. Browser execution began after the final Go command and
fixture build completed. Preflight was dirty source at entry; final warning wording
clarifies that preset reads, not OS dialog filesystem activity, are withheld.

The first browser failure came from the older harness's shared “last request”
referrer sample. It did not record the offending request identity or browser, so
its exact trigger cannot be established retrospectively. A later same-origin
request, such as a favicon, could overwrite that sample. A **new derived harness**
binds observation to a dedicated cross-origin navigation and records redacted
request classifications, still refusing any different-origin referrer. All six
engine/viewport navigation checks pass without changing application privacy headers.
The historical harness/results remain untouched; the failed run is not dismissed
as a proven favicon event or counted as an application privacy pass.

The incomplete Go log contains test/build/fuzz completion output, but the outer
compression runner ended before writing `result.json`. Its missing completion and
end-source record prevent qualification. The fresh `go-final2` rerun used the durable
capture script directly, with bounded tool polling, and completed normally. The
final browser fixture is joined to that completed capture, never the incomplete one.

**206 unit tests with race detection**, 13 seeded fuzz targets, **219 top-level /
462 inclusive passes**, zero failure/skip in completed Go captures. New tests cover
initial/root-stage consent, no hint/worker reads before confirmation, request
disconnect independence, revision replay, busy/cancel slot retention, late success,
session/owner shutdown and expiry, invalid paths/actions, diagnostic redaction,
unchanged HTTP field/origin/CSRF checks and read-only refresh. Non-cooperative test
callbacks demonstrate revocation without falsely claiming native cleanup.

Formatting and vet pass. Linux/Windows/macOS × amd64/arm64 compile the bridge and
five internal package-test binaries: **36 builds**, not native OS execution.
Thirteen mutation fuzz targets request 5s each with two workers; exact reported
execution/elapsed counts are retained in the index. No failed fuzz corpus; short
fuzzing is not exhaustive. Native Windows, macOS and Linux desktop UI counts are zero.

Browser verification uses Chromium, Firefox and WebKit at 1024px and 390px:
**25 existing regression cases** plus **30 synthetic asynchronous picker cases /
156 stage checks**. Six custom-picker approval flows require folder/account/preset
selection and exact digest approval, with three worker calls and no hint lookup.
Picker-only cancellation, simulated native cancel/unavailable and owner close each
leave zero metadata calls. Waiting HTTP responses are under the test's 3s ceiling;
this is isolated fixture responsiveness, not a production latency benchmark. Narrow
waiting/selected screenshots were visually inspected; no physical tablet or screen
reader was tested. Test-only stdin signals complete dialogs; no native UI dispatch.

[Go driver](make-plate-async-picker-check.sh), [browser driver](make-plate-async-picker-browser.cjs),
[derived regressions](make-plate-async-picker-regression.cjs),
[index](make-plate-async-picker-verification.json) and
[read-only checker](make-plate-async-picker-verify.cjs) bind source, commands/mounts,
counts, executable joins, retained failures and **62 artifact hashes**. Pinned Go
1.26.6 / Playwright 1.62.1 noble images and rehashed locked browser dependencies are
unchanged. Test containers are offline, UID/GID 1000, with read-only source/fixtures
and no published ports. Release contract passes for v5.1.0. A draft checker regex
escaping error was corrected before evidence acceptance; runtime captures were not rerun or altered for it.

## Re-cock — MP-1b-9b-4

Next is a **matched native Windows/Linux qualification package and scoped execution**,
not production activation. Establish explicit device permission and observed OS/CPU,
browser, installed slicer build and preset-bundle identity before claiming support.
The package must cover:

1. A test-only owner/helper dispatch path matched to the reviewed source, with
   private evidence and no production handler registration or automatic vault import.
2. Native browser/dialog foreground, keyboard/accessibility, Unicode, cancellation,
   timeout/revoke, provider side effects and unsafe/missing/nonstandard prerequisites.
   OS acceptance is not browser readiness; cancellation is not proof of provider cleanup.
3. Matched hint/reader/root boundaries and explicitly permitted real-profile review,
   including independently observed installed-app/bundle versions. Synthetic fixtures
   and cross-compilation cannot substitute for these observations.

The Dell tablet's Bambu `v2.8.0.6` remains owner-reported, not independently qualified;
physical Windows/YubiKey checks remain open. No Mac connection or device changes.
Mac-local preset import, CNC/CAM, Gate 12 desktop and extra performance tuning remain
deferred; existing Mac file-open/browser scope is unchanged.

MP-1c still couples authenticated claim/review/commit, immutable storage, additive
migration and portable/raw recovery. MP-1d retains independent Bambu/Orca/Prusa
conformance; MP-2–4 remain unstarted. No gate closeout, full security scan, waiver
transfer, push or publication. E4/R57/F26/H0 remains historical exact-image evidence.
Owner ROADMAP and desktop architecture notes are untouched.
