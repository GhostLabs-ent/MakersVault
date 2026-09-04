# Gate 11E-1c results — password-first passkey login

**Date:** 2026-09-04

**Status:** Complete; pending owner acceptance

**Entry commit:** `e422e9e`

**Schema:** 17 unchanged

**Recovery contract:** 6 unchanged

## Implemented boundary

Gate 11E-1c activates the accepted second-factor login and general
recent-authentication boundary without adding browser UI or policy/reset workflows:

- valid password authentication for an MFA-enabled account creates a five-minute
  pending login transaction and no browser session;
- the raw transaction token exists only in a separate HttpOnly, SameSite Strict,
  path-root cookie, using a production `__Host-` Secure name and a distinct local
  HTTP development/test name;
- only a keyed transaction digest and keyed WebAuthn challenge digest are stored;
- assertion options are restricted to the account's registered credentials and
  require user verification;
- exact configured Origin, RP ID, challenge, account-owned credential, signature,
  counter, enabled-account state, and MFA state are rechecked before completion;
- successful completion consumes the pending transaction and updates public
  authenticator state before a fresh ordinary protected-cookie session is issued;
- replay, expiry, absent or replaced transaction cookies, malformed responses,
  wrong challenges, foreign credentials, failed verification, and wrong origins
  create no session and return bounded generic login failures; and
- non-MFA accounts retain the established password-login behavior.

Password success no longer advances `last_login_at` until all required factors have
completed. Existing browser sessions presented during a new MFA attempt remain
untouched until successful completion, when normal login rotation revokes the
presented session and creates a fresh one.

## Abuse and state bounds

Each pending transaction allows at most five persisted verification attempts and an
account retains at most ten unconsumed authentication transactions. Expired state is
cleaned in bounded batches while a consumed reauthentication proof remains available
for its full five-minute recent-authentication window.

The existing process-local login limiter protects password attempts by source and
normalized username and passkey completion attempts by source. Its exponential delay,
bounded state, and `Retry-After` behavior remain unchanged. Oversized ceremony
responses retain an explicit resource-limit response; other invalid completion states
use the same `Invalid or expired login` result without revealing account, credential,
challenge, or verifier detail.

## Recent-authentication truth

For a non-MFA account, a recent password continues to satisfy high-impact route
policy. For an MFA-enabled account, those routes now require both:

1. password confirmation on the active browser session within five minutes; and
2. a consumed UV-required reauthentication ceremony bound to that same user, browser
   session, RP ID, and origin within five minutes.

The passkey reauthentication options route remains reachable after password
confirmation rather than circularly requiring a passkey proof to request one. Both
reauthentication ceremony endpoints are also in the narrow forced-password-change
allowlist, preventing an MFA account with a temporary password from being locked out
of the required password replacement path.

## Audit and privacy truth

The added stable actions are `passkey.authentication.begin`,
`passkey.authentication.complete`, and the final HTTP outcome
`identity.login.passkey`. Successful factor-state mutations retain their user target;
HTTP denial outcomes remain covered by the outcome-aware middleware. No raw pending
token, credential ID, public key, challenge, assertion, authenticator/client data,
password, cookie, or response body is written to audit details or security logs.

## Verification

```text
Focused login/session/authorization/audit/passkey matrix:
37 passed

Complete API gate (Python 3.11 container, split only for command-time bounds):
103 passed + 207 passed = 310 passed

Web regression gate:
typecheck passed; 29 tests in 10 files passed; production build passed

Bridge regression gate (pinned Go 1.26.6 container):
tests passed; executable build passed

Deployment contracts:
development and production Compose config passed;
production Compose rejected missing authentication secrets
```

## Deliberate sequential boundary

Gate 11E-1c is not independently releaseable or deployable. The API now enforces an
enrolled factor, while the current browser does not yet implement WebAuthn login or
settings ceremonies. Gate 11E-1d must add those browser workflows, safe policy
administration, explicit live Administrator MFA reset, real-browser ceremony
coverage, raw-backup revalidation, final security/recovery review, and consolidated
closeout evidence before this feature can be considered for rollout.

TOTP, passwordless login, API keys, OIDC/SSO, hosted tenancy, push, tag, release,
deployment, and publication remain unauthorized.

## Owner checkpoint

Please accept or amend Gate 11E-1c. Acceptance would authorize planning the next
bounded 11E-1d slice only; it would not authorize publication or deployment.
