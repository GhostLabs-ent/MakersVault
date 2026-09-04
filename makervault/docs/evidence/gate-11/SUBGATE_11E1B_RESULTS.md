# Gate 11E-1b results — passkey registration and self-management

**Date:** 2026-09-04

**Status:** Complete locally; owner acceptance pending

**Entry commit:** `c7caafd`

**Schema:** 17 unchanged

**Recovery contract:** 6 unchanged

## Implemented boundary

Gate 11E-1b activates the accepted schema-17 registration and account-management
surface without implementing password-first MFA login or browser UI:

- explicit `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, and optional RP-name configuration;
- exact production HTTPS origin/RP validation, with localhost HTTP limited to
  development/test and IP/mDNS RP IDs rejected;
- startup failure for malformed configuration or stored MFA-required state without a
  valid configuration, while an unconfigured Optional/password-only deployment stays
  unchanged;
- owner-only registration options and verification, credential listing and bounded
  rename, passkey reauthentication, and credential removal;
- first successful registration enables MFA for that account; multiple credentials
  are supported up to a bounded per-account maximum;
- password recency before first enrollment, then recent password plus an existing
  passkey for additional enrollment or removal;
- required-policy protection for the last credential and Optional-policy opt-out when
  the last credential is removed; and
- stable secret-free audit actions whose canonical target is the owning user.

No Administrator can enroll for another user. Public credential material is retained
only in the schema-17 credential table and is never returned by list/rename endpoints.
Passkey labels, timestamps, transport hints, sync/backup state, and opaque local row
IDs are the only credential-management output.

## Ceremony and assurance truth

Registration and reauthentication request user presence and user verification,
request attestation `none`, and allow platform, roaming, and syncable authenticators.
Server-generated 32-byte challenges expire after five minutes. Only their keyed
digests are stored, bound to purpose, account, current browser session, exact RP ID,
and exact origin.

Completion recovers the challenge from bounded `clientDataJSON`, invokes the pinned
`webauthn` verifier for origin/RP/challenge/UV/signature/authenticator validation, and
then rechecks live ownership, session, challenge, credential counter, policy, and
current-strength conditions under the mutation lock. A successful completion consumes
the challenge in the same transaction as credential/account/counter changes and the
audit event. Replay fails; invalid verification increments a persisted attempt count
to a maximum of five without returning verifier detail.

A consumed reauthentication ceremony is usable for five minutes only by its original
user, browser session, RP ID, and origin. Password-only recency never satisfies the
passkey half for an MFA-enabled account. A concurrent second “first enrollment” must
therefore obtain existing-passkey proof once the first completion has enabled MFA.

## Configuration and deployment truth

Both WebAuthn settings are optional together. Supplying only one, using an HTTP
production origin, using an unrelated origin host, or using an IP/mDNS RP ID fails
closed. RP/origin changes do not migrate credentials.

The variables pass through both canonical Compose manifests and are documented in
the environment example, configuration inventory, and secure-deployment guide.
`docker-deploy.yml` remains only the accepted include alias for the canonical
production manifest.

## Audit and privacy truth

The explicit actions are:

- `passkey.registration.begin`
- `passkey.registration.complete`
- `passkey.reauthentication.begin`
- `passkey.reauthentication.complete`
- `passkey.credential.rename`
- `passkey.credential.remove`

Audits use the user account as their canonical object. They contain no credential ID,
public key, raw challenge, client/authenticator data, assertion, attestation, response
body, or device identifier. Failed and denied HTTP outcomes remain covered by the
existing outcome-aware middleware; successful identity mutations write audit and
state atomically.

## Verification

```text
Focused Gate 11E-1b configuration/ceremony/self-management/API matrix:
6 passed

Complete API gate (Python 3.11 container):
308 passed in 135.40s

Web regression gate:
typecheck passed; 29 tests in 10 files passed; production build passed

Bridge regression gate (pinned Go container):
tests passed; executable build passed

Deployment contracts:
development and production Compose config passed;
production Compose rejected missing authentication secrets
```

## Deliberate sequential boundary

This slice is **not independently releaseable or deployable**. It sets
`mfa_enabled=1` after first enrollment, but the accepted password-first pending-login
transaction, assertion-before-session issuance, login throttling/replay matrix, and
MFA-aware general recent-authentication enforcement belong to 11E-1c. Releasing 1b
alone would leave password login unaware of the stored factor.

Gate 11E-1c is therefore the next required slice if the owner accepts 1b. Settings and
login UI, policy administration, live Administrator reset, browser ceremony tests,
raw-backup revalidation, final security review, and closeout remain 11E-1d. TOTP,
passwordless login, API keys, OIDC/SSO, hosted tenancy, push, tag, release, deployment,
and publication remain unauthorized.
