# Gate 11C — shared-vault authorization results

**Date:** 2026-09-02

**Status:** Implemented and verified locally; owner acceptance pending

**Scope:** Three fixed shared-vault roles, stable permissions, deny-by-default HTTP
and system-service classification, capability-aware UI, schema/portability updates,
and focused evidence only

## Outcome

Gate 11C adds an explicit authorization layer without introducing private objects,
tenants, per-object ACLs, or additional-account administration. Every existing
identity is migrated to Administrator because it previously held unrestricted
authority; the schema default for any future identity is Viewer. A session resolves
the identity's current persisted role on every request rather than trusting a role
snapshot stored in the browser session.

Implementation commit:

- `8b89bab` — schema 15 roles, permission enforcement, exhaustive route and system
  service inventories, capability-aware browser behavior, and recovery/release
  contract updates

## Regression-first evidence

The focused API and browser suites were added before their implementation modules.
Collection failed as intended because `authorization` and `capabilities` did not
exist. After implementation and the active-Machine/system-service refinements:

```text
Gate 11C authorization focus: 9 passed in 4.79s
Complete API suite: 268 passed in 94.29s (0:01:34)
Complete web suite: 10 files, 29 tests passed; typecheck and production build passed
```

## Role and permission truth

The server owns stable permission names; the browser capability map mirrors them
only to present an appropriate interface.

| Capability | Viewer | Member | Administrator |
|---|---:|---:|---:|
| Read active shared-vault metadata | yes | yes | yes |
| Download, export, exact-file handoff | yes | yes | yes |
| Upload/import and manage content metadata, revisions, files, folders, Projects, relationships, and Machines | no | yes | yes |
| Read and restore recoverable Trash | no | yes | yes |
| Permanently delete or empty Trash | no | no | yes |
| Manage server settings and durable jobs | no | no | yes |
| Inspect/revoke own browser sessions | yes | yes | yes |

The permission identifiers are `vault.read`, `content.download`, `content.export`,
`handoff.create`, `content.manage`, `trash.read`, `trash.restore`,
`content.delete_permanently`, `trash.empty`, `settings.manage`, `jobs.manage`, and
`session.manage_self`. Unknown or malformed roles fail closed.

Viewer reads exclude deleted Projects/Artifacts, Trash, and archived Machine
profiles. A manually supplied `include_archived=true` cannot bypass that server
boundary. Member can use recoverable lifecycle operations but cannot access server
settings, durable jobs, permanent deletion, or Trash emptying. Administrator retains
the previously unrestricted behavior.

## Deny-by-default entry-point truth

- The inventory classifies all 88 application routes. Eighty-five require a valid
  browser session and exactly one stable permission.
- The only non-session routes are `GET /health`, `POST /login`, and the separately
  scoped `GET /handoff/redeem`. FastAPI documentation/schema routes are disabled.
- Application startup validates the live FastAPI route table against the exact
  inventory. A missing rule, stale rule, duplicate route, framework-generated
  route, absent session authorizer, or authorizer on a non-session route stops
  startup.
- Unsafe requests validate Origin and session-bound CSRF before role authority.
  UI visibility is never the enforcement boundary.
- Eight startup/background entry points are represented by a closed `SystemService`
  enum and must pass through the fail-closed dispatcher before execution. They cover
  session cleanup, Trash maintenance, mount-scan recovery/startup, content-identity
  recovery/startup, thumbnail backfill, and prepared-metadata backfill.
- MakersVault remains a single API process. User-triggered Python service helpers
  are not separately reachable endpoints: their external entry is one of the
  permission-checked HTTP routes above. The system dispatcher covers work entered
  independently by application startup rather than by a user request.

Inventory tests prove exact route coverage, the three non-session exceptions, one
authorizer per protected route, complete system-service enum coverage, and rejection
of an unclassified route or system service.

## Browser capability truth

- Login and session status carry the current role and server permission list. The
  React capability provider derives display capabilities from the fixed role.
- Viewer keeps browse, preview, download/export, local handoff, browser-session, and
  client-local appearance/network/slicer preferences. Mutation controls, Trash, and
  privileged server settings/jobs are absent.
- Viewer preview rendering does not send an Artifact ID to preview workers, so it
  cannot persist thumbnails or preview state as a side effect.
- Member receives content, Project, Machine, import, and recoverable Trash controls.
  Administrator alone receives storage/mount configuration, retention configuration,
  durable content jobs, permanent deletion, and Empty Trash.
- Machine descriptive context remains readable, but archived-profile retrieval is
  suppressed for Viewer in both UI and server behavior.

## Migration, ownership, and portability

- Additive migration 15 adds a checked/indexed `useraccount.role`. It backfills all
  schema-14 identities to Administrator without changing identity fields, content
  records, paths, or bytes, and is idempotent.
- The fixed role constraint accepts only `administrator`, `member`, or `viewer`.
  Future rows default to Viewer.
- All content remains installation-shared. Role or later creator/actor provenance
  does not confer ownership; Gate 11C adds no tenant ID, private object, user-Project
  membership, ACL, or sharing link.
- Raw schema-15 backup contains the persisted role and must remain protected.
  `.mvault` v1 accepts schema 12–15 sources while still excluding users, roles,
  hashes, sessions, credentials, and audit state; its clean importer continues to
  reconstruct the frozen schema-12 content contract.
- Automatic browser-session revocation after raw restore remains Gate 11D work. A
  schema-15 raw restore stays isolated until sessions are revoked and verified.

## Repository verification

The final clean repository gate passed on 2026-09-02:

```text
make verify: passed
API: 268 passed in 94.29s (0:01:34)
Web: 10 files, 29 tests passed; typecheck and production build passed
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed (direct and same-origin cookie sessions, logout revocation,
security headers, 512 MiB policy, non-root API/web UIDs, schema 15)
Release contract: verified for v5.1.0
```

`git diff --check` also passed. The run used local test containers only.

No image was pushed, no deployment was changed, and no tag, release, or publication
was made.

## Gate boundary

Gate 11C is at its owner checkpoint. Acceptance would freeze only the three-role
shared-vault authorization contract and authorize no further work by itself.
Additional-account administration, password/reset workflows, last-Administrator
safety, recovery, durable audit, MFA, API keys, OIDC, public registration, hosted
tenancy, push, release, deployment, and publication remain unauthorized. Do not
begin Gate 11D without an explicit owner decision.
