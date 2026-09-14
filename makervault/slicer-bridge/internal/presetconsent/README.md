# Local preset preview/consent foundation — MP-1b-8

**Inactive in production.** This package adds a local session and HTTP handler,
not a listener, installed handler, browser launcher, new protocol action, remote
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
and the original 15-second worker budget bound each operation. `View`, `Apply` and
`TakeApproved` all check expiry/revocation before exposing data or authority. Call
`Close` on teardown; this is not a secure-memory-erasure or immediate-GC guarantee.
Backend dependencies are internal/test-injected, not an external adapter registry.

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
headers include no-store, no-referrer, nosniff, no framing, and a default-deny CSP
with only local forms/inline static CSS. A 4-MiB buffered rendering ceiling checks
both writer methods; failures emit no partial page. Normalized review bytes have a
separate 2-MiB ceiling. Radio/checkbox labels, visible focus and 44px-minimum buttons
support keyboard/tablet use; physical devices and screen readers are unqualified.

Do not publish the local nonce URL, CSRF token, paths, account names or form bodies
to logs/server. Local malware or a process already able to read browser/session
memory is outside this boundary. Tests of an unmounted handler are not proof of
DNS-rebinding/connection containment by an actual server or OS browser launch.

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

MP-1b-9: isolated local server/launcher lifecycle harness, before production
activation. Bind only numeric loopback; set bounded connections, read/write/header/
idle deadlines; cancel workers and close sockets/session on expiry, revoke, browser
failure and shutdown. Qualify actual HTTP-origin/form behavior and the bounded native
folder picker/custom-root source without accepting HTTP paths. Keep main/protocols
inactive until native Windows/hint/reader/lifecycle, independently observed versions,
real profiles and matched early worker dispatch are reviewed together. MP-1c still
owns remote claim/matching-code/approval/submit/commit and whole persistence/recovery.

Primary implementation references: Go's [bounded HTTP readers](https://pkg.go.dev/net/http@go1.26.6#MaxBytesReader)
and [contextual HTML templates](https://pkg.go.dev/html/template@go1.26.6), plus the
existing [worker](../presetworker/README.md), [hint](../presetfiles/ACCOUNTS.md) and
[accepted ADR](../../../docs/adr/0020-printer-presets-and-plate-recipes.md) contracts.
