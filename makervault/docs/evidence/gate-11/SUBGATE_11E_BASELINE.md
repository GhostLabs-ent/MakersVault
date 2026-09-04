# Gate 11E baseline — stronger authentication

**Date:** 2026-09-04

**Status:** Accepted design; 11E-1a complete and owner-accepted

**Entry commit:** `a85048b`

**Entry schema:** 16

**Authorization:** The owner accepted 11D-3 and authorized Gate 11E on 2026-09-03,
then accepted this design and ADR 0019 without amendment on 2026-09-04. That decision
authorized 11E-1a only.

## Verified entry truth

- Every account has a password. A password login immediately creates a full browser
  session; there is no pending-authentication state or second factor.
- Existing accounts and deployments must keep working without enrollment work.
- Production already requires Secure cookies over HTTPS, but direct trusted-LAN IP
  or mDNS HTTP remains supported as a weaker posture. `PUBLIC_URL` is optional and
  multiple explicit browser origins may be configured.
- Password reset and stopped-instance recovery revoke sessions but do not yet own
  authenticator records. `.mvault` v1 explicitly excludes future MFA material.
- Raw recovery contract 5 validates schema-16 identity/session/audit/recovery state.
- The API dependency set has no WebAuthn, CBOR, ASN.1, or general cryptography
  package. A maintained verifier must be pinned and audited; MakersVault must not
  implement WebAuthn cryptography itself.

The accepted pinned verifier is [`webauthn` 3.0.0](https://pypi.org/project/webauthn/)
(BSD-3-Clause, Python 3.10+). Its published dependency surface adds `cryptography`, `pyOpenSSL`, `cbor2`,
`pyasn1`, and `pyasn1-modules`; 11E-1a must resolve and pin the complete transitive
set. The vulnerability/license and image-impact evidence is recorded in the 11E-1a
results.

## Standards constraints

WebAuthn credentials are scoped to a Relying Party ID and usable only from allowed
secure origins. The RP ID is a domain string fixed for the credential lifetime; the
origin must normally be HTTPS, with `http://localhost` as the development exception.
This makes a stable hostname an actual authentication invariant, not UI metadata.
See the [W3C WebAuthn Level 3 specification](https://www.w3.org/TR/webauthn-3/).

NIST recognizes properly configured syncable authenticators as phishing-resistant
and replay-resistant, while manually entered OTP values are not phishing-resistant.
See [NIST SP 800-63B-4 authenticator guidance](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/).

TOTP requires the prover and server to share a unique symmetric secret and synchronized
time. That creates encryption-key custody, backup/restore, QR exposure, rotation, and
recovery-code obligations that MakersVault does not currently have. See
[RFC 6238](https://www.rfc-editor.org/info/rfc6238/).

## Recommended 11E contract

### 11E-1 — passkey-backed MFA, not passwordless login

1. Keep username and password as the first factor. An account that enables MFA must
   complete a WebAuthn assertion before a browser session is created. Do not add
   username-less, passkey-only, or public account discovery in this slice.
2. Use a maintained pinned server verifier; do not implement CBOR, authenticator-data,
   attestation, COSE-key, or signature validation locally. Evaluate the current
   `webauthn` package and its complete dependency/license/update impact before lock-in.
3. Require user presence and user verification. Request no identifying attestation
   (`none`). Support platform, roaming, and syncable authenticators without treating
   a device brand, display name, or attestation as account authority.
4. Require an explicit stable WebAuthn origin and RP ID. Production accepts HTTPS
   domain origins only; development accepts `http://localhost`. IP-address and mDNS
   deployments remain password-only until the operator supplies a stable supported
   hostname. RP ID never includes a scheme or port; every accepted web origin still
   includes its exact scheme, host, and effective port.
5. Store only credential ID, credential public key, user owner, sign counter,
   transports, backup flags, a bounded user label, and created/last-used timestamps.
   Store no biometric data, device unlock secret, private key, attestation certificate,
   challenge, or credential material in logs/audit/portable exports.

### Ceremony and replay boundaries

1. Registration requires an active eligible account and recent authentication at
   that account's current strength: password before first enrollment, then password
   plus an existing passkey after MFA is enabled. It is never an Administrator-
   created credential for another person.
2. One-time registration/authentication challenges expire within five minutes, are
   bound to purpose, account, session or pending-login transaction, RP ID, and origin,
   and are atomically consumed. Persist only a digest; recover the presented challenge
   from signed client data for comparison and verifier input.
3. Password-first login creates a short-lived pending transaction, not a browser
   session. Bind it with a separate host-only HttpOnly cookie; apply exact Origin,
   attempt limits, generic errors, and existing source/username throttling.
4. A valid assertion creates a fresh normal session. Invalid, expired, replayed,
   wrong-origin, wrong-RP, wrong-user, or wrong-credential assertions create none.
5. For an MFA-enabled account, high-impact recent reauthentication requires password
   and WebAuthn again. A password-only confirmation cannot silently lower assurance.

### Enrollment and Administrator policy

1. Default installation policy is **Optional**. Existing users and deployments have
   no enrollment task and no behavior change.
2. A user who completes first-passkey enrollment explicitly enables MFA for their
   own account; subsequent logins require it. Users may register multiple credentials
   and should be encouraged to keep two before relying on MFA.
3. Administrator policy may later select **Require Administrators** or **Require All**.
   A transition is rejected unless every enabled targeted account is already enrolled;
   changing policy requires recent MFA when the actor uses MFA and is audited.
4. An account may remove a credential only with recent MFA. Removing its last
   credential disables its opt-in only when no Administrator policy requires it.
   Never permit a policy/removal race to strand the last enabled Administrator.
5. Administrators may perform an explicit audited MFA reset for another account after
   recent reauthentication. They cannot view keys as secrets, register a credential
   for another user, or bypass the target's temporary-password workflow.

### Recovery, backup, and audit

1. Extend stopped-instance Administrator recovery to remove the recovered account's
   WebAuthn credentials and pending ceremonies, revoke all sessions, require password
   replacement, and emit the existing startup recovery marker. This guarantees a
   lost authenticator cannot permanently lock the vault.
2. Administrator MFA reset and password reset remain distinct explicit actions.
   Ordinary password reset does not silently delete credentials.
3. Advance raw recovery verification to the next contract for credential ownership,
   credential-ID uniqueness/shape, bounded public keys/transports/counters, policy
   satisfiability, and pending-ceremony expiry/ownership. Restored sessions and pending
   ceremonies are revoked; registered credentials remain usable only at the same RP.
4. `.mvault` v1 remains frozen and excludes credentials, public keys, MFA state,
   challenges, policy, and recovery data. Add real-record exclusion tests.
5. Audit enrollment, use outcome, removal, policy change, Administrator reset, and
   recovery using stable actions and canonical targets. Never store credential IDs,
   public keys, challenge/response payloads, authenticator data, client-data JSON,
   attestation, QR data, or recovery material.

## Deliberately deferred

- TOTP is not a fallback for passkey MFA. A weaker phishable fallback would define
  the effective security of the stronger path while adding symmetric-secret custody.
- Recovery codes are unnecessary in this slice because Members/Viewers have audited
  Administrator reset and the last Administrator has proven stopped-instance
  recovery. They can be reconsidered only with a separate storage/display contract.
- Passwordless/discoverable login, conditional mediation, attestation trust policy,
  device approval, and hardware-key mandates are deferred.
- API keys and OIDC/SSO remain separate post-11E owner checkpoints. No automation
  bearer is implemented as a browser session under another name.

## Proposed implementation slices after approval

1. **11E-1a:** dependency evaluation, schema 17 credentials/challenges/policy,
   migration and `.mvault` exclusion, contract-6 recovery design.
2. **11E-1b:** registration and self-management with recent-authentication and audit.
3. **11E-1c:** password-first pending login, assertion verification, session issuance,
   throttling, replay/origin/RP/UV tests, and MFA-aware recent authentication.
4. **11E-1d:** Settings/login UI, optional/admin policy workflow, recovery mutation,
   raw backup verification, browser tests, security review, and owner closeout.

## Owner checkpoint

Approval should decide all of the following together:

1. passkey/WebAuthn MFA first; no TOTP in 11E-1;
2. password plus passkey, not passwordless login;
3. Optional by default, with staged Administrator enforcement settings;
4. stable HTTPS hostname/RP configuration required for passkey use;
5. Administrator MFA reset plus stopped-instance recovery instead of recovery codes;
6. no API key, OIDC, public registration, hosted tenancy, push, or publication.

The owner accepted all six choices without amendment on 2026-09-04. 11E-1a results
are recorded in [`SUBGATE_11E1A_RESULTS.md`](SUBGATE_11E1A_RESULTS.md). Registration,
login, and account self-management remain outside this slice.
