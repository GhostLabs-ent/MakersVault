# ADR 0019: Origin-bound passkey MFA

**Status:** Accepted

**Proposed:** 2026-09-04

**Accepted:** 2026-09-04

## Context

Gate 11 established persistent accounts, revocable browser sessions, fixed roles,
recent password confirmation, durable audit, and stopped-instance recovery. A second
factor can now improve account security without becoming the only recovery path.

MakersVault is self-hosted. Some installations use a stable HTTPS hostname; others
use localhost, LAN IP addresses, or changing mDNS names. WebAuthn credentials are
cryptographically scoped to a stable RP ID and secure origin. TOTP works across
changing origins but requires MakersVault to retain a decryptable symmetric secret
for every enrolled account and remains susceptible to OTP relay phishing.

## Proposed decision

Implement password-plus-WebAuthn MFA as the first stronger authenticator. Keep it
optional by default, require explicit stable RP/origin configuration, and leave
existing unconfigured/password-only installations unchanged. Do not implement TOTP,
passwordless login, API keys, or OIDC in this slice.

Use a maintained pinned WebAuthn verifier. Require user presence and user
verification and request no identifying attestation. Persist public credential state
only. Bind one-time, digest-only challenges to an account, purpose, origin, RP, and
session or pending-login transaction, then atomically consume them.

An enrolled account requires password and WebAuthn both for login and high-impact
recent reauthentication. Default policy is Optional. Administrator enforcement may
target Administrators or all users only after every affected enabled account is
enrolled. Users own enrollment; Administrators may perform an explicit audited reset
but cannot enroll a credential for another user.

Raw backup retains credential state and advances its recovery contract. Raw restore
revokes pending ceremonies as well as sessions. `.mvault` remains content-only and
excludes all authenticator state. Stopped-instance Administrator recovery removes the
recovered account's credentials so loss of authenticators cannot permanently lock
the final Administrator out.

## Invariants

- No full browser session exists before every required factor succeeds.
- An invalid/replayed/expired/wrong-origin/wrong-RP assertion creates no session.
- Private keys and biometric/device-unlock material never reach MakersVault.
- Audit and logs contain no credential ID, public key, challenge, assertion,
  authenticator/client data, attestation, or recovery material.
- Enabling policy, removing a last credential, and concurrent role/account changes
  cannot leave required enabled accounts unenrolled or remove the last viable
  Administrator recovery path.
- A deployment without a valid stable passkey origin stays password-only; stored
  required-MFA state with invalid RP configuration fails loudly rather than bypassing
  the factor.

## Alternatives considered

- **TOTP first:** broader support for changing LAN origins, but phishable manual OTPs,
  symmetric-secret encryption/key-rotation/backup duties, QR exposure, time drift,
  and recovery-code lifecycle.
- **Passkey-only/passwordless:** lower login friction but expands account discovery,
  resident-key, recovery, and migration behavior beyond the approved second-factor
  goal.
- **TOTP fallback beside passkeys:** improves availability but makes the relayed OTP
  path the effective lower security boundary and doubles recovery complexity.
- **Mandatory enrollment on upgrade:** would burden and potentially lock out existing
  self-hosted users before hostname and authenticator readiness are known.

## Consequences

Passkey MFA is phishing-resistant and avoids server-held private or shared factor
secrets, but it cannot work on arbitrary IP/mDNS HTTP origins. Operators who want it
must establish a stable HTTPS hostname. The schema, login state machine, recovery
contract, account UI, audit inventory, and dependency lock all grow. Existing users
remain unaffected until they opt in or an Administrator safely stages enforcement.

## Approval boundary

The owner accepted this ADR and the linked Gate 11E checkpoint on 2026-09-04.
Acceptance authorized 11E-1a only; registration, login, policy UI, API keys,
OIDC/SSO, TOTP, public registration, hosted tenancy, deployment, and publication
remain separately gated.
