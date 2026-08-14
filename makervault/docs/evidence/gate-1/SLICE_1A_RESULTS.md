# Gate 1 Slice 1A Evidence

**Slice:** Fail-closed production authentication configuration and deployment
posture

**Status:** Locally verified

**Evidence date:** 2026-08-14

**Finding:** MV-SEC-002

## Decision implemented

The owner accepted guided environment setup for v5.1 and deferred a stateful
browser bootstrap to the later session architecture. The owner also accepted
localhost/trusted-LAN operation plus HTTPS reverse proxy or private-VPN remote
access, with direct public port exposure unsupported.

## Behavior

- Production is the API's default security environment.
- Production Compose requires non-empty `AUTH_PASSWORD` and `AUTH_SECRET` values
  before it resolves.
- API startup independently requires a non-empty username and password, a
  password of at least 12 characters, and a deployment-specific signing secret
  of at least 32 bytes.
- Published placeholder values are rejected. The signing secret cannot equal the
  administrator password.
- The source-development manifest and test harness select explicit
  non-production modes and contain no implicit API fallback.
- `scripts/setup-env.sh` refuses to overwrite existing configuration, generates
  a random password and 256-bit secret, and writes `.env` with mode `600`.
- Existing safe environment values remain compatible. An installation relying on
  published defaults must configure secrets before upgrading.

## Verification

| Check | Result |
|---|---|
| API and migration suite | Pass; 19 tests under Python 3.11 |
| Missing production password | Startup rejected with actionable error |
| Missing production signing secret | Startup rejected with actionable error |
| Published or short values | Rejected by parameterized regression tests |
| Valid explicit production configuration | Accepted |
| Generated configuration | Accepted by production API validation |
| Generated `.env` permissions | Mode `600` |
| Existing `.env` overwrite protection | Implemented as fail-closed precondition |
| Production Compose without secrets | Rejected before container creation |
| Canonical and compatibility Compose with safe values | Pass |
| Complete repository harness | Pass; `make verify` |
| Container smoke | Pass; direct and same-origin API, non-root processes, schema 3 |

## Files and data affected

Authentication configuration, Compose interpolation, tests, setup tooling, and
operator documentation changed. No database schema, database contents, managed
file, mounted library, session representation, or browser login workflow changed.

Changing `AUTH_SECRET` intentionally invalidates existing JWTs. The operator must
sign in again; no persistent data is lost.

## Rollback

Restore the previous application and environment contract. Because slice 1A has
no data migration, rollback does not require database or storage restoration.
Published credentials must not be restored on a reachable deployment.

## Residual risk and next slice

MV-SEC-002 is resolved in the locally verified candidate. Gate 1 remains open:
dependency advisories, upload/archive bounds, SSRF connection control, scoped
bridge handoffs, login abuse controls, token propagation, and security headers
retain their assigned slices.

Proceed to slice 1B only after slice 1A is committed locally as an independent
rollback point.
