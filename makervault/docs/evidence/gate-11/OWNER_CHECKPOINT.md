# Gate 11 Owner Checkpoint

**Status:** Accepted without amendment

**Prepared:** 2026-08-31

**Accepted:** 2026-08-31

The owner accepted this package without amendment and authorized subgate 11A only.

## Recommended decision package

1. **One shared self-hosted vault**
   - Multiple people may have identities, but active library content is shared
     installation-wide.
   - Do not add tenant IDs, private objects, per-Project user membership, ACLs,
     hosted-customer isolation, or public sharing in Gate 11.

2. **Three roles with explicit permissions**
   - Administrator manages users, authentication, settings, durable operations,
     audit, permanent deletion, and every Member capability.
   - Member performs ordinary library/project/machine creation and mutation,
     import, recoverable Trash, read, download, export, and exact-file handoff.
   - Viewer reads/downloads/exports active shared content and may use exact-file
     handoff, but cannot mutate it.
   - Server-side permission checks are deny-by-default and tested for every route;
     UI hiding is never enforcement.

3. **Administrator-created enrollment only**
   - No public registration, email invitation/reset, or anonymous/guest access.
   - Usernames are unique normalized identities; display names are not authority.
   - Only an Administrator creates/enables/disables accounts or resets another
     user's password.

4. **Safe migration of the existing owner**
   - Add identity structures without content ownership changes.
   - On an empty identity database, convert the valid configured administrator into
     the first persistent Administrator with Argon2id.
   - Retire the environment password as a normal login after proven conversion; do
     not retain an unaudited online break-glass bypass.

5. **Modern password policy**
   - Use a pinned, benchmarked Argon2id implementation and self-describing hashes.
   - For password-only login, require at least 15 characters, allow long Unicode
     passphrases and spaces, reject known-compromised choices locally, impose no
     composition rules, and do not force periodic changes absent compromise.

6. **Revocable server-side browser sessions**
   - Use high-entropy opaque secrets, store only keyed digests, and bind each to a
     durable Session record.
   - Deliver the browser secret only in a host-only HttpOnly SameSite cookie that is
     Secure in production; protect mutations with Origin and CSRF checks.
   - Support logout, per-session and all-session revocation, idle and absolute
     expiry, session rotation, and bounded cleanup. Remove administrator tokens from
     browser storage and URLs.

7. **Recovery without email or a bypass account**
   - Protect the last enabled Administrator transactionally.
   - Require recent password reauthentication for high-impact identity actions.
   - Provide an interactive, stopped-instance, backup-first local recovery command;
     make its use visible in the durable audit trail.

8. **Secret-free, useful audit records**
   - Persist actor/action/object/result/correlation/time and bounded source context
     for identity administration, important content mutations, settings, imports,
     exports, deletion, and handoff grants.
   - Never log credentials, password hashes, cookies/tokens, recovery/MFA material,
     notes, or private source paths.

9. **Preserve portability boundaries**
   - Raw matched backup/recovery includes and verifies identity and audit state, then
     revokes restored browser sessions before exposure.
   - Frozen `.mvault` v1 remains a content archive and excludes users, password
     hashes, sessions, MFA/API credentials, and audit. Its clean restore creates a
     new local administrator through bootstrap.

10. **Stage stronger authentication separately**
    - Approving this package authorizes 11A only.
    - Sessions, roles, administration/audit/recovery remain 11B–11D and require
      sequential evidence acceptance.
    - WebAuthn/passkeys or TOTP, scoped API keys, and OIDC/SSO remain 11E+ decisions;
      none is authorized by opening Gate 11.

## Why this package

It adds useful household/workshop accounts without pretending authentication alone
creates isolation. A shared-vault decision avoids invasive ownership migrations,
while explicit roles protect settings and irreversible actions. Opaque sessions
make logout and revocation real, Argon2id removes plaintext environment passwords
from routine authentication, and stopped-instance recovery fits a self-hosted
product with no assumed email provider.

The session and authorization recommendations follow current guidance to keep
session identifiers out of URLs, prefer protected cookies, validate authorization
on every request, deny by default, and use memory-hard password hashing. The
architecture sources are NIST SP 800-63B, OWASP's Authentication, Session
Management, and Authorization Cheat Sheets, and RFC 9106; implementation evidence,
not the citation alone, remains the gate.

Primary references:

- [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [RFC 9106 — Argon2](https://www.rfc-editor.org/info/rfc9106/)

## Material alternatives

- Private per-user libraries or tenant-scoped objects instead of one shared vault.
- Member self-registration or email invitations/resets.
- Two roles, a custom permission editor, or per-object ACLs instead of three fixed
  roles.
- Persistent JWTs in browser storage instead of opaque revocable sessions.
- Retaining `AUTH_PASSWORD` as a permanent online recovery bypass.
- Shipping TOTP, passkeys, API keys, or OIDC before core authorization and recovery.
- Including password/session/authentication state inside `.mvault` v1.

Any of these changes the threat model, migration, recovery, or archive contract and
must amend the proposed ADR before schema work.

## What approval authorizes

Approval accepts proposed ADR 0018 and authorizes subgate 11A only: an additive
identity schema, safe one-time administrator conversion, Argon2id password policy,
compatibility login evidence, and focused migration/security tests. It does not
authorize multiple active users, role enforcement, session cookies, MFA, API keys,
OIDC, public registration, hosted tenancy, push, release, deployment, or publication.

## Owner decision

Accepted without amendment on 2026-08-31. ADR 0018 is accepted and subgate 11A is
authorized. Multiple active users, roles/permission enforcement, cookie sessions,
administration/audit/recovery, MFA, API keys, OIDC, public registration, hosted
tenancy, push, release, deployment, and publication remain unauthorized.
