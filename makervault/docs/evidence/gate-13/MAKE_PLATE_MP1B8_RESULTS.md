# MP-1b-8 — Inactive local consent and bounded native hints

**2026-09-14 America/New_York.** Owner directed continuation after MP-1b-7.
Entry `d0dc059bf4afbb7862bbc76184b19dddbcce9929`; implementation
`dafb3fb70f67ff962a857c936dc2f2087f6deee1`.
**Local selection/consent foundation verified. MP-1b/MP-1 remain open and inactive.**

## Delivered and not implied

- A new internal local session requires separate approval before any hint/file
  access, then explicit root, account-or-system-only and preset choices. Nothing
  is preselected. Opaque random choice IDs cannot supply HTTP filesystem paths,
  account names, executable choices or arbitrary settings.
- Selecting presets performs a fresh worker projection. The page displays the
  exact normalized JSON bytes and SHA-256 digest; approval must match the current
  revision and digest. A local caller may consume a copy once, without root/account
  fields. This does not rescan, transmit, stage or save anything.
- Expiry (at most five minutes), stale/concurrent forms, duplicate/oversized choices,
  restart, request cancellation and revocation have explicit controls. Cancelling
  during worker I/O discards late results; approved-but-unconsumed data can still
  expire or be revoked. State checks are not a secure-memory-erasure guarantee.
- An unmounted HTTP handler has a random nonce path, independent CSRF token,
  exact numeric-loopback Host/path checks, Origin/fetch-site controls, read-only
  GET, strict bounded POST fields/body and privacy headers. Contextual template
  escaping and a buffered display ceiling prevent raw HTML/partial oversized pages.
  The displayed vault origin is explicitly **not authenticated** by this package.
- Windows native hints now use a no-input private worker operation with the existing
  deadline/kill/reap slot. The parent validates an exact known-root plan; paths stay
  private and cannot cross into public candidate JSON or other worker operations.
  The Windows provider and supervisor are unchanged; no HOME/XDG/credential
  environment inheritance was added. Linux copies only environment strings into
  the pure planner, with no filesystem/NSS probing.
- The new page provides labelled native controls, visible focus, 44px-minimum
  buttons and a narrow layout. Its technical JSON preview is a foundation, not the
  finished remote-import editor or a geometry-complete/print-ready assertion.

The [source contract](../../../slicer-bridge/internal/presetconsent/README.md)
defines exact boundaries, budgets and future host obligations. There is **no listener,
native browser launcher, production caller, new protocol action, remote authorization,
persistent preset or real workstation scan** in this slice. Existing production
main has no worker dispatch. Browser/server input cannot construct a custom root;
a bounded native selection source is still required before activation.

## Verification and retained attempts

All Go counts below are top-level `Test*` cases under race detection, plus separately
counted seeded fuzz targets; inclusive pass events also count subtests.

| Capture suffix, under `containment-mp1b8-` | Exit / duration | Observed outcome |
|---|---|---|
| `consent-preflight-20260914` | 0 / 28.839 s | 170 unit + 10 seed targets; 180 top-level / 368 inclusive passes, no fail/skip; formatting/vet pass |
| `browser-deps-20260914` | 0 / 4.113 s | Private locked Playwright dependency install only; network enabled for this preparation |
| `browser-preflight-20260914` | **1** / 2.015 s | Initial horizontal-overflow assertion failure retained |
| `browser-diagnostic-20260914` | **1** / 1.825 s | Reproduced Chromium narrow review: viewport 390 px, scroll width 596 px; screenshot/log retained |
| `consent-preflight-b-20260914` | 0 / 28.770 s | CSS correction and additional consent regressions; 172 unit + 10 seed targets, 182 top-level / 370 inclusive passes; no fail/skip |
| `browser-preflight-b-20260914` | 0 / 7.117 s | All 36 rendering/control checks pass against corrected dirty-source HTML |
| `consent-final-20260914` | 0 / 167.799 s | Clean implementation: same 172/182/370 counts, formatting/vet, 30 cross-builds and ten mutation fuzz smokes pass |
| `browser-final-20260914` | 0 / 6.692 s | Clean matching implementation: all 36 rendering/control checks pass against final Go-generated HTML |

The first browser failure did not identify its stage in the log; the diagnostic
rerun localized it to the review digest. Adding `overflow-wrap:anywhere` to the
muted review text fixed the narrow overflow; no assertion was removed or relaxed.
Both failed captures remain failures. A corrected narrow account screenshot was
visually inspected; its selected radio/focus came from the deliberate keyboard test,
not a default selection.

The final Go capture uses Go **1.26.6**, Linux/amd64, UID/GID 1000, network disabled
and read-only source/fixture mounts. Bridge plus four package-test binaries compile
for Linux/Windows/macOS × amd64/arm64: **six targets / 30 builds**. Cross-compilation
is not native execution. Ten fuzz targets each request five seconds with two
workers; actual progress reports are 5–6 seconds, with exact executions retained in
the [verification index](make-plate-consent-verification.json). No failing corpus
was produced. Short fuzz smokes are not exhaustive proof.

New tests cover explicit no-read-before-consent behavior, opaque/stale choices,
account-list failure without an automatic fallback scan, exact one-use review,
revocation after approval, cancellation during I/O, expiry/restart, selection limits,
fresh-selection failures, and a real Linux worker using an authored temporary
layout. HTTP guard/escaping/display-budget tests use `httptest` recorders, not an
active server. Hint tests cover strict Windows plan/framing/public-JSON boundaries
and a deliberately hung generic worker with the native-hint request; they do
**not** execute or reproduce a Windows Shell hang.

The browser matrix is six generated synthetic stages × two viewports
(1024×768 and 390×844) × Chromium **151.0.7922.34**, Firefox **153.0** and WebKit
**26.5**, all running headlessly on Linux. Checks include no initial selection,
keyboard radio operation and checkbox selection, review text/digest agreement,
button size, no horizontal page overflow, no external requests and no page errors. Each final HTML
hash joins the Go capture to the browser report. These are offline `setContent`
checks: **no live form submission, HTTP security-header enforcement, DNS-rebinding
containment, native protocol/browser launch, physical tablet or screen-reader
qualification** is asserted.

## Reproduction and evidence boundaries

The [Go driver](make-plate-consent-check.sh),
[browser driver](make-plate-consent-browser.cjs) and
[read-only checker](make-plate-consent-verify.cjs) join exact source states, command
arguments, mounts, counts, failures and **47 artifact hashes** across all eight
private captures under `/home/vinnyc/.local/state/makersvault/verification/`.
The index additionally binds the installed Playwright tree; repository package/
lock files are unchanged. Browser dependencies use `npm ci --ignore-scripts` in a
private directory from the existing lock; stderr contains only an npm update notice.
No npm upgrade or source dependency change was performed.

Pinned images:

- Go: `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
- Playwright 1.62.1 noble: `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`.

Only dependency preparation has network access. Test containers use read-only
source/dependency/fixture mounts and private writable evidence; formatting alone
used a writable source mount. The durable wrapper avoids the known 120-second
compression-wrapper ceiling and retains heavy logs privately. Earlier dirty-source
runs are not represented as clean final runs. Historical checkers/pass records
remain unchanged.

The release-contract check passes for v5.1.0. API/web/schema 17, production main/
file-open protocols, dependency declarations, the projection package, supervisor
and OS hint providers remain unchanged. No fresh full-app suite, image/advisory
scan, waiver transfer, complete gate or native-device qualification is claimed.

## Re-cock

Next **MP-1b-9: isolated local-server/browser-launch lifecycle harness**. Bind only
numeric loopback; bound connections and read/write/header/idle time; prove actual
HTTP form/Origin behavior and cancellation/expiry/revoke/launch-failure/shutdown
cleanup. Qualify a bounded native folder-picker/custom-root source without accepting
HTTP paths. Keep main/protocols inactive until matched early worker dispatch,
native Windows/hint/reader/lifecycle, independent installed-version observations
and real profiles are reviewed together. The owner's reported Windows Bambu Studio
v2.8.0.6 is not yet a qualified installed-build/profile fixture.

MP-1c still couples scoped claim/review/commit authority, immutable snapshot storage,
additive migration and portable/raw recovery. Bambu/Orca/Prusa runtime conformance
remains independent; MP-2–4 are not started. Mac-local import, CNC/CAM, Gate 12 desktop
and further performance tuning remain deferred; existing Mac file-open/browser
scope stays unchanged. Windows/YubiKey tests remain unrun.

No Mac connection, live-vault/installed-handler change, gate closeout, push or
publication. The owner's separate roadmap/desktop notes are untouched.
