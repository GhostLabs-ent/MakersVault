# Gate 11D-2 — durable secret-free audit results

**Date:** 2026-09-03

**Status:** Verified locally; owner acceptance pending

**Scope:** Durable structured audit events, exhaustive mutation/sensitive-read
classification, bounded secret-free records, Administrator-only cursor pagination,
identity-transaction audit atomicity, browser retrieval, and portability exclusion
proof only

## Outcome

Gate 11D-2 activates the `auditevent` structure reserved by schema 16. It adds no
new migration and changes no content record, path, or stored byte. Audit is a
mandatory server behavior: neither Administrator nor any other role can disable it,
change which actions are covered, weaken redaction, or delete events through the
application.

Implementation commit:

- `3c0fa69` — durable audit service and outcome middleware, atomic identity events,
  Administrator query API/UI, coverage/redaction/pagination/failure regressions, and
  `.mvault` exclusion proof

## Regression-first evidence

The audit regression was added before the service existed. Collection failed as
intended with `ModuleNotFoundError: No module named 'audit_service'`. The completed
regression then proved route coverage, stable actions, bounded fields, secret-detail
rejection, body/query exclusion, cursor pagination, Administrator-only access,
correlation, transactional identity behavior, post-commit failure truth, and
portable exclusion.

```text
Focused audit/account/session/portable matrix: 43 passed in 28.75s
Complete API suite: 278 passed in 106.22s (0:01:46)
Complete web suite: 10 files, 29 tests passed; typecheck and production build passed
```

## Coverage and correlation truth

- Every `POST`, `PUT`, `PATCH`, and `DELETE` route has a stable audit action.
- Sensitive reads are also audited: account and session administration, audit
  reads, folder/Artifact-history/Project exports, and scoped handoff redemption.
- The complete authorization inventory is now 95 routes: 92 session-authorized
  routes plus the same health, login, and scoped-handoff exceptions.
- Login success, invalid credentials, and throttling produce outcomes without
  persisting the submitted username or password. Authenticated events snapshot the
  actor ID, persisted username, and role at the time of the request.
- Every HTTP request receives a server-generated UUID correlation identifier in
  `X-Correlation-ID`. Audited records carry that same value; client-supplied values
  are not trusted.
- Results are derived from the final HTTP status as `success`, `denied`, or
  `failure`. Route templates—not raw URLs—are stored.

## Secret-free and bounded record truth

The outcome middleware never reads a request or response body. It stores no query
string. Audit records therefore do not contain passwords or hashes, cookie/session
secrets, CSRF values, handoff grants, recovery material, imported-site credentials,
notes, raw URLs, filenames, or private filesystem paths.

Persisted fields are limited to server ID/time/correlation, actor snapshot, stable
action/result, canonical UUID target where one exists, HTTP method, classified
route template, permission, status, bounded immediate client address, and a small
details object. Details accept only enumerated changed-field names and a bounded
revoked-session count; unknown keys or values are rejected before persistence.

Tests submit distinct secrets in login bodies, folder bodies, and query strings,
then inspect every persisted audit field and prove those values are absent.

## Transaction and failure truth

- Administrator account creation/update/reset, self-password change, and first-
  Administrator bootstrap append their success event in the same SQLite transaction
  as the identity mutation. A forced audit failure rolls the identity change back.
- Historical domain services commit independently. Their audit event is appended
  after the outcome because retrofitting false cross-service atomicity would be
  misleading.
- If a post-commit audit write fails while the response can still be replaced, the
  server returns `500 Operation completed but audit recording failed` and emits a
  secret-free security log. It does not falsely claim the domain mutation rolled
  back. The regression proves the mutation remains present.
- Audit I/O runs in a worker thread rather than blocking the ASGI event loop. The
  pure ASGI response boundary does not inspect or buffer streamed response bodies.

## Query and browser truth

- `GET /audit` requires the fixed Administrator-only `audit.read` permission.
  Member and Viewer requests are denied and that denial is itself audited.
- Each page is limited to 1–200 events and ordered newest first. An opaque cursor
  uses the immutable timestamp/ID boundary, so the audit-read event appended after
  a page cannot duplicate or skip older results.
- Settings exposes Security Audit only to Administrator. It shows outcome, actor,
  stable action, status, canonical target, route template, time, and correlation,
  with refresh and incremental older-page loading.
- There is no update/delete endpoint and no audit-disable, redaction, or coverage
  setting.

## Backup and portability truth

Durable audit records are installation security data inside raw format-1 backups and
must be protected with the rest of SQLite and `.env`. The existing `.mvault` v1
catalog remains frozen and secret-free. Its schema-16 exclusion regression now
inserts a real audit event and proves the actor, source marker, identities, roles,
password hashes, sessions, and audit data are absent from the portable archive.

The schema-16 `recoverymarker` remains only a reserved structure. Restore-time
session revocation, recovery event conversion, raw contract 5, and offline
Administrator recovery remain 11D-3 work.

## Repository verification

All repository verification targets passed on 2026-09-03:

```text
API: 278 passed in 106.22s (0:01:46)
Web: 10 files, 29 tests passed; typecheck and production build passed
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed with schema 16
Release contract: verified for v5.1.0
git diff --check: passed
```

The aggregate `make verify` invocation reached and passed container smoke, then the
lean-output wrapper hit its 120-second ceiling during teardown. `verify-smoke` and
`verify-release` were rerun independently and both exited successfully. The run used
local test containers only.

No image was pushed, no deployment was changed, and no tag, release, or publication
was made.

## Gate boundary

Gate 11D-2 is locally complete. Gate 11D-3 stopped-instance/raw recovery remains
unimplemented. Audit retention is intentionally indefinite and read-only in this
slice; no purge policy is being invented before recovery/backup behavior is proven.

The next authorized slice, after owner acceptance, is 11D-3 only. MFA, API keys,
OIDC/SSO, public registration, hosted tenancy, push, release, deployment, and
publication remain outside the gate.
