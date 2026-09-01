# ADR 0018: Shared-vault identity and authorization

**Status:** Accepted

**Proposed:** 2026-08-31

**Accepted:** 2026-08-31

## Context

MakersVault currently authenticates one environment-configured administrator with a
12-hour self-contained bearer token. The dependency establishes only that a token
is valid; it returns no stable principal, role, permission, or revocable session.
Every authenticated caller has the same authority over one global vault. Domain
records contain no user/tenant owner, and Project membership relates content rather
than people.

Adding more usernames to this mechanism would create several indistinguishable
administrators, not multi-user security. Adding ownership columns without first
choosing shared versus private semantics would force a high-risk migration across
Folders, Artifacts, Revisions, Files, Projects, relationships, Machines, Trash,
downloads, exports, imports, handoffs, and recovery.

## Decision

Treat one installation as one shared vault. Add persistent users and exactly three
initial roles—Administrator, Member, and Viewer—mapped to stable server-side
permissions. Do not add tenants, private objects, object ACLs, or public sharing.

Introduce the architecture sequentially:

1. persistent identity and Argon2id password hashing with one-time conversion of the
   existing configured administrator;
2. opaque, durable, revocable browser sessions carried in protected host-only
   cookies with Origin/CSRF enforcement;
3. a typed principal and deny-by-default permission requirement on every route and
   internal service entry point; and
4. administrator-created enrollment, last-admin protection, stopped-instance local
   recovery, secret-free audit, and matched recovery verification.

Environment credentials bootstrap an identity database only when it has no users.
They are retired as a normal login after successful conversion and never form a
permanent unaudited bypass. Public registration and email recovery do not ship.

Viewer may read/download/export active shared content and request an exact-file
handoff. Member additionally manages ordinary content and recoverable Trash.
Administrator additionally manages identity/authentication, settings, durable
operations, audit, permanent deletion, and Trash emptying. Permissions, not role
names or UI visibility, are enforcement inputs.

MFA, API keys, and OIDC/SSO are later, separately approved stages. Browser sessions
are never reused as file-link, bridge, automation, or provider credentials.

## Invariants

- Authentication returns a typed active principal or fails; authorization is
  checked server-side on every protected request and defaults to deny.
- A new route must be classified explicitly as public, session-authenticated with a
  permission, or scoped-token redemption.
- The last enabled Administrator cannot be deleted, disabled, or demoted.
- Passwords, hashes, browser/session/grant secrets, MFA/recovery material, cookies,
  and imported-site credentials never enter logs or `.mvault`.
- Domain creator/actor provenance is not an ownership ACL.
- Gate 8 exact-file handoff grants remain separately scoped and short lived.
- Raw recovery and clean portable restore both have explicit, tested authentication
  outcomes; restoring a raw snapshot cannot silently reactivate old browser sessions.

## Alternatives considered

- **Every user is an administrator:** simple authentication, but no authorization
  boundary and explicitly unsafe for destructive/settings operations.
- **Private per-user libraries:** potentially useful, but changes nearly every query,
  export, relationship, migration, and recovery invariant.
- **Tenant plus ACL framework now:** supports hosted use but multiplies the threat and
  testing surface before a hosted product is authorized.
- **Stateless JWT plus a denylist:** retains token exposure in JavaScript/URLs and
  recreates server-side session state less directly.
- **Permanent environment break-glass login:** easy recovery but bypasses account
  disablement, revocation, MFA, rate limiting, and audit.
- **Public registration/email reset:** requires delivery, abuse, disclosure, and
  account-recovery infrastructure that the self-hosted product does not have.

## Consequences

The schema grows identity, session, and audit records, but existing content receives
no owner backfill. Shared-vault authorization is simpler to explain and test, while
fixed roles can evolve through stable permissions. Cookie authentication requires a
real CSRF/origin contract and production HTTPS. Persistent sessions require cleanup,
revocation, backup, and restore behavior rather than token-only decoding.

## Migration and rollback

The identity migration is additive and creates no user until the bootstrap
transaction validates the existing configuration and empty identity state. The
transition retains a proven login path until persistent authentication succeeds,
then removes environment-password authentication. No older binary may run against a
newer schema. Operational rollback restores the matched pre-Gate-11 schema-12
database, managed storage, and configuration. Later raw recovery must revoke restored
sessions before exposure; `.mvault` clean restore bootstraps a new local admin.

## Superseding conditions

Private objects, multiple tenants, hosted customers, external identity as the only
login, or custom roles require a new ADR and migration/recovery model. Owner approval
of the Gate 11 checkpoint is required before this ADR is superseded.
