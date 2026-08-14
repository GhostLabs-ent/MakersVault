# Gate 1 Slice 1F Design

**Slice:** Single-admin login abuse controls, browser-token risk disposition,
security headers, and host policy

**Status:** Owner-approved implementation contract

**Approved:** 2026-08-14

**Findings:** MV-SEC-007, MV-SEC-008, MV-SEC-009, MV-SEC-015

## Current executable truth

MakersVault has one environment-configured administrator. The API issues a
12-hour stateless JWT, the web client stores it indefinitely in `localStorage`,
and a valid token can refresh itself. Logout only deletes the browser copy.
There is no login throttle, session store, revocation list, MFA, or recovery
workflow.

Normal API calls send the JWT in an authorization header. Browser-rendered
primary files and thumbnails still append that administrator JWT to a query
string because image elements, download links, and several model loaders cannot
all set request headers. The v5.1 bridge no longer receives this token.

The bundled Nginx proxy has cache controls but no common browser-security header
policy. FastAPI has no trusted-host middleware. The already accepted deployment
contract supports direct localhost/trusted-LAN use and remote use through an
operator-managed HTTPS reverse proxy or private VPN; direct public exposure of
the application ports is unsupported.

## Proposed v5.1 capability contract

### Login abuse control

1. Failed login checks are tracked in bounded process memory by immediate client
   address and normalized username, with an additional per-source guard so
   rotating usernames does not bypass the control.
2. The first two failures return the existing generic `401`. Starting with the
   third failure, a non-blocking cooldown begins at one second and doubles after
   each permitted failed attempt to a maximum of 60 seconds. Requests received
   during a cooldown return generic `429` plus `Retry-After` without checking the
   credentials.
3. A successful login clears the relevant failure state. Idle entries expire
   after 15 minutes, the map has a fixed maximum size, and API restart clears it.
   This matches the current single-process deployment without inventing a
   database-backed account/session model.
4. Username and password comparisons use constant-time comparison. Login audit
   events record success, failure, or throttling and the immediate client address,
   but never record a password or token.
5. The bridge-facing and normal API token formats remain separate. No account
   lockout, email recovery, multi-user policy, MFA, or shared rate-limit service
   is introduced in v5.1.

### Browser session persistence

6. The administrator JWT moves from `localStorage` to `sessionStorage`. Reloading
   the current tab remains seamless, while closing the browser session removes
   the token. On first v5.1 load, an existing `localStorage` token is moved once
   into `sessionStorage` and deleted from persistent storage so upgrades do not
   force an immediate sign-in.
7. The default 12-hour token lifetime and existing refresh behavior remain
   configurable. Shortening the token alone would not provide revocation because
   a valid token can refresh; presenting it as a complete fix would be false.
8. Active-page XSS can still read `sessionStorage`, and logout still cannot revoke
   an already copied stateless JWT. HttpOnly cookies, CSRF protection, durable
   session identifiers, session revocation, and invalidate-all-sessions remain a
   single Gate 11 architecture change.

### Browser file URLs

9. The administrator JWT query-string compatibility path remains for v5.1
   browser previews and direct large-file downloads only. Replacing it safely
   requires either scoped browser file tickets with renewal semantics or an
   authenticated media pipeline that does not regress large-file memory and
   preview behavior. That work belongs with Gate 11's session contract and Gate
   2's preview budgets, not an unmeasured change at Gate 1 closeout.
10. Compensating controls in v5.1 are: HTTPS for remote use, `Referrer-Policy:
    no-referrer`, protected-file `private, no-store` responses, query-token
    exclusion from bridge handoffs, session-scoped browser persistence, and the
    CSP below. The residual risk remains explicitly open rather than marked
    resolved.

### Security headers and host policy

11. Both the bundled Nginx path and direct API responses add `nosniff`,
    `Referrer-Policy: no-referrer`, a restrictive `Permissions-Policy`, and
    framing denial. The web CSP permits only the resources required by the
    current Vite/Three.js/OCCT application: self-hosted scripts, WASM execution,
    inline styles, data/blob images, blob workers, and the configured API origin.
    It denies plugins/objects, base-tag rewriting, framing, and foreign form
    targets. It does not enable generic remote scripts.
12. HSTS remains the external HTTPS reverse proxy's responsibility. The bundled
    container also supports intentional trusted-LAN HTTP, cannot know whether an
    operator's public hostname is permanently HTTPS-only, and must not silently
    pin a LAN or temporary hostname.
13. `TRUSTED_HOSTS` is an optional comma-separated API host allowlist. When it is
    unset and `PUBLIC_URL` is configured, the API derives the exact public host
    and also permits loopback health checks. When neither is configured, host
    filtering remains permissive for direct IP/mDNS LAN compatibility; this is
    acceptable only inside the already documented non-public posture.
14. The recommended one-host HTTPS deployment therefore gains host enforcement
    from its required `PUBLIC_URL` setting without another setup step. Existing
    separate UI/API hostnames must set `TRUSTED_HOSTS` to the API hostname.

## Required proof

- Login cooldowns progress without sleeping a request worker, return an integer
  `Retry-After`, resist username rotation per source, reset on success, expire
  idle state, and keep bounded memory.
- Login responses stay generic and audit output contains no supplied password or
  issued token.
- Existing persistent tokens migrate once to session storage; new tokens never
  remain in local storage; logout clears both stores.
- The production web response carries the tested CSP and common headers; current
  TypeScript, unit tests, Vite build, WASM/worker assets, and container smoke pass.
- Configured or `PUBLIC_URL`-derived hosts are accepted, unlisted hosts are
  rejected, and the empty direct-LAN compatibility mode is documented.
- Protected primary, thumbnail, prepared, and supporting-file responses are
  private/no-store and carry the API security baseline.

## Compatibility, residual risk, and rollback

No database or stored-file migration is required. Users remain signed in in the
tab that performs the one-time storage migration, but will sign in again after
closing that browser session. Operators with a separate public API hostname must
add one documented `TRUSTED_HOSTS` value before enabling host enforcement.

The in-memory throttle is intentionally not represented as multi-replica or
durable protection. Browser query credentials, active-page XSS exposure, and
stateless-token revocation remain dated residual risks assigned to Gates 2 and
11. Reverting this slice restores the old persistence/header/host behavior and
does not transform user data.
