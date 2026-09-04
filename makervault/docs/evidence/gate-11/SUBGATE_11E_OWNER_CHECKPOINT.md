# Gate 11E owner checkpoint — stronger authentication

**Date:** 2026-09-04

**Status:** Decision pending

**Proposal:** Implement password-plus-passkey MFA first, optional by default, with
safe staged Administrator enforcement. Do not implement TOTP, passwordless login,
API keys, or OIDC in this slice.

## Decision requested

Approve or amend these six linked choices:

1. WebAuthn/passkeys before TOTP because origin-bound public-key assertions resist
   phishing and require no server-held shared MFA secret.
2. Password remains the first factor; passkey is the second. No passwordless or
   username-less login in 11E-1.
3. Existing users remain password-only by default. First successful enrollment opts
   that account into MFA. Administrator settings may require Administrators or all
   users only after every targeted enabled account is enrolled.
4. Passkey use requires an explicit stable HTTPS origin and RP ID. Localhost HTTP is
   development-only. Arbitrary IP/mDNS HTTP remains password-only.
5. Members/Viewers recover through explicit audited Administrator MFA reset. The
   last Administrator recovers through the accepted backup-first stopped-instance
   command, which will clear that account's factor state. No recovery codes yet.
6. Raw backup advances to validate/recover the new state; `.mvault` v1 continues to
   exclude it. API keys, OIDC/SSO, TOTP, hosted tenancy, push, and publication remain
   unauthorized.

## Why this is the recommendation

- WebAuthn binds credentials to the RP rather than asking a person to recognize a
  phishing site or manually relay a code.
- The server stores a public key, not a TOTP seed that must remain decryptable.
- Optional-by-default enrollment avoids imposing work or lockout risk on current
  MakersVault users.
- The existing recent-authentication, last-Administrator, audit, raw recovery, and
  stopped-instance recovery controls supply the prerequisites that were absent when
  Gate 11 opened.
- Requiring stable HTTPS tells self-hosted users the real constraint instead of
  pretending passkeys can safely work on every legacy LAN URL.

Full design and implementation slices are in
[`SUBGATE_11E_BASELINE.md`](SUBGATE_11E_BASELINE.md), with the proposed durable
decision in [ADR 0019](../../adr/0019-origin-bound-passkey-mfa.md).

Approval authorizes 11E-1a only: dependency evaluation, schema/recovery design,
migration fixtures, and portability exclusion tests. Each later implementation
slice remains sequentially evidenced and accepted.
