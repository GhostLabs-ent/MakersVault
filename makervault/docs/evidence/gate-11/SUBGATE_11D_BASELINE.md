# Gate 11D baseline — administration, audit, and recovery

**Date:** 2026-09-02

**Status:** Implementation authorized

**Progress:** 11D-1 and 11D-2 were owner-accepted through authorization of their
successors. 11D-3 is implemented at `3ed6991`, verified locally, and awaits owner
acceptance.

**Entry commit:** `f5eba6d`

**Entry schema:** 15

## Verified entry truth

- MakersVault has one persistent Administrator identity. The schema can represent
  all three accepted roles, but there is no account-list/create/update/reset API or
  browser workflow.
- `password_change_required` is persisted but is not an authorization state. There
  is no self-password workflow or recent-password confirmation timestamp.
- Role checks are current on every request, but a role/password/enablement change
  service does not yet exist and therefore cannot revoke affected sessions.
- Last-Administrator safety is not implemented. Account deletion is also absent.
- Security events exist only in process logs. There is no durable, queryable audit
  record or correlation identifier.
- Raw recovery contract 4 validates the content graph through schema 12. It reports
  the later schema number but does not inspect identities, roles, sessions, or audit
  records, and the restore script restarts copied browser sessions unchanged.
- `.mvault` v1 uses fixed content catalogs, already excludes identity/session data,
  and accepts schema 12–15 sources. Gate 11D must extend source compatibility and
  exclusion proof without changing archive format 1.
- The existing recovery module is standard-library-only and independently verifies
  stopped matched database/storage archives. The deployment scripts already stop
  API and web services for backup/restore, providing the correct trust boundary for
  an offline recovery ceremony.

## Implementation contract

### 11D-1 — accounts and recent reauthentication

1. Add additive schema 16 fields/tables only. Existing content records, paths, and
   bytes are unchanged.
2. Administrator may list, create, enable/disable, assign a fixed role, edit a
   display name, and set a temporary password for another account. There is no
   public registration, invitation, email reset, username rename, or account
   deletion. Disabled records remain as durable audit principals.
3. New and administrator-reset passwords set `password_change_required`. A signed-in
   user in that state may access only session status, logout, password confirmation,
   and self-password change until the requirement is cleared.
4. A successful password login starts a five-minute recent-authentication window.
   Password confirmation renews only the current session. Role, enablement,
   temporary-password reset, self-password change, individual/revoke-all session
   actions, permanent deletion, and Trash emptying require that window.
5. Password changes and administrator role/enablement/reset changes revoke affected
   sessions. A successful self-password change issues a fresh session; no browser
   bearer or recovery secret is exposed.
6. Disabling or demoting the last enabled Administrator fails in the same serialized
   database mutation. Account deletion is deliberately omitted, so it cannot bypass
   this invariant.

### 11D-2 — durable secret-free audit

1. Append structured events with server-generated ID/correlation/time, stable action,
   result, actor ID/name/role snapshot, bounded object type/ID, route template,
   permission, status, and bounded source address.
2. Never store request/response bodies, passwords or hashes, cookies/tokens, CSRF or
   handoff grants, recovery material, imported-site credentials, notes, raw URLs,
   query strings, filenames, or private filesystem paths.
3. Audit login outcomes; identity, role, password, and session administration;
   settings and durable jobs; imports and content mutations; exports; handoff grants
   and redemption; Trash/permanent deletion; and audit reads. Audit query is
   Administrator-only and paginated to at most 200 rows.
4. Existing domain mutations use a post-outcome append because their historical
   services commit independently. Audit-write failure is security-logged and returns
   failure where still possible; it is not falsely represented as an atomic domain
   rollback. Identity safety mutations write their event in the identity transaction.

### 11D-3 — stopped-instance and raw recovery

1. Advance new raw backups to recovery contract 5. Verify schema-16 identity roles,
   enabled-Administrator presence, session ownership/time/digest shape, recovery
   markers, and audit structure while retaining compatible re-audit of contracts
   2–4.
2. After exact raw restore verification and before service exposure, revoke every
   restored browser session and persist a recovery marker. Startup converts pending
   markers into durable audit events before accepting requests.
3. Provide an interactive stopped-instance administrator recovery command. It reads
   passwords only through a protected prompt, targets one exact regular SQLite file,
   proves an independently verified matched backup of that exact pre-change database,
   acquires the instance lock, resets/enables/promotes an existing account, revokes
   all sessions, and writes a startup marker. It does not create a bypass account.
4. The deployment wrapper creates the matched backup first and leaves services
   stopped on ambiguous or failed mutation. Recovery and raw restore never modify
   Artifact, Project, Machine, storage, or `.mvault` content.

## Explicit boundaries

- Shared-vault roles remain fixed; there is no custom permission editor or object
  ownership/ACL migration.
- No email/SMS service, public registration, deletion, anonymous access, MFA, API
  key, passkey, TOTP, OIDC/SSO, or permanent environment-password bypass.
- No secrets in audit or `.mvault`; no change to frozen `.mvault` format 1.
- No push, tag, release, deployment, or publication.

## Evidence sequence

1. Schema-15-to-16 migration and compatibility fixtures.
2. Account lifecycle, forced password change, reauthentication expiry, session
   rotation/revocation, last-Administrator race/safety, role allow/deny, and UI tests.
3. Audit coverage/redaction/pagination/failure and correlation tests.
4. Contract-5 identity/session/audit corruption matrix, raw-restore revocation,
   offline recovery backup/lock/prompt/marker tests, and `.mvault` exclusion proof.
5. Full repository verification, local implementation/evidence commits, then an
   owner checkpoint before any 11E work.
