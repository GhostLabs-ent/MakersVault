# Gate 11E-1a results — passkey foundation and recovery contract

**Date:** 2026-09-04

**Status:** Implemented and locally verified; owner acceptance pending

**Entry commit:** `c399e18`

**Schema:** additive 17

**Recovery contract:** 6 for newly created raw backups; contracts 2–5 remain
compatible only through current independent re-audit

## Accepted boundary

The owner accepted ADR 0019 and all six linked Gate 11E choices without amendment
on 2026-09-04. That decision authorized 11E-1a only: dependency evaluation,
schema/recovery design, migration compatibility, and real-record `.mvault` exclusion.
No registration, assertion, pending-login, account UI, or enforcement behavior is
exposed by this slice.

## Dependency decision

MakersVault now pins `webauthn==3.0.0` in both reproducible Python 3.11 lock sets.
The resolved new dependency surface is:

| Distribution | Pin | Declared license |
|---|---:|---|
| `webauthn` | 3.0.0 | BSD-3-Clause |
| `cbor2` | 6.1.4 | MIT |
| `cryptography` | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| `pyOpenSSL` | 26.4.0 | Apache-2.0 |
| `pyasn1` | 0.6.4 | BSD-2-Clause |
| `pyasn1-modules` | 0.4.2 | BSD |

`cffi==2.1.1`, `pycparser==3.0`, and `typing-extensions==4.16.0` were already in
the runtime lock and satisfy the new graph. A disposable Python 3.11 image running
`pip-audit==2.9.0` against the complete runtime lock reported no known
vulnerabilities on 2026-09-04.

The pre-change and post-change API test images measured 81,808,751 and 88,214,001
bytes respectively: a 6,405,250-byte (6.11 MiB, 7.83%) compressed image increase.
Installed-file accounting attributes about 20.6 MB before image-layer compression
to the six new distributions. This is accepted for maintained WebAuthn/CBOR/COSE and
signature verification rather than local cryptographic implementation.

## Schema 17 truth

- Existing accounts gain `mfa_enabled=0`; no upgraded user is required to enroll or
  experiences a login change.
- `webauthncredential` stores one account owner, bounded base64url credential ID and
  public key, non-negative sign counter, canonical transports, backup/device flags,
  bounded label, and created/last-used timestamps. Credential IDs are globally
  unique; private keys and biometric/device-unlock material have no server field.
- `webauthnchallenge` stores a digest only, exact purpose, account, either current
  session or pending-login transaction binding, RP ID, origin, five-minute maximum
  lifetime, bounded attempt count, and consumption time. Raw challenge bytes have no
  server field.
- `authenticatorpolicy` is a database-enforced singleton. Its initial mode is
  `optional`; later modes are `require_administrators` and `require_all`.
- Migration 17 is additive and idempotent. The schema-16 fixture retains account
  state, creates empty credential/challenge tables, and receives exactly one Optional
  policy row.

## Recovery and portability truth

Recovery contract 6 counts and independently validates schema-17 authenticator
tables, required columns, account/credential/challenge/session ownership, globally
unique and bounded credential/challenge identifiers, public-key/transports/counter
shape, five-minute ceremony lifetime and binding, exact HTTPS/localhost origin-to-RP
scope, singleton policy shape, and policy enrollment satisfiability.

Raw restore revokes all copied browser sessions and consumes every pending ceremony
before service exposure while retaining registered public credentials. Backup-first
stopped-instance Administrator recovery removes the recovered account's credentials
and ceremonies, disables its MFA flag, returns enforcement to Optional, revokes all
sessions, and records only bounded counts/booleans in the startup audit marker.
Historical schema-16 marker shapes remain readable after migration.

`.mvault` v1 now accepts schema 17 as a source but remains frozen at its schema-12
logical content contract. A real-record regression places an enabled account,
credential ID, public key, label, challenge and transaction digests, and required
policy in SQLite, then proves none appears in archive members or bytes.

## Verification

```text
Focused schema/dependency/portable/recovery matrix:
92 passed in 46.98s

Focused historical migration plus recovery-marker matrix:
11 passed in 10.44s

Complete API gate (Python 3.11 container):
302 passed in 127.43s

Dependency vulnerability scan:
No known vulnerabilities found

Final uninterrupted repository gate:
302 API tests; web typecheck/tests/build; bridge tests/build; Compose/security;
container smoke at schema 17; release contract — all passed
```

## Remaining boundary

11E-1a creates no usable passkey feature. Registration and self-management remain
11E-1b; password-first pending login and assertion verification remain 11E-1c; UI,
policy workflows, and final security/recovery closeout remain 11E-1d. TOTP,
passwordless login, API keys, OIDC/SSO, hosted tenancy, push, tag, release,
deployment, and publication remain unauthorized.

## Owner checkpoint

Accept 11E-1a before beginning 11E-1b registration and self-management. Acceptance
does not authorize login/assertion or UI work beyond the next bounded slice.
