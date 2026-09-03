# Gate 11 Baseline — deliberate authentication evolution

**Gate:** 11 — Evolve authentication deliberately

**Status:** Subgate 11D-1 accepted; subgate 11D-2 verified locally and awaiting owner
acceptance

**Opened:** 2026-08-31

**Entry commit:** `b5f3fd2`

**Entry schema:** 12

**Entry identity model:** one environment-configured administrator

**Publication state:** Local only. Gate 11 does not authorize a push, tag, release,
deployment, public registration, hosted tenancy, identity-provider connection, or
publication.

## Entry condition

Gate 10 was accepted on 2026-08-31 with independently verifiable `.mvault` v1,
clean-instance reconstruction, a proven local `ContentStore`, and explicit raw and
portable recovery boundaries. Gate 11 may now design identity, sessions,
authorization, recovery, and auditing without changing those archive contracts
silently.

Opening Gate 11 first authorized this source audit, proposed ADR, and owner
checkpoint. On 2026-08-31 the owner accepted the package without amendment and
authorized 11A's additive schema 13, pinned password dependency, persistent first
administrator, and compatibility-login work only. Sessions, additional users,
permission enforcement, MFA, API keys, OIDC, and unrelated route changes remain
unauthorized.

The authorized implementation is complete at `0095f6e`; its transition, benchmark,
compatibility, and scope evidence is recorded in
[`SUBGATE_11A_RESULTS.md`](SUBGATE_11A_RESULTS.md).

The owner accepted 11A and authorized 11B on 2026-09-01. Gate 11B is limited to
revocable browser sessions, secure cookie/CSRF behavior, login migration, logout
and revocation, bounded expiry/cleanup, and focused evidence. Roles, permission
enforcement, additional accounts, administration, recovery, and audit remain gated.

The authorized implementation is complete at `5ca1a42`; its schema, cookie/CSRF,
revocation, browser migration, portability, and scope evidence is recorded in
[`SUBGATE_11B_RESULTS.md`](SUBGATE_11B_RESULTS.md). The owner accepted those
results and authorized 11C on 2026-09-01. Gate 11C is limited to the accepted
three shared-vault roles, stable server-side permissions, deny-by-default route
classification, enforcement, capability-aware UI, and focused evidence.
Additional-account administration, password/reset policy, last-admin safety,
recovery, durable audit, MFA, API keys, OIDC, and publication remain gated.

The authorized Gate 11C implementation is complete at `8b89bab`; its migration,
permission, route/system-entry inventory, UI, portability, and verification evidence
is recorded in [`SUBGATE_11C_RESULTS.md`](SUBGATE_11C_RESULTS.md). The owner
accepted those results and authorized 11D on 2026-09-02. Gate 11D is limited to
administrator-created accounts, password/reset and recent-reauthentication policy,
last-Administrator protection, stopped-instance recovery, durable secret-free
audit, raw-recovery session revocation, portability exclusion proof, and focused
evidence. MFA, API keys, OIDC, public registration, hosted tenancy, publication,
and unrelated work remain gated.

Gate 11D-1 is implemented at `cf8fcad` and locally verified in
[`SUBGATE_11D1_RESULTS.md`](SUBGATE_11D1_RESULTS.md). It adds schema-16 account
administration, forced password change, five-minute recent password confirmation,
affected-session revocation, and last-enabled-Administrator protection. The
schema-16 audit/recovery structures are reserved only: durable audit behavior and
stopped-instance/raw recovery remain Gate 11D-2 and 11D-3 work.

The owner authorized 11D-2 on 2026-09-03, accepting 11D-1's mandatory account and
recent-reauthentication boundaries. Gate 11D-2 is implemented at `3c0fa69` and
locally verified in [`SUBGATE_11D2_RESULTS.md`](SUBGATE_11D2_RESULTS.md). It
activates durable secret-free audit capture and Administrator-only cursor retrieval
without changing schema 16. Stopped-instance/raw recovery remains 11D-3 work.

## Verified entry truth

| Area | Current behavior | Gate 11 consequence |
|---|---|---|
| Administrator identity | `AUTH_USERNAME` and `AUTH_PASSWORD` define one process-wide administrator; the password is compared directly in constant time | Introduce a persistent identity without creating a second bypass login or locking out the existing owner |
| Configuration | Production startup rejects absent, published, short, or reused password/signing values | Preserve fail-closed first-run setup while separating bootstrap, session, and handoff secrets deliberately |
| Password storage | No password hash exists in SQLite because no `User` record exists | Benchmark and lock a memory-hard password-hash policy before accepting persisted credentials |
| Login throttling | A bounded source/username limiter applies exponential delay in process memory | Restarts and multiple workers erase or split state; persistent users need a durable and privacy-bounded abuse policy |
| Session token | Login creates a 12-hour HS256 JWT containing `sub`, `iat`, and `exp` | There is no server-side session, revocation, device list, absolute lifecycle, role snapshot, or logout invalidation |
| Refresh | Any still-valid administrator JWT can mint a fresh 12-hour JWT | A captured token can be extended repeatedly until it expires or the global signing secret changes |
| API principal | `require_auth` returns the token string (or `None` when auth is disabled) | Replace token-presence checks with a typed principal and explicit permission checks |
| Browser storage | The web stores the bearer in `sessionStorage`; some ordinary protected file URLs still accept it as a query parameter | Browser sessions must leave JavaScript storage and URLs; scoped 90-second handoff grants remain a separate exact-file contract |
| Authorization | Authenticated callers share unrestricted access to the global vault | Multiple logins cannot ship before deny-by-default permissions cover every route and file response |
| Domain ownership | Folder, Artifact, Revision, File, Project, relationship, and Machine records have no user or tenant owner | Decide shared-vault versus private ownership before adding columns; Project membership is content structure, not user authorization |
| Enrollment/recovery | There is no registration, invitation, password reset, email service, last-admin guard, or stopped-instance account recovery tool | Policy and offline recovery must be approved before persistent accounts can become the only login path |
| Audit | Security logs record login outcomes without passwords/tokens; no durable `AuditEvent` exists | Privileged identity and content actions need structured, secret-free, bounded audit evidence |
| Backup/portability | Raw format-1 backup contains SQLite and `.env`; `.mvault` v1 excludes secrets, sessions, and credentials | Define user/session/audit restore behavior without changing frozen `.mvault` v1 or making it an identity archive |

The application surface includes reads, downloads, uploads, remote and ZIP import,
revision and file mutation, Trash and permanent deletion, folders, Projects,
relationships, Machines, mount scans, storage reorganization, content hashing, and
local application handoff. With narrow exceptions for health, login, and exact-file
handoff redemption, these routes currently depend on the same boolean
authentication check. Authorization cannot be inferred from UI visibility.

## Threat and product boundary

The proposed target is one self-hosted MakersVault installation used by a household,
club, classroom, or workshop. Users share one vault; this gate is not cloud
multi-tenancy. It must protect administration and destructive operations from
ordinary users while keeping the existing content model usable.

Per-user private libraries, tenant IDs, object ACLs, public links, anonymous access,
cross-vault sharing, email delivery, billing, and hosted customer isolation are not
implicit consequences of adding accounts. Each would change the data and threat
model materially.

## Proposed Gate 11 contract

### 11A — persistent identity and safe bootstrap

1. Add an additive next-schema `User` identity with stable ID, unique normalized
   username, display name, memory-hard password hash, enabled state, and timestamps.
2. Use Argon2id through a pinned library and store its self-describing encoded hash.
   Benchmark a bounded production parameter set and retain algorithm/parameter
   upgrade-on-login capability.
3. Accept long passphrases and Unicode, require at least 15 characters for a
   password used as the only factor, reject known-compromised choices through a
   local bounded policy, impose no composition rule, and require changes only for
   compromise or an administrative reset.
4. Schema migration creates structures only. On the first start with no users, a
   valid existing environment administrator is transactionally converted into the
   first persistent administrator. Once that succeeds, the environment password is
   no longer a normal authentication path and must not become a permanent bypass.
5. Do not enable additional accounts or change route authority in 11A. Prove the
   current owner can log in before retiring compatibility behavior.

### 11B — revocable browser sessions

1. Replace self-contained administrator login tokens with cryptographically random,
   opaque session secrets; store only a keyed digest plus user, creation, activity,
   absolute expiry, revocation, and bounded client metadata.
2. Use a production `__Host-` session cookie with `Secure`, `HttpOnly`,
   `SameSite=Lax`, no `Domain`, and `Path=/`; put no token in URLs or browser
   storage. Development-only HTTP behavior must use an explicit separate contract
   and cannot weaken production defaults.
3. Protect unsafe cookie-authenticated requests with strict Origin validation and a
   server-bound CSRF token/header contract. CORS is not authorization.
4. Rotate the session on login, password change, privilege change, and recovery;
   implement server-side logout, per-session revocation, revoke-all, idle timeout,
   absolute timeout, and bounded cleanup.
5. Keep Gate 8's separately signed, 90-second, exact-file handoff grant. A browser
   session never becomes a durable file URL or bridge credential.

### 11C — shared-vault roles and deny-by-default authorization

Use exactly three initial roles:

- **Administrator:** all member actions plus users, roles, authentication policy,
  mount/storage settings, durable jobs, audit access, permanent deletion, and Trash
  emptying.
- **Member:** read/download/export/handoff plus upload/import, metadata, revisions,
  supporting/prepared files, folders, Projects, relationships, Machines, and
  recoverable Trash/restore.
- **Viewer:** read active shared-vault metadata and bytes, download/export, and
  request an exact-file local handoff; no mutation or settings access.

Permissions are stable server-side names mapped from roles. Every HTTP and internal
service entry point declares a permission and fails closed. Health, login/bootstrap
ceremony, and scoped handoff redemption are the only intentionally non-session
routes. Route-inventory tests fail if a new route lacks an explicit public or
permission classification.

All library objects remain installation-shared. Actor/creator audit fields do not
become ownership ACLs. There is no private object, per-Project user membership, or
sharing link in this gate.

### 11D — administration, recovery, audit, and portability

1. Only an Administrator creates an account or resets another user's password.
   There is no public self-registration, email reset, or invitation link in the
   initial gate.
2. Prevent deletion, disabling, or demotion of the last enabled Administrator in
   the same transaction. Require recent password reauthentication for self-password,
   role, session-revocation, recovery, and other high-impact actions.
3. Provide an interactive stopped-instance recovery command that accepts secrets
   through a protected prompt, operates only on exact local targets, preserves a
   matched backup first, and records a recovery marker for audit at next startup.
   Environment credentials do not remain an online break-glass bypass.
4. Add append-oriented structured audit events for authentication, user/role/session
   administration, settings, imports, destructive actions, exports, and handoff
   grants. Record stable actor/action/object/result/correlation/time fields and
   bounded network context; never record passwords, hashes, session/grant secrets,
   MFA material, cookies, imported-site credentials, notes, or private file paths.
5. Raw format-1 recovery gains schema-aware user/role/session/audit integrity checks
   and revokes restored browser sessions before service exposure. Frozen `.mvault`
   v1 remains content portability: it includes no users, password hashes, sessions,
   MFA material, API keys, or audit trail; a clean restore bootstraps a new admin.

### 11E and later — stronger authenticators and integrations

MFA, API keys, and OIDC/SSO follow only after 11A–11D are accepted and recovered in
a drill. Each requires another owner checkpoint:

- prefer phishing-resistant WebAuthn/passkeys when the deployment-origin and
  recovery requirements are proven; TOTP requires encrypted secrets and hashed
  single-use recovery codes;
- API keys are separately scoped, prefixed, hashed, expiring/revocable credentials,
  never browser sessions under another name; and
- OIDC uses explicit issuer/audience/redirect/account-linking rules and never makes
  a first external login an Administrator automatically.

## Proposed evidence sequence

1. **11A:** schema, identity/bootstrap, Argon2id policy, compatibility login, and
   representative schema-12 migration.
2. **11B:** opaque sessions, cookies/CSRF, refresh removal, logout/revocation, and
   browser migration.
3. **11C:** three roles, centralized permissions, route inventory, and
   allow/deny tests for every resource class and file response.
4. **11D:** user administration, last-admin/recovery/audit, backup/restore,
   `.mvault` exclusion proof, security review, and Gate 11 closeout.
5. **11E+:** separately authorize MFA, API keys, and OIDC in that order or defer
   them explicitly to a later roadmap.

## Explicit exclusions

- No schema or implementation before owner approval of the checkpoint.
- No hosted/multi-tenant mode, organization/tenant table, private objects, object
  ACLs, public sharing links, guest access, or public registration.
- No email/SMS delivery or dependency on an external recovery service.
- No social login, OIDC discovery, LDAP, SAML, MFA secret, passkey, API key, or
  third-party identity connection in 11A–11D.
- No reuse of browser sessions as bridge, file-link, automation, or provider tokens.
- No weakening of Gate 1 host/origin/import/handoff controls or Gate 10 archive,
  encryption, provider, and clean-import boundaries.
- No push, tag, release, deployment, or publication.

## Compatibility and rollback

Migrations are additive and never rewrite Artifact, Revision, Project, Machine, or
stored-byte identity. The environment administrator remains available only through
the measured transition until persistent login succeeds; it is not a permanent
parallel authentication path. Code rollback never starts an older binary against a
newer schema. Operational rollback restores the matched schema-12 SQLite/storage and
configuration snapshot, with the Gate 11 recovery drill proving how sessions and
credentials behave.

## Owner checkpoint

The accepted decisions are collected in
[`OWNER_CHECKPOINT.md`](OWNER_CHECKPOINT.md). Approval authorizes 11A only. Every
later subgate remains separately gated by the preceding evidence.
