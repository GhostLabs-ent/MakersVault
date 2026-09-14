# Local preset preview/consent foundation — MP-1b-8

**Inactive in production.** MP-1b-8 added the local session and HTTP handler;
MP-1b-9a adds its bounded numeric-loopback host and actual HTTP/browser harness.
MP-1b-9b-1 adds an inactive Windows UI helper and one-attempt owned-URL launcher.
MP-1b-9b-2 adds Linux UI helpers; MP-1b-9b-3 wires asynchronous custom selection
inside this still-inactive session, with synthetic HTTP/browser evidence only.
There is no installed handler, production native UI dispatch, new protocol action, remote
claim/import endpoint, stored snapshot or desktop application. Production main is
unchanged. Mac-local preset import stays owner-deferred. No real workstation
profiles or Windows known-folder calls were used in this slice's tests.

## Explicit local sequence

`New` accepts locally constructed configuration: a bounded HTTPS display origin,
an expiry no later than five minutes, and optionally one explicitly configured
custom root. JSON cannot populate/export this configuration. The origin is **not
authenticated by this package**; the page says so. Future protocol/claim binding
must validate the request/origin independently. No trust file is consulted or saved.

1. Initial page and construction perform no hint lookup or file read. A distinct
   local-reading approval is required, even for an already trusted download origin.
2. Acquire unobserved Bambu root suggestions, or plan the explicit custom root
   without native probing. Require selection; no first/default root is selected.
3. List the chosen root's account folders. Offer system-only as a separate explicit
   choice, never a preselection. Failed account listing produces a warning and only
   that explicit option; it does not execute a fallback scan. Cancelled/expired
   operations fail instead. Actual profile reading still enforces the root boundary.
4. Discover only the explicitly selected account/system source. Select up to 100
   preset identities; none is prechecked. Source disappearance/rename is a fresh
   selection failure, never substitution of the earlier discovery result.
5. Rescan through `select` and render the exact normalized JSON bytes for review,
   including nullable fields, reason codes and a SHA-256 review digest. Labels may
   contain private user-authored text. This technical preview is not the finished
   server-side import/editor UI or a print-ready/geometry-complete assertion.
6. Local approval must match the current form revision and displayed byte digest.
   `TakeApproved` returns a copy of those same bytes **once**, without root/account
   fields. It does not rescan, send, stage or save anything. Cancellation/expiry still
   revokes an approved-but-unconsumed preview. Remote approval/trust/revocation and
   strict API candidate validation remain independently required in MP-1c.

Every root/account/preset choice uses a fresh random 256-bit local ID; forms cannot
submit filesystem paths, raw account names, executable choices or preset settings.
A new random revision is consumed before each operation. Stale forms, old choice
IDs, duplicate/oversized selections and concurrent work fail. Start-over discards
the current choices/review and requires approval again; it does not extend expiry.
Cancel remains usable from a stale form after valid local CSRF checks. It can run
while worker I/O is outstanding; late results cannot resurrect the session.

State access is serialized. Locks are released during worker I/O so another local
request or owner cancellation can revoke it. Request cancellation, session expiry
and the original 15-second worker budget bound each metadata operation. The
explicitly consented asynchronous picker has separate ownership below. `View`, `Apply` and
`TakeApproved` all check expiry/revocation before exposing data or authority. Call
`Close` on teardown; this is not a secure-memory-erasure or immediate-GC guarantee.
Backend dependencies are internal/test-injected, not an external adapter registry.

## Asynchronous custom-folder consent — MP-1b-9b-3

The initial page offers **Allow local reading and choose a folder**, explicitly
authorizing the native dialog without first looking up default hints. Alternatively,
the root-choice page offers **Choose a custom folder** after ordinary reading
consent. Both use the existing CSRF/revision-bound local POST with decision `browse`;
no new HTTP fields, paths, account names, initial directory or native options.
GET, stale forms, pre-cancelled requests, wrong stages and missing providers cannot
launch it. The default locally constructed backend calls `presetui.PickFolder`.
Production main still does not dispatch the private UI action; this is not activation.

Acceptance rotates the revision, removes old choices, starts one callback and
returns the HTTP page immediately. Its context is bounded by the existing session
expiry and **90s picker budget**, not the accepting request's 20s deadline. A later
request disconnect does not revoke accepted local interaction. The script-free
waiting page offers an explicit same-path GET **Refresh status**, **Cancel folder
selection**, and whole-preview **Cancel**. No automatic polling or tab-close detector.

`stop-picker` needs a current revision and cancels only the picker. The busy slot
remains occupied until its callback returns; no restart, parallel picker or metadata
work queues behind it. Whole-session cancellation/expiry/owner shutdown cancels it
and immediately revokes visible authority. Late successful results are discarded.
Host `Done` still does not guarantee arbitrary callback or OS-provider UI cleanup;
the helper supervisor's actual kill/reap slot remains a separate bound. One bounded
operation may retain its previous choices in memory until it returns; no secure
erasure or hard-real-time callback completion is asserted.

A successful canonical local path is validated with the existing pure root planner,
kept only in local session memory, and offered as one **unselected opaque ID** with
a generic workstation-folder label. **Use this folder** must still be submitted
before account enumeration, and account/system selection precedes preset discovery.
The dialog confirms which folder was picked; its raw result is not rendered into
HTML/form fields or normalized preview. Existing default/configured-root hint labels
may display local paths; this change does not claim to remove those older labels.
Native folder browsing itself can access filesystem/provider state and is not a
sandbox or profile-read grant. Error messages concern preset reads, not OS UI I/O.

Cancellation, timeout, unsafe/empty paths and helper failure produce fixed redacted
warnings, never an automatic scan. Any previous unselected roots return with fresh
IDs; a successful new folder replaces them. Start-over discards the picked root and
requires consent again, without extending expiry; a separately configured CustomRoot
retains its pre-existing configuration semantics. Native Windows/Linux dialogs,
provider side effects, accessibility, real profiles and installed versions remain
unqualified. All browser picker completions in this checkpoint are test-only stdin
signals, not evidence that the real native helper was dispatched.

## Local HTTP boundary

`NewLocalHandler` requires an exact `127.0.0.1:<nonzero-port>` authority. It creates
a random nonce path and independent CSRF token, but never binds a socket. Every
request checks loopback remote address, exact Host and path, no query/encoded-path
alias, and rejects foreign Origin/fetch-site values. POST additionally requires
the exact local Origin and CSRF token; it accepts only URL-encoded forms, with a
16-KiB body ceiling, an exact field allowlist and duplicate-field/count checks.
GET is read-only; only GET/POST are supported. There is no CORS permission, script,
external asset, cookie/session token, arbitrary callback or URL redirect.

HTML uses contextual `html/template` escaping, no trusted dynamic HTML. Privacy
headers include no-store, same-origin referrer policy, nosniff, no framing, and a default-deny CSP
with only local forms/inline static CSS. A 4-MiB buffered rendering ceiling checks
both writer methods; failures emit no partial page. Normalized review bytes have a
separate 2-MiB ceiling. Radio/checkbox labels, visible focus and 44px-minimum buttons
support keyboard/tablet use; physical devices and screen readers are unqualified.

Do not publish the local nonce URL, CSRF token, paths, account names or form bodies
to logs/server. Local malware or a process already able to read browser/session
memory is outside this boundary. MP-1b-8's unmounted tests remain historical;
MP-1b-9a now exercises real HTTP Host/Origin controls and browser forms. It is not
native OS browser-launch, DNS-service/rebinding or physical-device qualification.

## Numeric-loopback host — MP-1b-9a

`StartLocal` attaches one session once, binds only `tcp4` at `127.0.0.1:0`, and
returns a private URL. No hint, profile read or browser lookup occurs on startup.
At most eight connections enter net/http; excess accepted sockets are immediately
closed. A separate eight-handler budget covers work outliving a connection.
Only HTTP/1 is enabled. Defaults: 3s header, 5s whole-request read, 20s write,
5s idle and 20s handler context deadlines; 8-KiB MaxHeaderBytes (plus Go's bounded
parser allowance), existing 16-KiB forms and 4-MiB page ceiling. Worker operations
retain their own 15s/context budget. These are not OS backlog/packet-rate or
hard-real-time guarantees; deadline tests use shortened internal test limits.

Owner/context cancellation, session expiry/revoke, exact one-use consumption or
an unexpected Serve failure revoke the session and cancel work. Shutdown permits
at most 2s drain before forcibly closing sockets. `Close` is concurrent-safe and
waits for teardown; do not call it synchronously from its own HTTP handler.
`Done` means revocation and listener/socket teardown, not guaranteed return of an
arbitrary non-cooperative callback. Existing worker kill/reap guarantees are separate.
`OpenBrowser` now closes on launch failure/cancellation; its Windows helper is
implemented but not natively qualified or production-dispatched. No tab-close
detector is delivered. The test-only readiness pipe/EOF fixture is not production IPC.

Actual browser POSTs exposed that `no-referrer` produces `Origin: null` for native
forms. The page now uses `same-origin`: exact Origin/CSRF enforcement stays, and
cross-origin navigations receive no Referer. Same-origin requests may carry the
private path back to this same unlogged listener. Do not add request logging.
Null/missing/foreign origins remain rejected; privacy settings overriding Origin
can therefore fail closed. The [Fetch Origin algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header)
and [same-origin policy](https://www.w3.org/TR/referrer-policy/#referrer-policy-same-origin)
explain this choice. Browser tests use no interception or Origin/header overrides.

## Bounded native hints without broader environment inheritance

Use `presetworker.NativeLocations`, not the direct Windows provider. Windows runs
`SHGetKnownFolderPath` inside the existing single-use worker via `native-locations`,
which accepts **no** root/account/input/pick/hint fields. The parent validates an
exact three-root known plan with common base and fixed labels. Roots travel only
in the distinct private envelope; public response JSON cannot emit them. Other
operations reject those private fields. A hung-worker fixture with this request
exercises the existing timeout/kill/reap slot; it is not an actual Windows Shell hang.

Linux only copies XDG/home strings and invokes the pure planner, with no filesystem,
NSS or executable lookup. It does not inherit those variables into the child;
the Linux worker explicitly refuses `native-locations` rather than guessing from
its sanitized environment. The Windows provider itself and supervisor are unchanged;
native Windows ABI, Shell/filter semantics and startup/lifecycle still need execution.
No OS-level memory sandbox, hard real-time kernel guarantee or parent-crash child
cleanup is claimed. The old direct file/hint APIs remain cooperative if bypassed.

## Required next integration checkpoint

MP-1b-9 is split into evidence checkpoints, not closed. MP-1b-9a establishes the
local server and synthetic browser lifecycle above. MP-1b-9b-1 adds the isolated
[Windows helper foundation](../presetui/README.md) and one-attempt owned-URL launch,
including local failure/cancellation revocation. MP-1b-9b-2 adds the inactive
[Linux fixed-tool helper foundation](../presetui/LINUX.md). MP-1b-9b-3 adds the
asynchronous consented selection above without submitted paths or longer HTTP
deadlines. Next MP-1b-9b-4 is matched native Windows/Linux desktop qualification
planning and scoped execution; production remains off until those checks pass.
Do not reuse the legacy pairing launcher
as qualified evidence: its Start-only/default-opener behavior is not this contract.
Keep main/protocols
inactive until native Windows/hint/reader/lifecycle, independently observed versions,
real profiles and matched early worker dispatch are reviewed together. MP-1c still
owns remote claim/matching-code/approval/submit/commit and whole persistence/recovery.

Primary implementation references: Go's [bounded HTTP readers](https://pkg.go.dev/net/http@go1.26.6#MaxBytesReader)
and [contextual HTML templates](https://pkg.go.dev/html/template@go1.26.6), plus the
existing [worker](../presetworker/README.md), [hint](../presetfiles/ACCOUNTS.md) and
[accepted ADR](../../../docs/adr/0020-printer-presets-and-plate-recipes.md) contracts.
