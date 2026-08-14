# Gate 1 Entry Record

**Gate:** 1 — Harden v5.1 trust boundaries and deployment

**Status:** Implementation complete; owner closeout pending

**Opened:** 2026-08-14

**Public baseline:** `63ade54cad7b1681cf2a33f62c0512d6d80bc45c`

**Local Gate 0 closeout:** `8c1b646`

## Objective

Make a fresh v5.1 deployment safe by default for its documented single-admin,
self-hosted scope. Gate 1 does not add users, roles, MFA, SSO, hosted operation,
or machine control.

## Verified entry conditions

- Gate 0 is accepted. Its local and remote verification harnesses passed.
- Production consists of separate API and static-web containers. The web
  container provides the recommended same-origin `/api` gateway.
- The API still falls back to published administrator and JWT secrets.
- The canonical production Compose manifest also supplies those published
  fallbacks when environment variables are absent.
- The current administrator identity is environment-configured; no database
  user, password-hash, bootstrap-token, revocation, or role model exists.
- The bridge accepts a URL supplied through a custom protocol invocation and can
  fall back to the operating system's default opener.
- The Gate 0 security revalidation assigns the remaining confirmed findings to
  Gate 1, Gate 2, Gate 5, or Gate 11 without claiming unrestricted Internet
  exposure is safe.

## Gate 1 workstream order

| Slice | Scope | Primary findings | Entry dependency |
|---|---|---|---|
| 1A | Fail-closed production authentication configuration and deployment posture | MV-SEC-002 | Owner checkpoint below |
| 1B | Compatible Python, web-build, and Go toolchain upgrades with fresh scans | MV-SEC-004, MV-SEC-005 | Locally verified; evidence recorded |
| 1C | Upload, image, archive, model, time, and storage budgets; ZIP path safety; mounted symlink containment | MV-SEC-006, MV-SEC-011, MV-SEC-013 | Budget values documented before enforcement |
| 1D | Redirect- and connection-aware remote-import SSRF controls | MV-SEC-003 | Adversarial network test harness |
| 1E | Short-lived file-scoped handoff grants and a bridge allowlist contract | MV-SEC-001, MV-SEC-007 | Grant and origin contract accepted |
| 1F | Single-admin login abuse controls, token-risk disposition, security headers, and deployment guidance | MV-SEC-008, MV-SEC-009, MV-SEC-015 | Earlier auth and proxy behavior stable |

Gate 2 retains browser preview/parser performance budgets. Gate 5 retains release
provenance. Gate 11 retains multi-user authorization and the final session model.

## Owner checkpoint 1 — first-run administrator experience

**Decision:** Accepted 2026-08-14.

### Recommended for v5.1: guided environment setup

- Keep the existing single administrator and environment-based credential
  contract.
- Make production mode the fail-closed default.
- Require a non-placeholder password and a deployment-specific signing secret of
  at least 32 random bytes before the API starts.
- Validate in both the production Compose boundary and API startup so bypassing
  one layer does not restore unsafe defaults.
- Provide a local setup helper and a canonical root `.env.example` with actionable
  migration instructions.
- Permit explicit development mode only in the source-development manifest and
  test harness. Never enable it in the production manifest.
- Preserve existing deployments that already provide safe values. Deployments
  relying on published defaults must configure secrets before upgrading.

This is recommended because it closes MV-SEC-002 without adding a password store,
bootstrap endpoint, first-visitor-wins risk, recovery flow, or schema migration to
the v5.1 confidence release.

### Deferred alternative: browser first-run setup

A browser flow would create the administrator and generate a persisted signing
secret. It is friendlier after container startup but requires a protected
bootstrap ceremony, password hashing and storage, recovery semantics, concurrent
first-request handling, and a new migration boundary. It should be designed with
the Gate 11 session architecture unless the owner deliberately expands v5.1.

## Owner checkpoint 2 — supported access posture

**Decision:** Accepted 2026-08-14.

### Recommended v5.1 contract

- Localhost and a genuinely trusted LAN are supported for direct operation, with
  documentation that plain HTTP does not protect credentials or tokens from
  network observers.
- Remote access is supported only through an operator-managed HTTPS reverse proxy
  or a private network/VPN that supplies equivalent transport protection.
- One HTTPS hostname routed to the web container is the recommended topology.
- Existing two-hostname UI/API reverse proxies remain supported with explicit
  `VITE_API_URL` and `CORS_ORIGINS` configuration.
- Direct exposure of the API port or unencrypted MakersVault ports to the public
  Internet is unsupported for v5.1.

This posture does not require MakersVault to obtain certificates or introduce a
hosted dependency. It states the boundary the application and tests must enforce
and document.

## First implementation slice after approval

Slice 1A will add configuration validation as a small API module, startup failure
tests, Compose interpolation checks, a secure setup helper, and upgrade/operator
documentation. It will not change the database, stored files, model formats, or
browser login workflow.

**Rollback:** restore the previous environment contract and application image.
No user data migration is involved. Rolling back to known defaults is permitted
only on an isolated recovery network and must not be documented as normal
operation.

## Acceptance boundary

Both owner-checkpoint recommendations are accepted. Slice 1A implementation is
authorized; later slices retain their stated entry dependencies and any new
owner checkpoints.
