# Gate 11D-1 — accounts and recent reauthentication results

**Date:** 2026-09-03

**Status:** Verified locally; owner acceptance pending

**Scope:** Administrator-created shared-vault accounts, forced password change,
recent password confirmation, last-Administrator safety, affected-session
revocation, schema/portable compatibility, and browser workflows only

## Outcome

Gate 11D-1 adds local account administration on top of the accepted three-role
shared-vault model. An Administrator can list accounts, create one with a temporary
password, edit its display name, assign a fixed role, enable or disable it, and set
a new temporary password. Every account can change its own password. There is still
no public registration, invitation or email reset, username rename, account
deletion, private ownership, or custom role editor.

Implementation commit:

- `cf8fcad` — schema 16, account administration and password services, recent
  password confirmation, last-Administrator protection, session invalidation, and
  Accounts & Access browser workflows

## Regression-first evidence

The account-administration regression was added before the service implementation.
Collection failed as intended because `account_service` did not exist. After the
implementation, the regression covers migration compatibility, last-Administrator
safety, authority-change revocation, the complete administrator/user password
workflow, and Member denial.

```text
Account-administration regression: 4 passed
Complete API suite: 272 passed in 98.90s (0:01:38)
Complete web suite: 10 files, 29 tests passed; typecheck and production build passed
```

## Schema and identity truth

- Additive migration 16 adds `browsersession.reauthenticated_at` and backfills an
  existing session from its creation time. It changes no content record, path, or
  stored byte.
- Schema 16 also reserves the accepted `auditevent` and `recoverymarker` structures
  for the next two slices. Gate 11D-1 does not write, query, or claim durable audit
  events or recovery markers yet.
- Usernames remain normalized and unique. Display names are bounded to 256
  characters. New password hashes use the accepted bounded Argon2id policy.
- New and Administrator-reset accounts require a password change. Until completed,
  the user may access only session status, logout, password confirmation, and their
  own password-change endpoint.
- `.mvault` v1 now accepts schema-16 sources while retaining its frozen schema-12
  content contract. Identity, hashes, sessions, reserved audit/recovery state, and
  deployment secrets remain excluded.

## Recent-password and session truth

- A successful password login records recent authentication for that browser
  session. Explicit password confirmation refreshes only that session's timestamp.
- The window is five minutes. Once it expires, the server rejects protected actions
  with `Recent password confirmation required`; browser visibility is not the
  enforcement boundary.
- Account creation, role/enablement changes, temporary-password resets, self-password
  changes, per-session/revoke-all actions, permanent deletion, and Empty Trash all
  require the current session to be inside that window.
- Role or enablement changes revoke the affected account's active sessions. An
  Administrator reset also revokes them and requires a password change at the next
  login. A successful self-password change revokes old sessions and issues a fresh
  cookie/CSRF pair.
- Passwords, hashes, browser-cookie secrets, CSRF values, and recovery material are
  never returned by account-list or account-mutation responses.

## Last-Administrator safety

Disabling or demoting the last enabled Administrator returns conflict without
changing the account. The count and mutation run under one service mutation lock
and one database transaction. This serialization matches MakersVault's supported
single API-process deployment. Account deletion is absent, so it cannot bypass the
invariant.

The focused regression proves rejection with one Administrator and successful
demotion only after another enabled Administrator exists. It also proves the
demoted account's prior session is immediately unusable.

## Authorization and browser truth

- Stable permissions now include `identity.manage_self` for all three roles and
  `identity.manage` plus the reserved `audit.read` permission for Administrator.
- Six new account/session routes are deny-by-default classified. The complete live
  inventory is now 94 routes: 91 session-authorized routes plus the same three
  explicit health, login, and scoped-handoff exceptions.
- Settings exposes Accounts & Access to every signed-in role for password
  confirmation and self-password change. Administrator additionally receives
  account creation, role/enablement, display-name, and temporary-password controls.
- A required password change replaces the normal vault UI until completed. Signing
  out remains available.
- Session Settings provides inline password confirmation before individual or
  revoke-all session actions.

## Repository verification

The clean repository gate passed on 2026-09-03:

```text
make verify: passed
API: 272 passed in 98.90s (0:01:38)
Web: 10 files, 29 tests passed; typecheck and production build passed
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed with schema 16
Release contract: verified for v5.1.0
git diff --check: passed
```

The run used local test containers only. No image was pushed, no deployment was
changed, and no tag, release, or publication was made.

## Gate boundary

Gate 11D-1 is locally complete. Gate 11D-2 durable secret-free audit and Gate 11D-3
stopped-instance/raw recovery remain unimplemented. In particular, the schema-16
tables reserved here are not evidence that audit capture, audit query, restore-time
session revocation, recovery markers, or administrator recovery already work.

The next authorized slice is 11D-2 only. MFA, API keys, OIDC/SSO, public
registration, hosted tenancy, push, release, deployment, and publication remain
outside the gate.
