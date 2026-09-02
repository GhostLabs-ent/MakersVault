# Gate 11B — revocable browser-session results

**Date:** 2026-09-01

**Status:** Verified locally; owner acceptance pending

**Scope:** Additive session schema, opaque cookie authentication, Origin/CSRF
enforcement, browser migration, expiry/cleanup, logout and revocation, and
identity-free portability only

## Outcome

Gate 11B replaces renewable browser JWTs with opaque, server-side, revocable
sessions. The browser receives the session secret only as a host-only HttpOnly
cookie, never through JSON, JavaScript storage, an authorization header, or a file
URL. Login rotates any session presented by that browser; logout, per-session
revocation, and revoke-all take effect immediately.

Implementation commit:

- `5ca1a42` — schema 14, opaque sessions, cookies and CSRF, web migration/session
  settings, deployment configuration, portability and compatibility regressions

## Regression-first evidence

The new API suite was collected before `session_service` existed and failed as
intended:

```text
ModuleNotFoundError: No module named 'session_service'
```

The new browser contract also initially failed all three focused assertions because
legacy storage migration remained and the cookie-aware fetch/CSRF functions did not
exist. After implementation and the cross-host CSRF refinement:

```text
Gate 11B session/login/migration focus: 26 passed in 14.80s
Session/handoff/portable/configuration focus: 46 passed in 21.09s
Complete API suite: 259 passed in 89.28s (0:01:29)
Complete web suite: 9 files, 26 tests passed; typecheck and production build passed
```

## Persistent-session truth

- Additive migration 14 creates `browsersession` without changing the accepted
  schema-13 identity or any model, Project, Machine, revision, path, or stored byte.
- Each login creates a 32-byte random opaque secret. SQLite stores only a
  context-separated HMAC-SHA-256 digest, user ID, timestamps/expiry, revocation,
  idle policy, and bounded client address/user-agent metadata.
- The current policy defaults to a 12-hour idle expiry, seven-day absolute expiry,
  five-minute persisted touch interval, and at most 20 active sessions for the one
  account. Configuration rejects non-positive, inverted, or excessive bounds.
- Expired, revoked, malformed, disabled-user, and unknown sessions fail closed.
  Expired/revoked rows are removed in bounded batches; active-session admission is
  capped before a new record is committed.
- `GET /session` validates the current session; `GET /sessions` lists only the
  current user's active sessions. `POST /logout`, `DELETE /sessions/{id}`, and
  `POST /sessions/revoke-all` provide current, individual, and all-session
  revocation. The web exposes these controls under **Settings → Browser Sessions**.
- The reusable revoke-all service is the required hook for later password, role,
  and recovery operations. Those operations do not exist in 11B and remain gated.

## Cookie, Origin, and CSRF truth

- Production uses `__Host-makersvault_session` with `Secure`, `HttpOnly`,
  `SameSite=Lax`, `Path=/`, and no `Domain`. Production browser access therefore
  requires HTTPS.
- The non-Secure `makersvault_session_dev` name exists only in explicit
  `development` and `test` environments; production cannot silently downgrade.
- Every unsafe cookie-authenticated route requires an `Origin` that exactly matches
  a configured browser origin after canonical HTTP(S) normalization.
- CSRF is context-separated and bound cryptographically to the presented opaque
  session. It is returned only after successful login or a safe authenticated
  session check. The web retains it in memory, with a readable host cookie as a
  same-host convenience; neither SQLite nor browser local/session storage contains
  the CSRF value.
- The in-memory response path keeps intentionally separate same-site web/API hosts
  usable even though a `__Host-` cookie is correctly unreadable from another host.
- Authentication and session responses are `private, no-store`. CORS remains a
  browser transport policy and is not treated as authorization.

## Browser and handoff migration

- The web deletes legacy `makersvault_auth_token` values from both `localStorage`
  and `sessionStorage`; it does not migrate or refresh them.
- All API fetches include cookies, unsafe requests add the bound CSRF header, and
  ordinary requests never construct a Bearer header.
- Protected preview/file URLs contain no authentication query parameter. The API
  rejects both the retired query-token and Bearer paths, and `/refresh` no longer
  exists.
- Gate 8's separately derived, 90-second, exact-file bridge handoff grant is
  unchanged. It cannot authenticate an ordinary API route and the browser session
  never crosses the custom-protocol boundary.

## Backup and portability boundary

- Raw stopped schema-14 backup includes keyed server-side session rows and the
  deployment secret, but never the browser cookie value. Until 11D adds automatic
  restore detection/revocation, a raw restore must stay isolated while the owner
  signs in and uses revoke-all before exposure.
- `.mvault` v1 now accepts schema-12, schema-13, and schema-14 sources while
  exporting no user, password hash, session record, session/CSRF value, credential,
  or audit state. The frozen clean importer still reconstructs schema 12; startup
  applies 13–14 and bootstraps a new local administrator.
- Identity/session-aware raw recovery audit and formal recovery ceremony remain
  explicit 11D work and are not claimed by 11B.

## Repository verification

The final clean repository gate passed on 2026-09-01:

```text
make verify: passed
API: 259 passed in 89.28s (0:01:29)
Web: 9 files, 26 tests passed; typecheck and production build passed
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed (direct and same-origin cookie sessions, logout revocation,
security headers, 512 MiB policy, non-root API/web UIDs, schema 14)
Release contract: verified for v5.1.0
```

`pip check`, `git diff --check`, and the release-contract verifier also passed. The
run used local test containers only.

No image was pushed, no deployment was changed, and no tag, release, or publication
was made.

## Gate boundary

Gate 11B is ready for owner review. Acceptance will freeze only the browser-session
and CSRF contract. Additional users, roles,
permission enforcement, password/account administration, last-admin safety,
recovery, audit events, MFA, API keys, OIDC, public registration, hosted tenancy,
push, release, and deployment remain unauthorized. Gate 11C must not begin until
the owner accepts this checkpoint explicitly.
