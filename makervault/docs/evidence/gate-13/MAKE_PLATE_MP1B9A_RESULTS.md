# MP-1b-9a — Bounded local HTTP host and actual browser forms

**2026-09-14 America/New_York.** Owner directed continuation from MP-1b-8.
Entry `83a1aa09c6207668e88fe3747f4e76a31eff243e`; implementation
`c7099ad65208bf782308ad8fbd80c788715c8a1f`.
**Local HTTP checkpoint verified; MP-1b-9/MP-1b/MP-1 remain open and inactive in production.**

MP-1b-9 is split into two evidence checkpoints. This slice implements the local host
and exercises browser forms/teardown. **MP-1b-9b remains required** for bounded native
browser/folder-picker helpers and their owner lifecycle; it has not been silently
dropped or qualified by a synthetic launcher. Existing production main/pairing and
all native file/hint/worker providers are unchanged.

## Delivered boundary

- `StartLocal` attaches a session once and binds only `tcp4` at `127.0.0.1:0`.
  Startup performs no hint/profile/browser lookup. It exposes one ephemeral private
  URL to the local caller, not the vault or logs. No production main caller exists.
- Eight admitted connections and a separate eight-handler work budget, HTTP/1 only,
  3s read-header / 5s whole-request read / 20s write / 5s idle / 20s handler-context
  limits, 8-KiB MaxHeaderBytes plus Go's bounded parsing allowance. Existing 16-KiB
  form, 4-MiB page and 15s worker-operation limits remain.
- Parent cancellation, session revoke/expiry, unexpected Serve termination and exact
  one-use consumption revoke consent and trigger bounded teardown. The host cancels
  work before a maximum 2s drain, then forces socket closure. Concurrent `Close`
  calls are idempotent; a closed/previously hosted session cannot get another host.
- `Done` means session revocation and listener/socket teardown. It is not a guarantee
  that arbitrary non-cooperative injected callbacks returned, a process-memory
  sandbox, packet-rate/backlog limit or kernel hard-real-time bound. The existing
  worker supervisor's kill/reap contract remains independent.
- No native browser launcher, default-opener reuse, custom-root picker, installed
  protocol/handler mutation, remote authorization, persistent preset or new API.
  The caller must close on launch failure. Closing a browser tab is not detected;
  explicit cancellation, owner shutdown and expiry remain the available boundaries.

The [source contract](../../../slicer-bridge/internal/presetconsent/README.md)
records exact host obligations and [Go server lifecycle semantics](https://pkg.go.dev/net/http@go1.26.6#Server).
Successful HTTP responses alone do not prove a native helper or actual slicer works.

## Browser-discovered correction

Real form submission reproduced **403** on the initial local-read approval.
The diagnostic observed POST `Origin: null` under the previous `no-referrer` policy.
This behavior is specified by the [Fetch Origin algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header).

The page now uses `Referrer-Policy: same-origin`, which permits same-origin native
form Origin while withholding cross-origin Referer. Exact Origin, nonce, CSRF and
field checks remain; null/missing/foreign origins are still rejected. A same-origin
request can send the private path back to the same unlogged listener. The
[referrer-policy definition](https://www.w3.org/TR/referrer-policy/#referrer-policy-same-origin)
and cross-origin navigation test support this tradeoff. Browser privacy overrides
that suppress Origin may still fail closed; no token-only fallback was added.

Initial failing browser attempts used request interception to constrain destinations;
the diagnostic reported missing fetch-site and null Origin. Corrected/final tests
use **no request interception or header overrides**. The isolated container has
network disabled, and request observation checks only the two owned loopback origins.

## Verification and retained attempts

| Capture | Exit / duration | Observed outcome |
|---|---|---|
| `server-preflight` | **1** / 20.662 s | Mixed-source compilation failure; not qualification |
| `server-preflight-b` | 0 / 33.069 s | 180 unit / 190 top-level / 399 inclusive passes; before referrer fix |
| `browser-preflight` | **1** / 1.225 s | 403 native-form rejection retained |
| `browser-diagnostic` | **1** / 1.211 s | 403 reproduced; Origin null recorded |
| `server-preflight-c` | 0 / 34.031 s | 180 / 190 / 399 passes; corrected referrer policy |
| `browser-preflight-b` | **1** / 5.123 s | Readiness timeout; launched before fixture build completed |
| `browser-preflight-c` | 0 / 15.493 s | 25 actual-HTTP scenarios pass |
| `server-preflight-d` | 0 / 33.062 s | 181 / 191 / 400 passes; adds independent work-budget regression |
| `server-final` | 0 / 168.213 s | 181 / 191 / 400 passes, formatting/vet, 30 cross-builds, ten fuzz smokes |
| `browser-final` | 0 / 15.244 s | 25 actual-HTTP scenarios pass against final source-built fixture |

All captures use fresh private directories under
`/home/vinnyc/.local/state/makersvault/verification/`, prefixed
`containment-mp1b9a-` and suffixed `-20260914`. None was overwritten.

The four failed captures remain failures:

1. The first Go preflight raced test-source creation: compilation saw a call to
   `serveBrowserFixture` before the new fixture file was part of that build.
   Start/end dirty-source status differs. It is **not a source-bound pass**.
   Source editing/formatting was completed before the next Go run.
2. The first browser attempt and diagnostic both reproduce the 403 form rejection.
   The latter records only redacted request facts, not private URLs/tokens.
3. Browser preflight-b started before its Go fixture build had finished and timed
   out waiting for readiness. This is retained as an orchestration/readiness failure,
   not an application-latency result. The same completed fixture passed the next run.
   The final browser run starts only after the final Go command exits successfully.

Final clean-source Go evidence: **181 unit tests with race detection**, ten seeded
fuzz targets, **191 top-level / 400 inclusive pass events**, zero fail/skip,
formatting and vet pass. Linux/Windows/macOS × amd64/arm64 compile bridge plus four
package-test binaries: **six targets / 30 builds**. Ten mutation fuzz smokes each
request five seconds with two workers; exact execution counts/elapsed reports are
in the [index](make-plate-local-server-verification.json). No failing fuzz corpus.
Cross-builds and short fuzzing are not native qualification or exhaustive proof.

New HTTP tests cover the complete explicit selection/review/consume sequence;
wrong Host/nonce/query, foreign/missing Origin, cross-site fetch, missing/duplicate
CSRF, raw root/unknown fields, oversized bodies and unsupported methods; socket
overflow/release; slow header/body and idle closure; oversized headers; expiry,
revoke, parent stop, accept failure and simulated owner handling of launch failure;
concurrent close/single ownership; handler-context cancellation and Cancel during
in-flight work. A separate detached-handler fixture verifies the work cap independently
of sockets, and confirms that arbitrary non-cooperative callbacks are not covered by
`Done`. Deadline tests use shortened internal limits; the 20s write deadline is
configured/asserted, not a measured slow-receiver or native kernel guarantee.

Final actual-browser evidence: **25 scenarios**, using Chromium 151.0.7922.34,
Firefox 153.0 and WebKit 26.5 headlessly on Linux. Each engine runs desktop
1024×768 and narrow 390×844 cases for full approval, cancellation, known-token
foreign-origin rejection and cross-origin referrer privacy. Six full flows cover
**36 HTTP stages**, including actual native form posts, no preselection, keyboard
radio use, checkbox selection and exact reviewed/consumed digest equality. A final
pipe-EOF case simulates the owner's reaction to launch failure. All owned fixture
processes exit 0 and reject new connections after teardown.

The Go test executable supplies a **synthetic, minimal/incomplete candidate backend**,
not real profile reads, installed-build detection or API-schema conformance. Its
readiness URL travels only over private test pipes; one fixed consume byte or EOF
controls teardown. This is test-only IPC, never a production protocol or native
browser launcher. Browser evidence joins the exact executable hash to the Go
capture. The narrow review screenshot was visually inspected; no page overflow.
No physical tablet, screen reader, native Windows helper or real DNS-rebinding
service is qualified.

## Evidence and unchanged scope

The [Go driver](make-plate-local-server-check.sh),
[browser driver](make-plate-local-server-browser.cjs),
[index](make-plate-local-server-verification.json) and
[read-only checker](make-plate-local-server-verify.cjs) bind source/commands,
fixture mounts/binary, counts/fuzz outcomes, screenshots and **54 artifact hashes**.
The previous private locked Playwright dependency tree is reused read-only and
rehash-checked; no dependency install or toolchain upgrade. All test containers run
offline; primary documentation was separately reviewed with browsing.
Historical MP-1b-8 evidence/checkers remain unchanged and are not made to qualify
the new source.

Verification uses UID/GID 1000, read-only source/fixture/dependency mounts and pinned
Go 1.26.6 image `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`,
plus Playwright 1.62.1 noble
`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`.
Formatting alone used a writable source mount; test listeners were confined to
disposable network-disabled containers, with no host port publication.

Release contract passes for v5.1.0. API/web/schema 17, production main/pairing/
file-open protocols, dependencies, preset projection/file readers and worker/hint
providers are unchanged. No fresh full-app/security-image/advisory qualification or
waiver transfer. The old exact-image E4/R57/F26/H0 decision stays historical.

## Re-cock

Next **MP-1b-9b: bounded native browser/folder-picker helpers and owner lifecycle**.
Establish fixed trusted invocation, bounded launch/selection/timeout/reaping, exact
private URL delivery and explicit local custom-root authority. Existing Start-only
pairing/default-opener code is not qualification for this flow. Do not activate main
until native Windows/hint/reader/lifecycle, independent versions, real profiles
and matched early worker dispatch are reviewed together.

MP-1c still couples scoped claim/review/commit, immutable storage, additive migration
and portable/raw recovery. MP-1d retains independent Bambu/Orca/Prusa conformance;
MP-2–4 remain unstarted. Owner-reported Windows Bambu v2.8.0.6 and YubiKey checks
remain unqualified. Mac-local import, CNC/CAM, Gate 12 desktop and further performance
tuning stay deferred; existing Mac file-open/browser scope is unchanged.

No Mac/device connection, live-vault/installed-handler change, gate closeout, push or
publication. The owner's separate ROADMAP and desktop notes remain untouched.
