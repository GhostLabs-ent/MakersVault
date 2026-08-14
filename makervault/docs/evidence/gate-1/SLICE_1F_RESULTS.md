# Gate 1 Slice 1F Evidence

**Slice:** Single-admin login abuse controls, browser-token risk disposition,
security headers, and host policy

**Status:** Locally verified candidate

**Evidence date:** 2026-08-14

**Findings:** MV-SEC-007, MV-SEC-008, MV-SEC-009, MV-SEC-015

## Login abuse boundary

The API now applies a process-local, non-blocking progressive cooldown to failed
logins. State is tracked by immediate source plus normalized username and by
source alone, so changing usernames does not bypass the source guard. The first
two failures retain the generic `401`; the third starts a one-second cooldown,
and subsequent permitted failures double the delay to a 60-second ceiling.
Cooldown requests return generic `429` and integer `Retry-After` without checking
credentials or sleeping a worker.

Attempt state expires after 15 idle minutes and is capped at 2,048 entries with
oldest-entry eviction. A successful login clears its relevant state. Credential
comparison is constant-time and request fields have explicit length bounds.
Audit events record only success/failure/throttle outcome and the immediate
source; regression tests prove supplied passwords and issued tokens are absent.

This control is intentionally process-local. It matches the canonical one-process
API deployment and is not claimed as a shared multi-replica account service.

## Browser session disposition

The administrator JWT now lives in `sessionStorage`. New tokens are never written
to persistent storage. On first load, an existing `localStorage` token moves into
the current browser session and the persistent copy is deleted; logout clears
both stores defensively. Reload remains seamless, while closing the browser
session requires a new login.

The configurable 12-hour token and refresh behavior remain because shortening a
self-refreshing stateless token would not create revocation. Active-page XSS can
still read session storage, and an already copied token cannot be revoked by
logout. HttpOnly cookies, CSRF controls, durable session identifiers, and
invalidate-all-sessions remain one Gate 11 architecture boundary.

## Query-token residual risk

The v5.1 browser compatibility path still uses the administrator JWT in protected
primary-file and thumbnail URLs. Replacing it without regressing direct large-file
downloads and multiple preview loaders requires scoped ticket renewal or a
measured authenticated-media pipeline. That work remains assigned to Gate 2 and
Gate 11 rather than being represented as complete here.

Compensating controls now include the already isolated bridge protocol, remote
HTTPS requirement, session-only persistence, `Referrer-Policy: no-referrer`, CSP,
and `private, no-store` primary, thumbnail, prepared, supporting, and ZIP file
responses. MV-SEC-007 remains partially resolved with a dated explicit residual.

## Header and host boundary

The bundled Nginx gateway now emits:

- a CSP limited to self-hosted scripts, required WASM execution, inline styles,
  data/blob images, blob workers, and configured API/CORS origins;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- a restrictive `Permissions-Policy`; and
- CSP `frame-ancestors 'none'` plus `X-Frame-Options: DENY`.

The runtime entrypoint validates and injects the configured API/CORS sources into
the CSP. The same non-CSP baseline wraps direct API responses, including rejected
host responses.

`TRUSTED_HOSTS` provides an explicit comma-separated API allowlist. When absent,
`PUBLIC_URL` enables exact public-host enforcement plus loopback health checks.
When both are absent, direct-IP/mDNS LAN compatibility remains permissive under
the documented non-public deployment contract. Separate public API hostnames and
simultaneous public/LAN access have explicit configuration examples.

HSTS remains the external reverse proxy's explicit responsibility after the
operator commits a hostname to permanent HTTPS. The LAN-capable application
container does not silently make that operational decision.

## Regression and abuse evidence

| Layer | Proof |
|---|---|
| API | Cooldown progression, source guard, expiry, bounded memory, successful reset, generic errors, secret-free audit output, host derivation/matching/rejection, security headers, and protected-file no-store behavior pass. |
| Web | Legacy token migrates once; new tokens use session storage only; logout clears both stores; TypeScript, unit tests, and the production build pass. |
| Container | Generated Nginx configuration starts successfully; direct and same-origin API paths work; web/API security headers, body policy, schema, and non-root processes pass smoke. |

## Verification

| Check | Result |
|---|---|
| API/migration/security tests | Pass; 61 tests |
| Web unit tests | Pass; 7 tests |
| Web type check and production build | Pass |
| Bridge tests/build | Pass; 10 tests under Go 1.26.6 |
| Compose validation and production-secret assertions | Pass |
| Container smoke | Pass; direct/same-origin API and generated security headers |
| Complete repository harness | Pass; `make verify` |

## Finding disposition and gate status

- MV-SEC-015 is resolved in the locally verified candidate.
- MV-SEC-009 is resolved for v5.1 login abuse but remains open for durable session
  revocation in Gate 11.
- MV-SEC-008 is reduced by session-only persistence and CSP but remains open for
  active-page XSS and the final HttpOnly/session architecture in Gate 11.
- MV-SEC-007 remains partially resolved; the bridge boundary is fixed and the
  browser file-query compatibility residual is explicitly accepted for v5.1.

All Gate 1 implementation slices are locally verified. Gate 1 is ready for owner
closeout; no database, stored-file, or model-format migration occurred.
