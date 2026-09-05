# Gate 11E-1d results — browser, policy, reset, and closeout

**Date:** 2026-09-04

**Status:** Complete — owner checkpoint

**Entry commit:** `f1a8734`

**Schema:** 17 unchanged

**Recovery contract:** 6 unchanged

## Completed user workflow

Gate 11E-1d completes the accepted password-plus-passkey feature as one usable
browser workflow:

- password login detects an MFA account, invokes the browser's native WebAuthn
  assertion, and enters the vault only after the server issues a normal session;
- **Settings → Accounts & Access** lets every authenticated user register, list,
  rename, and remove their own passkeys without exposing public-key material;
- current-strength confirmation performs password reauthentication and, when MFA is
  enabled, a second native passkey ceremony before high-impact work;
- password replacement, including the forced temporary-password path, uses that same
  current-strength sequence; and
- credential metadata distinguishes synced/backed-up and single-device state and
  encourages two enrolled passkeys without requiring a separate recovery code.

The browser serializes only the standard WebAuthn public response required by the
API. It does not put a credential, challenge, assertion, password, pending-login
token, or session bearer in local/session storage.

## Policy and account invariants

The server and Administrator UI expose three persistent policy choices:

1. **Optional** — the migration and new-install default. Individual enrollment is an
   opt-in that makes password plus passkey mandatory for that account.
2. **Require Administrators** — available only when every enabled Administrator is
   enrolled.
3. **Require everyone** — available only when every enabled account is enrolled.

These are settings an Administrator may choose; neither required mode is enabled by
default. Policy changes require current-strength authentication. Required policy
also rejects a last-credential removal/reset and any create, enable, or role change
that would produce an enabled unenrolled target. Account and authenticator mutations
share a process lock around the SQLite decision to serialize policy/account
changes in the supported single API process.

This fail-closed behavior makes onboarding explicit. Under Require Administrators,
create a non-Administrator, let them replace the temporary password and enroll, then
promote them. Under Require Everyone, temporarily select Optional, onboard and enroll
the new enabled account, then restore Require Everyone.

## Live reset and recovery truth

An Administrator may reset passkey MFA only for another account and only after
current-strength confirmation. The operation atomically removes that account's
credentials and ceremonies, disables its MFA flag, revokes its active sessions, and
records bounded counts in audit. It does not change the password or clear an existing
temporary-password requirement. A required policy blocks reset until the operator
lowers the policy or otherwise makes the account non-targeted.

The existing schema-17 recovery boundary remains intact:

- raw restore retains registered public credentials, revokes every copied browser
  session, and consumes every pending ceremony before exposure;
- backup-first stopped-instance Administrator recovery removes the recovered
  account's factors, returns global policy to Optional, revokes every session, and
  cannot create a new bypass account; and
- `.mvault` v1 remains the frozen schema-12 logical content contract and excludes
  users, hashes, sessions, audit/recovery state, MFA flags, credentials, ceremonies,
  and policy.

The complete 313-test API matrix re-executed raw recovery, recovery-marker,
schema-17 corruption, historical contract, and portable archive cases. The new
policy audit shape was also inserted into the schema-17 raw fixture and accepted by
the current contract-6 validator.

## Security review

- All 106 routes are exhaustively classified: 102 require a session permission and
  health, password login, passkey-login completion, and scoped handoff redemption are
  the only non-session routes.
- Policy update and Administrator MFA reset require both Administrator permission
  and recent current-strength authentication.
- An MFA high-impact proof must match the current user, browser session, RP ID, and
  the request's exact configured Origin; an otherwise trusted alternate origin does
  not reuse the proof.
- Registration, authentication, reauthentication, policy, credential, and reset
  audit events remain secret-free. The canonical global policy target is explicit;
  request/response bodies and WebAuthn material are not audited.
- Required-policy blockers are computed from enabled accounts and credential
  ownership, not from browser claims. Password reset never removes a factor.
- Ceremony TTL, attempt, response-size, per-account pending-login, and credential
  count bounds from 11E-1b/1c remain enforced.

Accepted residual constraints are operational rather than silent bypasses: passkeys
need one stable HTTPS origin; changing it does not migrate credentials; local
throttling matches the supported single API process; there is no TOTP, recovery-code,
email, passwordless, API-key, or OIDC fallback. If no Administrator retains a usable
factor, recovery requires a stopped instance and exact verified pre-change backup.

## Verification

```text
API collection: 313 tests
Complete API gate, split only for command-time bounds:
103 passed + 48 passed + 40 passed + 122 passed = 313 passed

Final policy/reset/authorization/passkey revalidation after strengthening
live-session revocation and role-denial assertions: 20 passed

Web gate:
typecheck passed; 32 tests in 11 files passed; production build passed

Real-browser passkey drill:
Chromium 151 virtual authenticator; registration, password-plus-passkey
current-strength confirmation, Require Administrators policy, logout, and fresh
password-plus-passkey login all passed; exactly one credential observed

Slicer bridge gate (pinned Go 1.26.6 container):
tests passed; executable build passed

Deployment gate:
development/production/compatibility/smoke/benchmark Compose configs passed;
production Compose rejected missing authentication secrets;
fresh container smoke passed with non-root API/web processes and schema 17

Release identity/publication contract, shell and JavaScript syntax,
and git diff --check passed
```

`make verify-passkeys` is now part of `make verify` and the container CI job. The
drill installs the locked browser dependencies in a disposable container and runs
in a disposable Compose project with project-scoped volumes;
cleanup removes its containers, network, and volumes. No live installation, public
repository, image registry, release, or external account was changed.

This drill validates Chromium and the real WebAuthn verifier with a virtual
authenticator. Physical security keys, platform credential prompts, and Firefox/
WebKit passkey ceremonies were not exercised here and remain final release
qualification work. Existing build warnings about bundle size and browser-data
freshness remain unchanged.

Documentation now distinguishes the frozen Gate 5 candidate (`f6ff55b`, schema 5)
from this later local schema-17 development. Gate 11E evidence does not qualify a
replacement release candidate.

## Owner checkpoint

Accepting this evidence closes Gate 11E-1. Gate 12 may then open only as its own
architecture checkpoint. TOTP, passwordless login, recovery codes, API keys,
OIDC/SSO, hosted tenancy, object storage, print monitoring, push, tag, release,
deployment, and publication remain outside this closeout.
