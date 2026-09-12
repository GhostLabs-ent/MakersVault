# MakersVault Architecture and Delivery Runbook

**Status:** Governing working document

**Baseline date:** 2026-09-12

**Committed baseline:** `main` approved six-package native update at `6306ccf`, following runtime containment at `ea17494` and S01/S02 hardening at `ac4a051` (schema 17; Gate 13B accepted at `2f61b37`, 13C qualification open and not accepted)

**Latest full verification:** clean committed `6306ccf`;
[native-update evidence](evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md).
424 API tests, 58 reexecuted web tests, 25 Python / 28 Node harness tests,
HTTPS upgrade/recovery/rollback and exact-image containment pass. Actual API/Nginx
processes have empty capability sets and no-new-privileges. Dated language audits
are clean; the exact-image scan retains 189 API / 3 web matches. Subsequent
[vendor/byte reconciliation](evidence/gate-13/SECURITY_RECONCILIATION_RESULTS.md)
verifies 26 fixes without suppressing raw matches. The
[current E2/R52 proposal](evidence/gate-13/SECURITY_CURRENT_IMAGE_DECISION.md) remains
owner-pending, with an explicit BusyBox evidence gap and seven unaccepted holds.
These read-only reviews recheck durable evidence, not rerun the full gate. Earlier
browser results and WebKit synthetic-drop limits remain separately dated; G13-01
performance tuning stays deferred. Nothing is pushed or release-qualified.

**Bounded follow-up:** the owner authorized one final performance pass on 2026-09-10
and is content to carry remaining stalls/latency rather than prolong tuning.
`c42614e` avoids tracked ORM objects in the read-only folder list; all 354 API tests
pass. [Bounded-pass evidence](evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md)
retains remaining timing failures. Further performance tuning is deferred by that
owner decision, not relabeled a benchmark pass. No security/platform/release waiver.

**Immutable v5.1 source baseline:** `f6ff55b33fd64c7a5037e8eb642bed048c3e0e4f`

**Target:** v5.1 and the strategic roadmap that follows it

**Product promise:** **The self-hosted workspace for everything you make.**

## 1. Purpose

This is the execution runbook for turning the MakersVault strategy into working,
recoverable software. It governs the order of work, the evidence required to call
work complete, the decisions that require owner input, and the way the plan is
updated after each milestone.

It is intentionally founded on gates and truth:

- A roadmap item is not complete because code exists. It is complete when its
  behavior, migration, security, recovery, documentation, and evidence pass a
  defined gate.
- Current source and repeatable runtime evidence outrank an architectural wish.
- An assumption stays an assumption until it is tested or explicitly decided.
- A failed gate changes the plan; it is not explained away.
- After every accepted gate, MakersVault is re-baselined before the next gate is
  started.

This document is the operational companion to:

- [MakersVault_v5.1_Competitive_Strategy(1).md](MakersVault_v5.1_Competitive_Strategy(1).md)
- [PRODUCT_STRATEGY.md](PRODUCT_STRATEGY.md)
- [V5.1_SCOPE.md](V5.1_SCOPE.md)
- [ROADMAP.md](ROADMAP.md)
- [SUSTAINABILITY.md](SUSTAINABILITY.md)
- [MakersVault_v5.1_Security_Analysis.md](MakersVault_v5.1_Security_Analysis.md)

If those documents disagree about product intent, the product strategy and
explicit owner decision govern. If they disagree about current behavior, verified
source and runtime evidence govern. The disagreement must be recorded and the
stale document corrected at the active gate.

## 2. End state

The roadmap is satisfied when MakersVault is a trustworthy, self-hosted workshop
system of record in which a user can:

- Find and organize a large, mixed-discipline library without preview stalls.
- Understand what an item is, who created it, where it came from, and whether its
  content has changed.
- Keep primary files, visible supporting material, revisions, and useful
  fabrication context together.
- Group artifacts into projects and express a small set of useful relationships.
- Open supplied files in trusted local applications without MakersVault silently
  controlling a machine.
- Back up, verify, export, and restore the complete vault without a paid service.
- Operate the application with secure defaults and a documented upgrade path.
- Optionally buy operational convenience without losing the complete open-source,
  self-hosted product.

This is a directional end state, not permission to build every future subsystem
at once. Each capability remains behind its gate.

## 3. Non-negotiable product invariants

Every design and implementation gate must preserve these rules:

1. MakersVault does not slice models, send fabrication jobs, or start machines.
2. Prepared-print payloads remain internal. The user sees useful context such as
   `Prepared for Bambu Lab P1S · PLA · 0.4 mm · 3h 12m`, not a G-code browser.
3. Supporting documents remain visible and retrievable.
4. Users are not required to upload thumbnails. Preview extraction, bounded
   generation, caching, fallback, and failure handling belong to MakersVault.
5. Mounted no-copy libraries are never silently moved, renamed, or rewritten.
6. Duplicate detection may suggest; it does not silently merge or delete.
7. Original files and metadata remain portable without a subscription.
8. Local application integrations open supplied files; they do not create hidden
   machine-control authority.
9. No temporary `AssetGroup` layer is introduced. Evolution proceeds toward
   `Project -> Artifact -> Artifact Revision` when that architecture reaches its
   gate.
10. A difficult or hostile file must not make the rest of the library unusable.

A proposal that breaks an invariant stops until the owner changes the product
decision explicitly and the strategy documents are updated.

## 4. Truth protocol

### 4.1 Evidence order

When sources disagree, use this order:

1. Repeatable runtime result against the named build and data fixture.
2. Passing automated test that asserts the behavior directly.
3. Current executable source, migration, and deployment configuration.
4. Recorded architecture decision accepted by the owner.
5. Current product and release documents.
6. Issue, comment, recollection, or assumption.

Higher evidence does not make an unsafe design acceptable. It only establishes
what is true now.

### 4.2 Truth states

Every material claim used to approve work carries one of these states:

| State | Meaning |
|---|---|
| `VERIFIED` | Reproduced or directly proven in the named baseline. |
| `OBSERVED` | Seen once, but not yet protected by repeatable evidence. |
| `ASSUMED` | Needed for planning and not yet proven. Cannot satisfy a gate. |
| `PROPOSED` | A candidate design awaiting decision or evidence. |
| `DECIDED` | Explicitly accepted product or architecture direction. |
| `BLOCKED` | Cannot proceed safely without a dependency or owner decision. |
| `SUPERSEDED` | Was valid, but a newer accepted record replaced it. |

### 4.3 Required gate record

Every gate uses this record in its work log or pull request:

```text
Gate:
Status: PROPOSED | READY | IN PROGRESS | EVIDENCE REVIEW | ACCEPTED | REWORK
Baseline commit/image/database fixture:
Objective:
Verified entry conditions:
Assumptions to test:
Owner decisions required:
Files and data affected:
Migration and rollback plan:
Security and privacy impact:
Evidence produced:
Acceptance criteria result:
Documentation updated:
Residual risks and deferrals:
Accepted by/date:
Next-gate recommendation:
```

No gate may be marked `ACCEPTED` with an unlabelled assumption standing in for an
acceptance criterion.

## 5. Verified architecture baseline

This section records the starting truth for the runbook. It must be refreshed at
Gate 0 and after every accepted gate.

### 5.1 Baseline qualification

Commit `1231565642b8541a7ad36ba4ffdeb2da9527ef89` is the clean Gate 0 source
baseline. It preserves the authorized v5.1 UI, metadata, storage, preview, and
model-bundle work together with the Gate 0 safety foundation. Generated and
runtime artifacts are excluded from source ownership. The complete local
`make verify` target passed against this exact commit and left a clean working
tree. GitHub Actions run 31802094344 then passed all four verification jobs
against evidence closeout commit `63ade54cad7b1681cf2a33f62c0512d6d80bc45c`.

Gates 1–5 subsequently passed their named local evidence. Gate 5 qualified immutable
v5.1 source `f6ff55b33fd64c7a5037e8eb642bed048c3e0e4f`; owner acceptance is recorded at
`c004c60`. No tag, push, image, binary, or release is published. By owner decision,
post-v5.1 Gate 6 work proceeds after that immutable candidate in local history while
publication remains reserved for a coordinated rollout.

### 5.2 Current component map

```text
Browser
  React/TypeScript + bounded preview workers + native passkey ceremonies
                  |
                  | protected cookie session; exact-Origin/CSRF mutations
                  v
Static unprivileged Nginx -> FastAPI (one shared-vault API process)
  exhaustive route permissions + identity/session/passkey/audit services
  library/import + revision/Trash + Project/Machine + recovery services
           |                         |
           v                         v
SQLite schema 17             LocalContentStore + remaining filesystem seams
  identity/roles/audit          managed revision/supporting/prepared bytes
  Project <-> Artifact         thumbnails/quarantine; external no-copy references
                `-- revisions

Offline matched raw backup/restore: format 1, recovery contract 6
Offline .mvault v1: content-only export -> verified clean schema-12 import

Browser exact-file grant -> paired Go bridge -> configured local application
```

The target is a well-factored modular monolith, not a fleet of microservices.
Background work may run in a separate process later, but domain boundaries are to
be made explicit before deployment boundaries are multiplied.

### 5.3 Truth ledger

This is a cumulative gate history. Each row's evidence and consequence describe
its named gate; later accepted rows supersede earlier authorization checkpoints.
Use section 15 and the active Gate 13 record for current authority, not an older
row's future-tense wording.

| ID | State | Current truth | Primary evidence | Consequence |
|---|---|---|---|---|
| T-001 | `VERIFIED` | The API is Python 3.11, FastAPI, SQLModel, and SQLite by default. | `api/requirements.txt`, `api/db.py` | SQLite-safe migrations and recovery are release requirements. |
| T-002 | `VERIFIED` | The React/Vite client keeps card parsing, decompression, normal calculation, rendering, and LightBurn extraction in terminable workers behind one shared bounded queue; successful cards become persisted static thumbnails. | `web/src/lib/previewJobs.ts`, preview workers, Gate 2 candidate evidence | New preview formats must join the bounded queue and persistence contract rather than add main-thread card parsers. |
| T-003 | `VERIFIED` | Production web packaging is a static build served by unprivileged Nginx with runtime API configuration. | `web/Dockerfile`, `web/nginx.conf`, `web/40-runtime-config.sh` | The former production Vite-server finding is resolved in the Gate 0 baseline. |
| T-004 | `VERIFIED` | Production deployment separates `/app/data` and `/app/storage`; development layout differs. | Docker Compose files | Backup instructions must distinguish production and development. |
| T-005 | `VERIFIED` | Production Compose requires explicit credentials, and API startup independently rejects missing, published, short, or reused secrets. Development fixtures require an explicit non-production mode. | `api/security_config.py`, Compose manifests, Gate 1 slice 1A evidence | Authentication configuration is fail-closed; later Gate 1 slices still govern network, token, and bridge exposure. |
| T-006 | `SUPERSEDED` | At the original baseline, auth was one environment-configured administrator with 12-hour HS256 JWTs and no user, role, revocation, or MFA model. | Gate 11 source baseline | T-042–T-052 replace this historical boundary. |
| T-007 | `VERIFIED` | Some file handoffs place bearer material in URLs, including custom-protocol handoff. | API schemas/routes and bridge code | Replace broad reusable bearer URLs with narrow, short-lived grants. |
| T-008 | `VERIFIED` | The bridge accepts custom protocol input, downloads a URL, caches the result, and launches a local application. | `slicer-bridge` source | The bridge is a workstation trust boundary and needs protocol hardening. |
| T-009 | `VERIFIED` | Startup uses an ordered, immutable SQLite migration ledger at schema version 17, with dependency locking and fail-closed version/name checks. Schemas 6–12 add content/history/Trash/Projects/Machines; schemas 13–17 add persistent identity, sessions, roles, account/audit/recovery structures, and passkey state additively. | `api/migrations.py`, `api/db.py`, API migration tests | Larger model changes must extend this migration mechanism and retain old-database fixtures. |
| T-010 | `VERIFIED` | Metadata is split between SQLite and filesystem content; updates are not one atomic transaction. | API storage and asset services | File mutations require staging, compensation, and reconciliation. |
| T-011 | `VERIFIED` | Current records include `Folder`, `Asset`, `Project`, `ProjectMembership`, `ProjectRelationship`, `MachineProfile`, `ArtifactMachine`, immutable `ArtifactRevision`, scoped `AssetFile`, durable content jobs, `TrashPurgeOperation`, and `AppConfig`; several bounded journal/result structures are stored as JSON text. | `api/models.py`, Gate 6 evidence, Gate 7A/7C evidence, Gate 9A/9B evidence | Lifecycle/export work must build on these records rather than replace data in place. |
| T-012 | `VERIFIED` | Managed historical revisions, thumbnails, bundles, and purge quarantine use explicit storage layouts; no-copy revision records reference external paths. | revision/file/Trash services and Gate 6D recovery evidence | Backup completeness and storage invariants are enforced by schema-aware matched-pair verification. |
| T-013 | `VERIFIED` | Mounted scans deduplicate primarily by source path and report details to process logs. | `api/mount_import.py` | A durable scan job/report is required for v5.1 observability. |
| T-014 | `VERIFIED` | URL import performs important address checks, but redirect and DNS behavior still need adversarial tests. | `api/url_utils.py`, security review | SSRF safety is proven by tests at the security gate, not presumed. |
| T-015 | `VERIFIED` | Prepared payloads and visible supporting files already have distinct roles and response behavior. | `AssetFile`, prepared-print and ZIP services | Visibility/download invariants need regression tests. |
| T-016 | `VERIFIED` | The repository owns a unified `make verify` harness and GitHub Actions workflow covering API migrations/routes, web type-check/tests/build, bridge tests/build, Compose validation, and container smoke behavior. | `Makefile`, `.github/workflows/ci.yml`, Gate 0 evidence | Later gates extend the shared harness and cannot substitute undocumented local checks. |
| T-017 | `VERIFIED` | Large route and UI files concentrate behavior in `api/main.py` and `AssetGrid.tsx`. | source inventory | New work should extract seams incrementally; no rewrite gate is authorized. |
| T-018 | `VERIFIED` | Canonical local and production Compose manifests are named; compatibility aliases are tested; generated/runtime artifacts are ignored and absent from Git tracking. | ADR 0001, Compose validation, root `.gitignore`, Gate 0 evidence | Deployment and repository ownership drift is now detectable by the shared harness. |
| T-019 | `DECIDED` | The frozen Gate 5 v5.1 candidate is single-admin. Later local Gates 11 and 11E implement shared-vault accounts and optional passkey MFA; API keys and OIDC/SSO remain deferred. | Immutable Gate 5 boundary; Gate 11/11E checkpoints | Current development evidence must not be presented as qualification of a replacement v5.1 release candidate. |
| T-020 | `DECIDED` | v5.1 is a confidence release, not the Project/Revision rewrite. | v5.1 scope | Reliability gates outrank future architecture work. |
| T-021 | `VERIFIED` | Gate 5 qualifies and locally accepts immutable v5.1 source `f6ff55b`; upgrade, recovery, exact-image, reproducibility, performance, import, and browser evidence pass. Publication remains deferred. | `docs/evidence/gate-5/RESULTS.md`, acceptance commit `c004c60` | Gate 6 branches from a fixed release boundary and cannot alter the v5.1 candidate. |
| T-022 | `VERIFIED` | The immutable v5.1/schema-5 boundary had one mutable primary-file state per Asset, no content digest or revisions, and immediate best-effort deletion outside a filesystem/database transaction. | Gate 6 source audit and `docs/evidence/gate-6/BASELINE.md` | This remains the measured migration baseline and pre-Gate-6 rollback boundary. |
| T-023 | `DECIDED` | A bounded print-failure alert is a candidate experimental post-v5.1 track: disabled by default, advisory only, external-provider-first, and never a Gate 6 dependency. | `docs/EXPERIMENTAL_PRINT_MONITORING.md`, owner direction 2026-08-22 | Monitoring can be prototyped independently but cannot introduce printer-control authority or weaken active-gate evidence. |
| T-024 | `VERIFIED` | Schema 8 provides content identity, immutable revision replacement/restore/export, metadata-only Trash, explicit retention/permanent deletion, and format-1 matched backup verification for every revision and purge journal. | `docs/evidence/gate-6/RESULTS.md`, Gate 6 API tests | Gate 7 may rely on stable artifact/revision ownership only after the owner accepts Gate 6 closeout. |
| T-025 | `SUPERSEDED` | Schema 8 had no Project or artifact-relationship entity. Folders controlled browse/storage organization, `collection` was free-form metadata, and every API/UI workflow addressed an Asset directly. | Gate 7 source audit and `docs/evidence/gate-7/BASELINE.md` | This remains the measured pre-Project migration boundary. |
| T-026 | `VERIFIED` | Schema 9 adds empty-by-default Project identity and explicit many-to-many artifact membership. Authenticated bounded APIs enforce active-name, metadata, membership, Trash-visibility, and artifact-purge ownership rules without changing artifact bytes or paths. | `docs/evidence/gate-7/SUBGATE_7A_RESULTS.md`, Project and migration tests | Gate 7B builds retrieval UI on the accepted additive model. |
| T-027 | `VERIFIED` | Local Gate 7B implementation adds bounded Project navigation/workspaces, active-Project Unassigned retrieval, explicit membership actions, and optional Project-scoped ingestion while preserving standalone folders, artifact history, paths, bytes, and schema 9. | `docs/evidence/gate-7/SUBGATE_7B_RESULTS.md`, Project API/web workflow tests, full repository gate | Owner accepted 7B on 2026-08-23; Gate 7C may add the accepted relationship model. Publication remains prohibited. |
| T-028 | `VERIFIED` | Local schema 10 stores only canonical Project-scoped artifact relationships, computes inverse labels, enforces same-active-Project membership and recursive cycle rules, and preserves relationships through ordinary Trash while cleaning incident rows on confirmed membership removal or permanent artifact purge. | `docs/evidence/gate-7/SUBGATE_7C_RESULTS.md`, relationship/migration/UI tests, full repository gate | Owner accepted 7C on 2026-08-25; Gate 7D may add the accepted lifecycle/export model. Publication remains prohibited. |
| T-029 | `VERIFIED` | Local Gate 7D adds bounded Project metadata Trash, exact restore/permanent-delete ownership, and authenticated ZIP64 Project export that composes complete artifact histories with deterministic manifests and explicit missing/changed/external truth while leaving schema 10 and member bytes unchanged. | `docs/evidence/gate-7/SUBGATE_7D_RESULTS.md`, lifecycle/export/API/UI tests, full repository gate | Owner accepted 7D on 2026-08-25; Gate 7E may extend recovery verification and closeout evidence. Publication remains prohibited. |
| T-030 | `VERIFIED` | Local Gate 7E advances new matched backups to recovery contract 3 and audits schema-10 Project, membership, and relationship ownership with deterministic corruption reports. Outer format 1 and schema 10 remain unchanged; legacy no-marker and contract-2 archives remain verifiable, including pre-7E schema-10 backups. | `docs/evidence/gate-7/SUBGATE_7E_RESULTS.md`, recovery/migration/Project/Trash tests, full repository gate | Owner accepted Gate 7 closeout on 2026-08-26. Gate 8 and publication remain unauthorized. |
| T-031 | `VERIFIED` | Gate 8 generalizes the local bridge through an embedded version-1 adapter catalog, exact-file adapter/role grants, constrained local custom adapters, diagnostics/revocation, file-sensitive FreeCAD/Inkscape UI, preserved legacy schemes, and Windows/Linux/macOS platform contracts without changing schema 10 or stored bytes. | `docs/evidence/gate-8/GATE_8_RESULTS.md`, ADR 0012, API/web/bridge regressions, platform cross-builds, full repository gate | Owner accepted Gate 8 closeout on 2026-08-26. Gate 9 and any push, tag, release, deployment, SDK, marketplace, or publication remain separately gated. |
| T-032 | `VERIFIED` | Local schema 11 adds empty-by-default descriptive Machine profiles with six bounded categories, strict common fields, case-insensitive active-name identity, authenticated retrieval/lifecycle, archive-first permanent deletion, and no device or stored-byte authority. | `docs/evidence/gate-9/SUBGATE_9A_RESULTS.md`, Machine API/migration regressions, full repository gate | Owner accepted 9A and additive schema 12 for 9B on 2026-08-27. Gate 9B is authorized; publication remains unauthorized. |
| T-033 | `VERIFIED` | Local schema 12 adds explicit neutral Artifact-machine associations and nullable exact prepared-machine references on current Assets and immutable Revisions. Authenticated APIs never auto-match supplied printer text; new exact targets require active FDM/resin profiles. Trash retains context, while transactional permanent deletion removes only owned associations or nullable references and never rewrites prepared metadata, payloads, paths, or stored bytes. | `docs/evidence/gate-9/SUBGATE_9B_RESULTS.md`, machine-context/migration/revision/Trash regressions, full repository gate | Owner accepted Gate 9B on 2026-08-28. Publication remains unauthorized. |
| T-034 | `VERIFIED` | Local Gate 9C advances Artifact-history and Project exports to format 2 with deterministic Machine snapshots and unresolved-ID truth, adds duplicate-safe current-state Machine retrieval, and exposes bounded Settings/detail workflows with no per-card context fan-out or device authority. Schema 12 and recovery contract 3 are unchanged. | `docs/evidence/gate-9/SUBGATE_9C_RESULTS.md`, portability/retrieval/web regressions, full repository gate | Owner accepted Gate 9C at `0485184` on 2026-08-28. Gate 9D is at its recovery/closeout owner checkpoint; publication remains unauthorized. |
| T-035 | `VERIFIED` | Local Gate 9D advances new matched backups to recovery contract 4 and audits schema-12 Machine structures, identities, associations, current and historical exact targets, and current/revision mirror truth with deterministic critical findings. Outer format 1, schema 12, export formats, paths, and stored bytes remain unchanged; historical no-marker, contract-2, and pre-9D contract-3 report subsets remain supported only when current content audit passes. | `docs/evidence/gate-9/SUBGATE_9D_RESULTS.md`, recovery/corruption/compatibility regressions, full repository gate | Owner accepted Gate 9 closeout on 2026-08-31. Gate 10 was separately authorized; publication remains unauthorized. |
| T-036 | `SUPERSEDED` | At Gate 10 entry, server backup was a stopped raw SQLite/storage snapshot containing `.env`; Artifact and Project exports were logical ZIP format 2 with no importer; eight production modules depended directly on local `Path`/rename/free-space semantics. | Gate 10 source audit and `docs/evidence/gate-10/BASELINE.md` | This remains the measured pre-portability boundary and is superseded by T-037–T-038. |
| T-037 | `VERIFIED` | Local Gates 10A–10B define dependency-free, independently verifiable `.mvault` v1 and a capability-explicit local `ContentStore`; the stopped schema-12 exporter streams and hashes complete managed content, records external truth, independently verifies output, and publishes create-if-absent without changing the raw backup contract. | `docs/MVAULT_FORMAT_V1.md`, `docs/evidence/gate-10/SUBGATE_10A_RESULTS.md`, `docs/evidence/gate-10/SUBGATE_10B_RESULTS.md` | 10A–10B are owner-accepted. No object-store driver or live export is authorized. |
| T-038 | `VERIFIED` | Local Gate 10C imports independently verified `.mvault` v1 archives only into absent or compatible empty schema-12 targets, reconstructs records and streamed bytes in isolation, assigns SHA-256-derived provider-safe keys, marks external references unavailable, audits the staged pair, and publishes storage first/SQLite last behind a restart-safe rollback journal. | `api/mvault_import.py`, `docs/evidence/gate-10/SUBGATE_10C_RESULTS.md`, focused restore regressions | Owner accepted Gate 10C and authorized 10D on 2026-08-31. Merge/replacement/live import, S3, application key custody, and publication remain unauthorized. |
| T-039 | `VERIFIED` | Local Gate 10D defines a source-owned offline export/verify/import workflow with canonical phase progress on stderr, JSON results and content/external summaries on stdout, stable cancellation exits, and a documented standard `age` v1 outer-envelope workflow whose identities remain entirely user-owned. | `docs/PORTABLE_VAULT_WORKFLOW.md`, `docs/evidence/gate-10/SUBGATE_10D_RESULTS.md`, CLI workflow regressions | Owner accepted Gate 10D and authorized 10E on 2026-08-31. No application cryptography/key custody, browser job orchestration, S3, live/merge import, or publication is authorized. |
| T-040 | `VERIFIED` | Gate 10E's 1,200-Artifact mixed drill verifies 8,452 logical records and 3,479 managed files including a 64 MiB incompressible payload, then clean-restores/re-exports 3,790 portable members with semantic/byte equality; export, verify, import, and re-export each stay below 68 MiB peak RSS. Pinned `.mvault` v1 and legacy/current raw format-1 backup contracts pass, capacity/interruption behavior is explicit, and the remote-provider evaluation is no-go. | `docs/evidence/gate-10/SUBGATE_10E_RESULTS.md`, portable scale drill, failure matrix, provider evaluation | Owner accepted and closed Gate 10 on 2026-08-31. S3, provider credentials, merge/live import, application key custody, and publication remain unauthorized. |
| T-041 | `VERIFIED` | Gate 11 opens from one environment-configured administrator, direct constant-time password comparison, process-local throttling, renewable 12-hour HS256 bearer JWTs, browser `sessionStorage` and query-token compatibility, no persistent User/Session/Role/AuditEvent, and one globally shared content graph. | `api/auth.py`, `api/login_security.py`, `api/main.py`, `api/models.py`, web auth client, `docs/evidence/gate-11/BASELINE.md` | The owner accepted shared-vault tenancy, roles, enrollment, session, recovery, audit, and portability direction on 2026-08-31 and authorized 11A only. Sessions, role enforcement, additional users, and later authentication stages remain gated. |
| T-042 | `VERIFIED` | Local schema 13 adds one persistent administrator with normalized identity and a pinned, bounded Argon2id password policy. A validated environment administrator is converted only when the identity table is empty; subsequent environment changes are not a login or recovery bypass. `.mvault` v1 accepts schema-12/13 sources while excluding identity and reconstructing its frozen schema-12 content contract. | `api/identity_service.py`, schema-13 migration, Gate 11A identity/login/migration/portable regressions, `docs/evidence/gate-11/SUBGATE_11A_RESULTS.md` | Owner accepted Gate 11A and authorized 11B on 2026-09-01. Additional accounts, roles, recovery, audit, and later authentication stages remain gated. |
| T-043 | `VERIFIED` | Local schema 14 replaces browser JWT/query authentication with opaque, digest-only, revocable sessions; production `__Host-` HttpOnly Secure SameSite cookies; exact-Origin plus session-bound CSRF enforcement; bounded idle/absolute expiry, cleanup and active count; logout/per-session/revoke-all; and an in-memory browser migration with no authentication bearer in storage or URLs. The exact-file bridge grant remains separately scoped. | `api/session_service.py`, session/auth routes, web session client/settings, Gate 11B session/migration/portable/browser regressions, `docs/evidence/gate-11/SUBGATE_11B_RESULTS.md` | Owner accepted Gate 11B and authorized 11C on 2026-09-01. Additional accounts, administration, recovery, and audit remain unchanged and unauthorized. |
| T-044 | `VERIFIED` | Local schema 15 adds exactly three fixed shared-vault roles mapped to stable permissions. All 88 HTTP routes are exhaustively classified and startup-validated; 85 require one session permission while health, login, and scoped handoff redemption are the only exceptions. Eight independent startup/background services pass through a closed fail-closed system dispatcher. Viewer is active-content read/download/export/handoff-only, Member manages recoverable shared content, and Administrator alone owns settings, durable jobs, permanent deletion, and Trash emptying. | `api/authorization.py`, schema-15 migration, capability-aware web UI, Gate 11C authorization/migration/portable/UI regressions, `docs/evidence/gate-11/SUBGATE_11C_RESULTS.md` | Owner accepted Gate 11C and authorized 11D on 2026-09-02. MFA, API keys, OIDC, public registration, hosted tenancy, and publication remain unauthorized. |
| T-045 | `VERIFIED` | Local schema 16 adds Administrator-created shared-vault accounts, forced temporary-password replacement, five-minute recent password confirmation, affected-session revocation, and last-enabled-Administrator protection. All 94 routes remain exhaustively classified; schema-16 audit/recovery tables are structural reservations and do not yet imply durable audit or recovery behavior. | `api/account_service.py`, schema-16 migration, account/session API and browser regressions, `docs/evidence/gate-11/SUBGATE_11D1_RESULTS.md` | Owner accepted 11D-1 and authorized 11D-2 on 2026-09-03. Publication remains unauthorized. |
| T-046 | `VERIFIED` | Local Gate 11D-2 activates schema 16's durable audit table with mandatory outcome capture for every mutation and sensitive security/export/handoff reads, server correlation IDs, actor/role snapshots, bounded canonical targets, body/query/secret exclusion, identity-transaction atomicity, honest post-commit failure behavior, and Administrator-only cursor retrieval. All 95 HTTP routes remain deny-by-default classified; `.mvault` v1 excludes real audit state. | `api/audit_service.py`, `api/audit_middleware.py`, audit/account/portable regressions, browser Security Audit, `docs/evidence/gate-11/SUBGATE_11D2_RESULTS.md` | Owner accepted Gate 11D-2 by authorizing 11D-3 on 2026-09-03. Publication remains unauthorized. |
| T-047 | `VERIFIED` | Local Gate 11D-3 advances new raw backups to recovery contract 5 with schema-16 identity/session/audit/marker verification and compatible re-audit of contracts 2–4. Exact raw restore revokes copied sessions and queues a startup audit marker. Interactive stopped-instance recovery requires a verified exact pre-change backup, protected password prompt, exclusive file/SQLite lock, and one existing account; it revokes every session and cannot create a bypass identity. | `api/recovery.py`, `api/recovery_mutation.py`, `api/recovery_marker_service.py`, `scripts/recover-administrator.sh`, recovery regressions, `docs/evidence/gate-11/SUBGATE_11D3_RESULTS.md` | Owner accepted Gate 11D-3 on 2026-09-03. Consolidated Gate 11 closeout is next; no 11E work, push, tag, release, deployment, or publication is authorized. |
| T-048 | `VERIFIED` | Gate 11 closes with persistent Argon2id identities, revocable protected-cookie sessions, three deny-by-default shared-vault roles, account/recent-authentication safety, mandatory audit, contract-5 raw recovery, and stopped-instance Administrator recovery operating as one tested system. The consolidated identity/session/authorization/account/audit/recovery/portable matrix passes 118 tests. | `docs/evidence/gate-11/RESULTS.md`, accepted 11A–11D evidence, full repository gate | Owner accepted 11D-3 and authorized Gate 11E on 2026-09-03. Gate 11E remains at its authenticator design checkpoint; no schema/feature implementation or publication is implicit. |
| T-049 | `VERIFIED` | Local Gate 11E-1a pins a maintained WebAuthn verifier, adds optional-by-default schema-17 account/credential/digest-only-ceremony/singleton-policy state, advances new raw backups to recovery contract 6, consumes pending ceremonies on restore, clears recovered-Administrator factor state, and proves `.mvault` v1 excludes real authenticator records. It exposes no registration or login behavior. | ADR 0019, schema/dependency/recovery/portable regressions, `docs/evidence/gate-11/SUBGATE_11E1A_RESULTS.md` | Owner accepted 11E-1a on 2026-09-04 and authorized 11E-1b registration/self-management. Login/assertion, UI, TOTP, API keys, OIDC, and publication remain unauthorized. |
| T-050 | `VERIFIED` | Local Gate 11E-1b adds explicit stable RP/origin validation, owner-only UV-required attestation-free registration, bounded digest-only session-bound ceremonies, credential list/rename/removal, passkey reauthentication for current-strength self-management, first-enrollment opt-in, last-credential policy safety, and atomic secret-free audit without changing schema 17 or recovery contract 6. | Passkey configuration/service/API regressions, full repository gate, `docs/evidence/gate-11/SUBGATE_11E1B_RESULTS.md` | Owner accepted 11E-1b on 2026-09-04 and authorized 11E-1c. UI/policy/reset closeout remains 11E-1d; push, deployment, and publication remain prohibited. |
| T-051 | `VERIFIED` | Local Gate 11E-1c makes password success for an MFA-enabled account create only a five-minute digest-bound pending transaction in a separate host-only cookie. Exact-origin, UV-required assertion verification consumes that transaction before issuing a fresh normal session; bounded per-transaction attempts, per-account pending state, source throttling, generic denials, and replay rejection create no session. High-impact recent authentication now requires recent password and session/RP/origin-bound passkey proof for MFA accounts, including the forced-password-change recovery path. | Password-first/assertion/replay/throttling/recent-auth regressions, 310-test API gate, `docs/evidence/gate-11/SUBGATE_11E1C_RESULTS.md` | Owner accepted 11E-1c on 2026-09-04 and authorized 11E-1d. Push, deployment, and publication remain prohibited. |
| T-052 | `VERIFIED` | Local Gate 11E-1d completes native browser registration/login/step-up and credential management, Administrator-selectable Optional/Require Administrators/Require Everyone policy with enrollment and account-mutation invariants, and explicit current-strength other-account MFA reset that preserves the password and revokes sessions. Schema 17 and recovery contract 6 remain unchanged; raw restore and stopped-instance recovery behavior are revalidated. | 313 API tests, 32 web tests/build, Chromium virtual-authenticator drill, Compose/security/bridge/container gates, `docs/evidence/gate-11/SUBGATE_11E1D_RESULTS.md` | Owner accepted closeout on 2026-09-05 at implementation `1a209aa` and evidence `6b2ed08`. Push, tag, release, deployment, and publication remain prohibited. |
| T-053 | `DECIDED` | Gate 12 sustainable optional services is deferred to the desktop version by owner direction. Its delivery evidence is outstanding; free-core, portability, and non-lock-in commitments remain in force. | Owner direction 2026-09-05; Gate 12 status and `docs/SUSTAINABILITY.md` | Carry Gate 12 into the desktop roadmap and explicitly trace the deferral in Gate 13; do not count it as delivered. |
| T-054 | `VERIFIED` | Gate 13A reruns the existing complete repository gate on `236c0fd`: 313 API tests, 32 web tests/type/build, bridge/Compose/security/fresh schema-17 smoke/passkey checks, and the static release contract pass. A current 1,200-Artifact portable round trip preserves 3,790 catalog/payload members within its 256 MiB worker budget. | `docs/evidence/gate-13/SUBGATE_13A_RESULTS.md`, current test-image identities and commands | Owner accepted 13A at `c2e9f94` on 2026-09-05 and authorized 13B. These development results do not qualify a new release candidate or alone prove portable-import startup. |
| T-055 | `VERIFIED` | At 13A entry, preview/organization/mounted-import and exact-image release harnesses used legacy JWT authentication; recovery/release drills asserted schema 5 and could not qualify current behavior unchanged. | `docs/evidence/gate-13/TRACEABILITY.md`, findings G13-01–03 and named source scripts | Harness assumptions replaced by T-056; current browser/release matrix remains 13C. Historical Gate 5 evidence is preserved and production authentication unchanged. |
| T-056 | `VERIFIED` | Gate 13B replaces the stale authentication/schema assumptions identified by T-055. Full verification at `2c68d70` passes 313 API / 32 web / 7 Python harness / 5 Node client tests plus production-HTTPS schema 4→17 upgrade, contract-6 restore with pre-start invalidation, exact stopped rollback, and portable 17→12→17 fresh-identity startup. | `docs/evidence/gate-13/SUBGATE_13B_RESULTS.md`; immutable local development image IDs, 18 portable members, refusal/interruption evidence | Owner accepted 13B at `2f61b37` on 2026-09-06. Current browser/platform/advisory and selected-release qualification remain 13C; Gate 12 remains desktop-deferred and publication prohibited. |
| T-057 | `VERIFIED` | Dated 13C scans on unchanged entry locks/images report three affected web packages and 283 API / 158 web image package matches. Python application locks, Go source and browser-harness locks report no findings for their stated scope. Production HTTPS/operator prose is reconciled; audit helpers and the static release contract pass. | `docs/evidence/gate-13/SUBGATE_13C_RESULTS.md`, advisory review, machine-readable identities/hashes and all reduced image matches | These are observed results, not security clearance. Remediation and runtime-image triage require an owner scope decision; browser/platform/release qualification remain unfinished. No application pins changed or publication authorized. |
| T-058 | `VERIFIED` | Owner-approved targeted dependency/runtime maintenance and complete verification pass at clean `84b020d`: 313 API / 37 web tests, current production-HTTPS lifecycle and exact audited-image smoke. Fresh language locks report no advisories; images report 181 API / 3 web package matches. | `docs/evidence/gate-13/REMEDIATION_RESULTS.md`, new audit/match/vendor/verification records | T-057 remains historical entry evidence. Seven interpreter matches have explicit vendor exclusions; other findings are not waived. The subsequent approved archive guard is T-059. Browser/platform/release qualification and 13C acceptance remain open. |
| T-059 | `VERIFIED` | Owner approved Stored/Deflate-only member parsing after `78f6aa3`. The bounded guard preserves conforming 3MF/ZIP64, original prepared handoff and library-size policy. Full gate at clean `ddf8cf4` passes 351 API / 45 web tests and the HTTPS recovery lifecycle. Exact-image rescan retains 181 API / 3 web matches; reviewed unsupported-member read paths are mitigated, not a patched interpreter inventory. | `docs/evidence/gate-13/ARCHIVE_GUARD_RESULTS.md`, compression regressions, new verification/audit records | Current browser evidence is separate: Chromium first cards miss <1000 ms despite completed functional workflows. No budget or security-policy relaxation, residual-risk waiver, 13C acceptance or publication follows from the full-gate pass. |
| T-060 | `VERIFIED` | Owner-approved browser corrections at clean `1255933` pass the complete gate: 351 API / 51 web / 19 Python harness / 10 Node tests and joined HTTPS lifecycle. Seven request-order browser cases pass and the old-image control fails at 20 instead of two cards. Firefox trust and three-engine organization functional assertions pass. Browser-side first-card timing retains old wait duration separately. | `docs/evidence/gate-13/BROWSER_FIX_RESULTS.md`, new immutable image/verification/browser records | No blanket performance pass: Chromium A records 584.4 ms first cards and a 56 ms load-more long task; repeat B records 1433.2 ms first cards, 713 ms navigation and 55 ms folder-navigation tasks. Profile before an optimization proposal; thresholds, release pins, residual risks and 13C acceptance remain unchanged. |
| T-061 | `VERIFIED` | Owner-approved diagnostic profiling on unchanged `1255933` images completes three traced and two unprofiled 600-Artifact/104-folder runs. Run D confirms 4,200 closed folder options for 40 cards. Traces separate real DOM-building work, expensive driver queries and large wall/thread-CPU gaps; unprofiled controls pass at 495.2/528.0 ms without erasing historical failures. Profiling harness `8e11610` passes 19 Python / 14 Node tests and static release checks. | `docs/evidence/gate-13/CHROMIUM_PROFILE_RESULTS.md`, all five reduced runs and private-artifact hashes | The subsequent owner-approved picker and benchmark slice is T-062. These historical profiles did not establish a single cause for all stalls or accept performance/security/13C. |
| T-062 | `VERIFIED` | Owner-approved shared on-demand folder picker at `76b526d` removes closed-card destination duplication (4,200→0 at 40 cards/104 folders), retains paths/confirmation/permissions/bytes and passes all ten picker cases in three engines plus seven Chromium ordering cases. Full-gate inputs match `76b526d`: 351 API / 56 web tests and joined HTTPS lifecycle; later harness `53142f9` passes 19 Python / 21 Node tests. Three unprofiled 600/104 Chromium repeats pass unchanged enforced budgets. | `docs/evidence/gate-13/FOLDER_PICKER_RESULTS.md`, explicit full-run source note, exact images, all attempts/hashes and fresh image audit | 600/1,040 stress fails first cards (1,612.4 ms) and folder search (494.9 ms); separate detail preview records 1,074 ms long task. Both remain unqualified; no historical failure erased. Residual 181 API / 3 web matches remain unwaived. Profile remaining paths before another optimization proposal; platform/release/13C acceptance remain owner checkpoints. |
| T-063 | `VERIFIED` | Owner-authorized diagnosis on unchanged `76b526d` images retains six attempts. Stress sidebar mounts 8,800 hidden menu descendants; real DOM callbacks and 405–475 ms driver label queries are distinct costs. Captured detail pause is 1,039.5 ms wall / 1.0 ms renderer CPU, before the STL request; observed context creation is under 8 ms. Diagnostic harness `3101b68` passes 19 Python / 28 Node tests and static release checks. | `docs/evidence/gate-13/RESIDUAL_DIAGNOSIS.md`, complete reduced runs/private-artifact hashes | Diagnosis is not a fix or blanket causal attribution. Unprofiled stress still fails search, interaction and folders API p95; exact detail native wait and API-time breakdown remain unresolved. Lazy sidebar menus plus scoped accessible locator are proposed, not implemented. No threshold, security, image, release-pin or owner-acceptance change. |
| T-064 | `VERIFIED` | Owner-approved on-demand sidebar menus and scoped search locator at `82cb2cc` remove 8,800 closed-menu descendants in the 1,040-folder fixture without changing 400 visible rows. Full gate passes 351 API / 58 web tests and HTTPS lifecycle. Seventeen picker/sidebar checks pass across three engines with explicit WebKit FileList-only event limits; seven ordering cases pass. All five Chromium organization runs have zero observed interaction tasks and fast folder search. | `docs/evidence/gate-13/SIDEBAR_MENU_RESULTS.md`, twelve retained browser attempts, final-image/full-gate identities, harness `7b0bb6e` | No general performance clearance: baseline E fails first cards at 1,368.5 ms; stress D/G fail folders API p95 at 113.3/108.3 ms. Historical detail wait, non-Chromium/native-platform evidence, advisories and release qualification remain open. No upload/folder quota, application API/auth/lock change, risk waiver, push or Gate 13C acceptance. |
| T-065 | `VERIFIED` / `DECIDED` | Bounded folder-list projection at `c42614e` preserves output and immediate mutation visibility without ORM hydration; 354 API tests pass. Disposable HTTP instrumentation attributes some API spikes to cyclic garbage collection, not expensive SQL execution. | `docs/evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md`, diagnostic samples and same-image unprofiled browser reports | Stress API still misses <100 ms. Exact intermittent browser wait remains unresolved. Owner authorized this one final pass and accepts carrying remaining performance issues for now: stop tuning; retain failures and original budgets. Not full-gate rerun, advisory waiver, native-platform proof, release or 13C acceptance. |
| T-066 | `VERIFIED` / `PROPOSED` | Security closeout review at `fb645d7` audits exact `c42614e` images and unchanged locks: production language scopes clean; development scans find Vitest/mocker and HTTPX2/httpcore2 advisories. All 181 API / 3 web matches are retained with reduced-record equality. Seven Python exclusions freshly confirmed; 68 focused security tests pass. Runtime inspection narrows several Perl preconditions; Unicode IDNA and native/raw-recovery residuals remain | `docs/evidence/gate-13/SECURITY_CLOSEOUT.md`, audit/inventory/runtime evidence and source URLs | REVIEW COMPLETE, SECURITY ACCEPTANCE OPEN. Approve bounded S01 tool refresh/S02 hostname hardening before implementation; resolve or explicitly disposition S04 against exact candidate images. No application/lock change, suppression, waiver, full-gate repeat, release or 13C acceptance. G13-01 stays deferred. |
| T-067 | `VERIFIED` | Owner-approved S01/S02 implementation at clean `ac4a051` updates Vitest and HTTPX2/httpcore2, declares existing idna directly, and uses strict IDNA2008 across outbound DNS/Host/SNI/redirect identity. 68 new cases and old-image negative control verify the boundary; 138 focused tests pass. Full gate passes 422 API tests, same-source 58-test web preflight, 19 Python / 28 Node harness tests and current HTTPS lifecycle. Fresh language audits are clean; exact runtime matches remain 181 API / 3 web with reduced-record equality | `docs/evidence/gate-13/SECURITY_HARDENING_RESULTS.md`, complete captured attempts/audit/runtime evidence | Reviewed outbound IDNA path mitigated, not a whole-interpreter patch. S04 native/raw-recovery residuals remain unwaived and require explicit dispositions before candidate qualification. No changed inbound auth, schema, base image, installer/bridge/release pin or stored model bytes. Performance G13-01 stays deferred; no push, release or automatic 13C acceptance. |
| T-068 | `VERIFIED` / `PROPOSED` | S04 decision preparation at unchanged `ac4a051` inputs accounts for 80 native CVEs / 167 matches: 11 exact-image precondition exclusions proposed, 10 priority unresolved reviews and 59 scoped residual decisions. A fresh benign probe exactly matches prior components on the named linux/amd64 images; targeted vendor pages rechecked. Shipped Compose does not explicitly apply the probe's isolation flags | `docs/evidence/gate-13/SECURITY_RESIDUAL_DECISIONS.md`, per-CVE pending register and new observations | Zero owner risk acceptances. Approve bounded no-new-privileges/capability hardening before implementing it; preserve startup ownership, upload limits and recovery. Historical private temporary logs are unavailable this session; committed evidence retained, no new full gate/advisory scan claimed. Durable raw candidate evidence required. No runtime changes, release, push or gate acceptance. |
| T-069 | `VERIFIED` | Owner-approved runtime containment at clean `ea17494` sets canonical Compose no-new-privileges / capability allowlists and empties API capability sets after setup. Full gate passes 422 API tests, 58 reexecuted web tests, 25 Python / 28 Node harness tests and HTTPS lifecycle with generated-preview persistence. Actual API/Nginx master/16 workers have five empty capability sets. Eight startup/ownership cases and six capability-removal controls pass on exact lifecycle API; old image fails the bounding-set assertion | `docs/evidence/gate-13/SECURITY_CONTAINMENT_RESULTS.md`, durable private captures and exact-image evidence | Preserve failed parser and initial image-audit attempts. Final audits match exact lifecycle IDs and retain identical reduced records for 181 API / 3 web matches; fresh language scopes clean, locks unchanged. Durable evidence passes 86 hash checks. Stronger containment is not a native patch, risk acceptance, hostile raw-snapshot sandbox or release qualification. No quota/resource limit, schema, model-byte or frozen-release change. |
| T-070 | `VERIFIED` / `PROPOSED` | S04 owner package joins all 80 native CVEs / 167 matches to the exact `ea17494` lifecycle images. Recommends E11 exact-image exclusions, R59 time-limited local-qualification exceptions and H10 holds. Targeted vendor review corrects the zipdetails CLI rationale; new exact-image probe confirms command absence and narrows SQLite symbol evidence without clearing SESSION | `docs/evidence/gate-13/SECURITY_DISPOSITION_PROPOSAL.md`, per-CVE proposal, four new durable probe captures and evidence checker | No owner acceptances recorded. R59 explicitly includes two critical Perl CVEs; all 184 image matches remain visible. Proposed named owner/C1–C7 conditions expire by 30 days or candidate freeze, whichever first. H10 and security/Gate 13C stay open even if E/R approved. No application changes, broad rescan, full-suite repeat, push or release. |
| T-071 | `DECIDED` / `VERIFIED` / `PROPOSED` | September 12 owner VincentCinque approves E11/R59 for exact-image local qualification under C1–C7; ten H remain unaccepted. New vendor review retains 79 Debian bodies (Alpine collector 406 retained), identifies stable fixes, and reopens seven R exceptions under C6. Fresh component/CLI probes reaffirm E11; 52 exceptions remain active and 17 residual CVEs open | `docs/evidence/gate-13/SECURITY_OWNER_ACCEPTANCE.md`, immutable approval event, dated review, durable captures and checker | Deadline October 12 00:00 America/New_York or earlier candidate freeze/13D/C6 trigger; no automatic renewal. All 181 API / 3 web matches remain; fixes are not installed. Six-package stable API refresh is proposed, not authorized. Preserve parser/collector limitations, exact-image scope, trusted raw recovery, remaining seven H evidence gaps, performance/desktop deferrals and release gates. |
| T-072 | `DECIDED` / `VERIFIED` / `OPEN` | Owner-approved six-package stable API refresh at clean `6306ccf` installs exactly the approved signed binary pins; no other package additions/removals/version changes. Full gate passes 424 API / 58 reexecuted web / 25 Python / 28 Node tests, HTTPS upgrade/recovery/rollback and exact-image 8-case/6-negative containment matrix | `docs/evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md`, joined exact-image inventory/audit/per-CVE record, 167 private hash checks | Fresh September 12 scanner data retains all prior pairs: API 189 / web 3 matches, seven newly seen CVEs. Twenty vendor-fixed-version claims conflict with scanner unknown ranges; no suppression or clean-scan claim. New images inherit no E/R waivers. Retain seven original H plus four new PCRE2 holds; three new exclusions only proposed. Reconcile evidence before additional remediation/owner dispositions. Interrupted wrapper attempt retained; no push, publication, schema, language-lock or frozen-release change. |
| T-073 | `VERIFIED` / `OPEN` | Read-only application reconciliation on unchanged `6306ccf` images verifies 26 vendor fixes: original 20 plus all six newly seen PCRE2 IDs. Current Debian feed fixed versions equal the pins; six archives match authenticated APT metadata and 931 runtime regular files match archive bytes. No further package update needed for this group | `docs/evidence/gate-13/SECURITY_RECONCILIATION_RESULTS.md`, new per-CVE register, 15 new plus 167 prior private hash checks | All 189 API / 3 web raw matches retained, including 28 for the 26 verified fixes; precise upstream scanner-ingestion cause unproven. Native87 now comprises fixed26, proposed E2, pending new-image R52 and unresolved H7. No new acceptance, waiver transfer, rescan, full-suite rerun, application change or push. Prepare the image-specific E/R decision and handle H7 separately; security and release gates remain open. |
| T-074 | `VERIFIED` / `PROPOSED` | Current-image E2/R52 owner package refreshes all 86 known Debian-native records: no scoped change, 26 fixes retained, 51 Debian R still open without a recorded Trixie fix. BusyBox CNA bytes unchanged; fresh exact-image component checks agree. Individual R rationales distinguish actual utilities/call preconditions | `docs/evidence/gate-13/SECURITY_CURRENT_IMAGE_DECISION.md`, pending 87-ID proposal, 15 new plus 182 prior private hashes | No new acceptance or old-image waiver transfer. R52 includes 44 High package matches and requires explicit acknowledgment that current Alpine fix status is unverified. Keep H7 unaccepted, October 12/earlier C6 deadline, raw 189 API / 3 web matches and first failed APK-output probe. Await E/R owner decision; no application change, rescan, full-gate repeat, push or security/release closure. |

### 5.4 Current storage invariants

Until a later gate changes them deliberately:

- SQLite holds identity and metadata; it is essential backup data.
- Existing managed revision-1 bytes may remain at their legacy/template path; every
  later managed revision lives at an immutable artifact/revision path and is never
  moved by artifact metadata changes.
- Generated thumbnails live under managed thumbnail storage and may be
  regenerated, but retaining them improves restore fidelity and performance.
- Supporting and prepared files live under per-asset bundle storage with explicit
  artifact-wide or revision ownership.
- A prepared file is internal and excluded from normal browse/download surfaces.
- Trash is metadata-only. Permanent deletion uses a durable database journal and a
  same-filesystem `.trash-quarantine` transition before ownership deletion.
- Mounted no-copy revision content remains outside the vault backup unless
  separately captured by the operator; its source path and state remain explicit.
- Operational recovery and rollback always restore SQLite and managed storage as a
  matched pair. Schema contraction is not authorized.

## 6. Target architecture direction

### 6.1 Architectural shape

```text
Web UI
  |
  v
HTTP/API boundary
  |
  v
Application use cases
  +-- library and organization
  +-- ingestion and provenance
  +-- preview orchestration
  +-- project/revision management
  +-- export, backup, and recovery
  `-- application handoff grants
  |
  v
Domain model and policy
  |
  +-------------------+---------------------+
  v                   v                     v
Metadata repository   Content store         Durable job store
(SQLite first)        (filesystem first)    (SQLite first)
                                                |
                                                v
                                    bounded workers/reconcilers

Short-lived, file-scoped handoff grant -> desktop bridge -> approved local app
```

Key rules:

- Route handlers translate HTTP; they do not own domain policy.
- Domain policy does not depend on React, FastAPI, SQLite SQL, or a concrete
  storage path.
- Storage is addressed through a small interface before S3-compatible storage is
  considered.
- Expensive or resumable work has durable job state and idempotent operations.
- The bridge receives a narrow handoff capability, not a general-purpose bearer
  token and arbitrary download authority.
- Components remain deployable as one API process until evidence justifies a
  separate worker.

### 6.2 Target logical model

The long-term logical direction is:

```text
Project
  `-- Artifact
        `-- ArtifactRevision
              +-- ArtifactFile -> ContentBlob
              +-- Preview (derived)
              +-- SourceReference / provenance
              `-- PreparedPrint (internal role and metadata)

Project/Artifact -- Relationship --> Project/Artifact
Artifact/Revision -- OpenWithPolicy --> ApplicationAdapter
PreparedPrint ---- Machine context --> MachineProfile (descriptive)
```

This remains a conceptual target, not the current physical schema. Accepted Gates
6–7 and ADRs 0007/0009–0011 resolved ownership and relationships: an existing Asset
is the compatible Artifact projection, Project membership is optional and
many-to-many, revisions are immutable, and supporting/prepared ownership is
explicit. There is no temporary AssetGroup or separate ContentBlob table. The
current map is in section 5.2; remaining architectural work is tracked by Gate 13.

Content identity and logical identity are separate:

- A `ContentBlob` is immutable bytes identified by SHA-256, size, and media type.
- An `Artifact` is the user's named thing and can change over time.
- An `ArtifactRevision` records a historical state.
- An `ArtifactFile` gives content a role and user-facing filename.
- A folder, collection, and tags organize items; they do not define byte identity.

Physical content-addressed storage is optional. SHA-256 identity must not force a
storage-layout migration before it is valuable.

### 6.3 Compatibility policy

- v5.1 API changes are additive wherever practical.
- Stored files are not relocated merely to make a schema look cleaner.
- New columns are nullable or safely defaulted during expansion.
- Data is backfilled and verified before old representations are contracted.
- Destructive schema contraction occurs only in a later release with a tested
  backup/restore path.
- Downgrade recovery may be restore-from-backup rather than a lossy reverse
  migration; that fact must be explicit in release notes.

## 7. Gate operating model

### 7.1 Gate lifecycle

```text
PROPOSED -> READY -> IN PROGRESS -> EVIDENCE REVIEW -> ACCEPTED
                \                         |
                 +------ REWORK <---------+
```

`READY` means entry evidence exists, open owner decisions are resolved, and
migration/rollback plans are written. `ACCEPTED` means exit evidence has been
reviewed and the truth ledger has been updated.

Only one roadmap gate is active at a time unless the owner explicitly authorizes
parallel work with independent data and rollback boundaries.

### 7.2 Stop and ask checkpoints

Implementation stops for owner input when a gate requires:

- A change to a product invariant or explicit non-goal.
- A destructive or externally visible data-retention decision.
- A user-facing terminology or workflow choice with materially different product
  meaning.
- A new external service, recurring cost, telemetry, or paid-service dependency.
- A new trust boundary, remote access posture, or machine-control capability.
- An irreversible migration whose safer alternative materially changes scope.
- Reprioritization because the evidence makes the active roadmap order unsound.

Routine implementation choices inside an accepted gate do not require repeated
approval; they require evidence at exit.

### 7.3 Definition of done for every gate

Unless a gate explicitly proves an item irrelevant, completion requires:

- Acceptance criteria tied to tests or a reproducible manual protocol.
- Upgrade from a representative prior-version database and storage fixture.
- Failure-path coverage, not only a happy path.
- Security review of changed trust boundaries and file handling.
- Backup/restore implications documented.
- User-visible behavior and operator documentation updated.
- Build and packaging evidence for affected components.
- No unexplained new warning, generated artifact, or dirty migration output.
- Truth ledger, risk register, and next gate re-baselined.

## 8. Sequenced roadmap gates

### Gate 0 — Establish the reproducible baseline and safety harness

**Current execution:** `ACCEPTED` as of 2026-08-14. Local evidence is in
[evidence/gate-0/RESULTS.md](evidence/gate-0/RESULTS.md). Both ADRs are accepted,
immutable baseline `1231565642b8541a7ad36ba4ffdeb2da9527ef89` passed the complete
local harness, and GitHub Actions run 31802094344 passed all remote jobs.

**Objective:** Turn the current working version into a named, reproducible
baseline that can be changed without guessing.

**Entry truth:** v5.1 feature work exists in a dirty working tree; the repository
has no established automated test/CI contract, formal schema versioning, or single
canonical deployment manifest.

**Required work:**

- Preserve and inventory current user-owned changes before cleanup.
- Separate source, release artifacts, generated web output, runtime databases,
  caches, and local binaries in repository policy.
- Name the canonical development and production Compose manifests; remove or
  explicitly generate duplicates in a later reviewed change.
- Record an architecture/component map and configuration inventory.
- Introduce a formal schema version and ordered migration runner suitable for
  SQLite. Select Alembic or a small versioned migration system through an ADR.
- Create representative pre-v5.1 and current database/storage fixtures with no
  private user content.
- Establish API test, web build/type-check/test, bridge build/test, and container
  smoke-test commands.
- Add CI that executes the same source-owned commands used locally.
- Revalidate every security finding against current source and mark it confirmed,
  fixed, stale, or needing runtime proof.

**Exit evidence:**

- A clean, tagged or committed baseline can be recreated from source.
- One documented command set verifies API, web, bridge, and containers.
- A fresh database and representative old database reach the same declared schema
  version through repeatable migration.
- Canonical manifests and generated-artifact ownership are unambiguous.
- The security analysis no longer contradicts current source without a recorded
  discrepancy.

**Owner checkpoint:** approve the canonical deployment path and migration-system
ADR.

**Rollback:** Gate 0 must not transform user libraries. Tooling and repository
policy can be reverted while the preserved working snapshot remains recoverable.

### Gate 1 — Harden v5.1 trust boundaries and deployment

**Current execution:** `ACCEPTED` as of 2026-08-14. Final evidence is recorded in
[evidence/gate-1/RESULTS.md](evidence/gate-1/RESULTS.md). Entry evidence and the
first owner checkpoint are recorded in
[evidence/gate-1/BASELINE.md](evidence/gate-1/BASELINE.md). Both owner decisions
are accepted. Fail-closed production configuration is implemented and locally
verified in [slice 1A evidence](evidence/gate-1/SLICE_1A_RESULTS.md). The
framework/parser and build-toolchain upgrades are locally verified in
[slice 1B evidence](evidence/gate-1/SLICE_1B_RESULTS.md). The owner-approved
server resource budgets, ZIP safety, and mounted-source containment are locally
verified in [slice 1C evidence](evidence/gate-1/SLICE_1C_RESULTS.md). Ordinary
multi-file imports remain unmetered as a batch; the approved limits apply per
file, with aggregate limits only for ZIP extraction. The immediate next action
was slice 1D; controlled redirects and connection-target enforcement are now
locally verified in [slice 1D evidence](evidence/gate-1/SLICE_1D_RESULTS.md).
The immediate next action is the slice 1E owner checkpoint: accept the scoped
handoff grant and bridge-origin contract before implementation. That contract is
now owner-approved and locally verified in
[slice 1E evidence](evidence/gate-1/SLICE_1E_RESULTS.md). The owner-approved
single-admin login/session residual-risk contract, security headers, host policy,
and final deployment guidance are now locally verified in
[slice 1F evidence](evidence/gate-1/SLICE_1F_RESULTS.md). All Gate 1 slices are
implemented, locally verified, and owner-accepted. The commits remain local by
owner decision until coordinated v5.1 rollout. Gate 2 is eligible to open from a
measured preview baseline.

**Objective:** Make a fresh v5.1 deployment safe by default for its stated
single-admin, self-hosted scope.

**Dependencies:** Gate 0 accepted.

**Required work:**

- Remove known production credential/signing-secret fallbacks and define a clear
  first-run or explicit-environment setup path.
- Fail startup with actionable guidance when production security configuration is
  missing or known-unsafe.
- Upgrade and verify vulnerable direct dependencies; record the dependency scan.
- Add application-level upload, archive-entry, aggregate expansion, image, model,
  time, and storage budgets.
- Validate every URL import redirect and resolved connection target against SSRF
  policy; test redirect and DNS-change cases.
- Prevent mounted copy mode from escaping the configured root through symlinks.
- Design a short-lived, file-scoped handoff grant. The bridge must reject arbitrary
  origins/files and never accept a general MakersVault session token as its long-
  term contract.
- Reassess browser token storage, query-string propagation, login throttling, and
  session invalidation for the single-admin threat model. Resolve what can be
  changed compatibly in v5.1 and record a dated residual risk for anything that
  properly depends on the Gate 11 session architecture.
- Document trusted-LAN, reverse-proxy, HTTPS, and direct-Internet exposure posture.
- Keep multi-user, roles, MFA, and SSO out of this gate.

**Exit evidence:** all confirmed v5.1 P0 security findings have a regression test
or documented compensating control; malicious upload/import fixtures remain
bounded; a default production launch cannot unknowingly use published secrets;
bridge abuse tests demonstrate the narrowed trust boundary.

**Owner checkpoint:** choose the first-run administrator experience and supported
remote-access posture.

**Rollback:** configuration changes use a compatibility window for existing
deployments. A documented environment migration restores service without reverting
to known credentials. File-format changes are not allowed in this gate.

### Gate 2 — Bound preview work and prove library responsiveness

**Current execution:** `ACCEPTED`. The owner approved Gate 2 closeout on
2026-08-14. The approved contract is implemented at local commit `af57da3`; the
complete repository harness and cold/warm/detail/LightBurn browser evidence pass.
See [Gate 2 results](evidence/gate-2/RESULTS.md).

**Objective:** Ensure no single model can freeze the library and cached libraries
remain fast.

**Dependencies:** Gates 0–1 accepted.

**Required work:**

- Create a non-private benchmark corpus: small, medium, large, malformed,
  multi-part, multi-plate, and image-heavy files.
- Capture baseline load time, interaction latency, active preview concurrency,
  memory, failure rate, cache hit rate, and repeated-visit behavior.
- Define size/complexity/time budgets per preview path.
- Persist preview state: pending, ready, failed with reason, skipped by policy, and
  retry requested.
- Keep library cards on bounded static previews; reserve interactive parsing for
  explicit detail view.
- Abort or isolate failed client work and verify navigation remains responsive.
- Verify embedded 3MF extraction, generated thumbnails, type-aware fallbacks, and
  preview modes across supported browsers.

**Exit evidence:** the benchmark report demonstrates bounded concurrency and
memory; pathological fixtures cannot block navigation; repeat visits primarily use
cached thumbnails; failure and retry behavior is visible and repeatable.

**Owner checkpoint:** approve the observable experience for files intentionally
skipped by safety policy. Numeric limits are evidence-driven and configurable
where installations reasonably differ.

**Rollback:** preview policy can fall back to cached/placeholder-only operation
without affecting original files or metadata.

### Gate 3 — Complete scalable organization workflows

**Current execution:** `ACCEPTED`. The owner approved Gate 3 closeout on
2026-08-21. The contract is implemented at local commit `188b2e9`; the complete
repository harness and executable 600-asset/104-folder browser workflow pass. See
[Gate 3 results](evidence/gate-3/RESULTS.md).

**Objective:** Make large-library navigation and bulk work explicit, predictable,
and recoverable.

**Dependencies:** Gate 2 accepted.

**Required work:**

- Add active-folder breadcrumbs and verified nested-folder/search behavior.
- Add a visible selection toolbar with selected count, current-page selection,
  clear selection, move, tag, download, and conservative deletion.
- Define selection behavior across filters, folders, pagination, and partial API
  failures.
- Report progress and per-item failures without hiding successful work.
- Preserve human-readable names unique within a folder and safe filename rename
  behavior.
- Do not implement “all server matches” until an API-side bulk contract can operate
  without loading every ID into the browser.
- Keep permanent mass deletion constrained until the trash gate exists.

**Exit evidence:** end-to-end tests cover navigation, selection scope, mixed
success/failure, concurrent rename conflict, supporting/prepared visibility, and
destructive confirmation; a representative large library remains usable.

**Owner checkpoint:** approve conservative deletion behavior before Trash exists.

**Rollback:** bulk operations are individually idempotent or report exactly which
IDs changed. Partial failure must never invite blind retry of destructive work.

### Gate 4 — Make ingestion observable and establish content truth

**Current execution:** `ACCEPTED`. Required Gate 4A was completed and locally
verified on 2026-08-21. Optional Gate 4B is explicitly deferred until Gate 5 proves
release-critical upgrade and recovery stability. See
[Gate 4 results](evidence/gate-4/RESULTS.md).

**Objective:** Let operators understand mounted imports and, when stable, establish
rename-resistant identity and provenance.

**Dependencies:** Gates 0–3 accepted.

**Gate 4A, required for v5.1:**

- Add an explicit mounted-library rescan action.
- Persist scan status, start/end time, import mode, and imported/skipped/failed
  counts with bounded failure details.
- Make scan work resumable or safely repeatable; one bad file cannot abort a scan.
- Preserve path-based compatibility and no-copy source ownership.
- State copy versus index-in-place consequences before execution.

**Gate 4B, include only when 4A and release-critical work are stable:**

- Compute SHA-256 during new ingestion without an avoidable second full read.
- Backfill managed files through bounded, resumable jobs.
- Record unavailable, changed, and failed states for no-copy content.
- Store source URL, creator, and license provenance when known.
- Warn on matching content; never auto-merge or delete.

**Gate 4A exit evidence:** repeated scans are explainable and do not duplicate
unchanged source paths; failure details are visible without container logs; copy and
index-in-place ownership remain explicit and tested.

**Gate 4B exit evidence when included:** hashing jobs are bounded and restartable;
known duplicate fixtures produce suggestions only.

**Owner checkpoint:** none for 4A within approved scope. Ask before introducing
automatic grouping, merging, or a license inference policy.

**Rollback:** scan records may be abandoned without altering sources. Hash and
provenance columns remain additive. A backfill can pause and resume safely.

### Gate 5 — Prove upgrade, recovery, and the v5.1 release

**Current execution:** `ACCEPTED`. The owner opened Gate 5 on 2026-08-21 and
approved the `f6ff55b` v5.1.0 release candidate, known limitations, and P1
deferrals on 2026-08-22. Feature scope remained frozen while the matched
backup/restore and release contract in
[the Gate 5 baseline](evidence/gate-5/BASELINE.md) was implemented. Upgrade,
recovery, exact-image, reproducibility, performance, import, bridge, and
Chromium/Firefox/WebKit evidence pass in
[the Gate 5 results](evidence/gate-5/RESULTS.md). Nothing is tagged, pushed, or
published; coordinated rollout remains a separate owner-authorized action.

**Objective:** Release v5.1 only after the whole confidence-release promise works
as an upgrade, not just as a fresh demo.

**Dependencies:** Gates 0–4A accepted; Gate 4B is optional and must be explicitly
listed as included or deferred.

**Required work:**

- Define essential data, derived/rebuildable data, and external no-copy data.
- Write and execute stop, snapshot, upgrade, verify, rollback/restore, and clean-
  machine recovery procedures.
- Test migrations against representative pre-v5.1 libraries, including nested
  folders, old thumbnails, supporting files, prepared metadata, renamed files,
  missing external files, and interrupted prior work.
- Run the performance, security, import, organization, and bridge matrices on
  versioned release candidates.
- Publish versioned Docker and bridge artifacts with provenance and checksums.
- Finish changelog, release notes, security policy, contribution guide, issue
  templates, upgrade notes, and known limitations.
- Verify the repository can build those artifacts without relying on committed
  runtime data or unexplained generated output.

**Exit evidence:** a clean installation is restored from the documented backup;
an old representative installation upgrades without data loss; rollback via the
documented backup succeeds; every v5.1 P0 acceptance criterion has named evidence;
release artifacts match their source revision.

**Owner checkpoint:** approve the release candidate, known limitations, and any P1
deferrals. This is the v5.1 ship/no-ship gate.

**Rollback:** restore the pre-upgrade database and managed-storage snapshot as a
matched set. Never restore only one side of the pair.

### Gate 6 — Establish revisions and recoverable deletion

**Current execution:** `ACCEPTED`; the owner accepted ADRs 0006–0008 and
[the Gate 6 checkpoint](evidence/gate-6/OWNER_CHECKPOINT.md) on 2026-08-22, with
capacity-aware Trash retention as the default. Current schema-5 behavior is recorded
in [the Gate 6 baseline](evidence/gate-6/BASELINE.md). Subgate 6A content truth and
revision expansion is implemented at local commit `c7e8743`; the complete repository
harness and focused migration/content evidence pass. The owner accepted
[the 6A results](evidence/gate-6/SUBGATE_6A_RESULTS.md) on 2026-08-22. Subgate 6B
is implemented at local commit `c6ddcfe` under its
[immutable workflow contract](evidence/gate-6/SUBGATE_6B_BASELINE.md); the full
repository gate and focused workflow checks pass in
[the 6B results](evidence/gate-6/SUBGATE_6B_RESULTS.md), accepted by the owner on
2026-08-22. Subgate 6C is complete under its
[Trash implementation contract](evidence/gate-6/SUBGATE_6C_BASELINE.md). The
implementation is complete at local commit `71c3d82`; focused safety tests and the
full repository harness pass in
[the 6C results](evidence/gate-6/SUBGATE_6C_RESULTS.md), accepted by the owner on
2026-08-22. Subgate 6D recovery, compatibility, and closeout is complete under
[its evidence contract](evidence/gate-6/SUBGATE_6D_BASELINE.md). Its implementation
is complete at local commit `642735d`; schema-7 upgrade, format-1 compatibility,
revision-aware backup/restore, and negative consistency evidence pass in
[the 6D results](evidence/gate-6/SUBGATE_6D_RESULTS.md). All Gate 6 exit claims are
mapped in [the Gate 6 closeout](evidence/gate-6/RESULTS.md). The owner accepted Gate
6 and separately authorized Gate 7 to begin on 2026-08-22.

**Objective:** Add trustworthy history before adding the larger Project model.

**Dependencies:** Gate 5 accepted against an immutable v5.1 candidate. Public
publication may remain deferred under the owner's local-development decision, but
Gate 6 history must remain strictly after and excluded from that candidate. SHA-256
identity is included as subgate 6A because Gate 4B was deferred.

**Subgates:** 6A content truth and revision expansion; 6B immutable revision
workflows; 6C Trash and permanent deletion; 6D recovery, compatibility, and
closeout.

**Required decisions:** current-revision semantics; metadata ownership between
artifact and revision; supporting-file versioning; preview retention; storage
layout; revision export; Trash retention and permanent-deletion policy.

**Exit evidence:** existing Assets migrate without byte relocation; revision
creation never overwrites historical bytes; restore and permanent deletion are
tested; mounted changed/missing content has explicit states; backup manifests
represent all revisions.

**Owner checkpoint:** approve metadata ownership and Trash retention before schema
implementation.

**Rollback:** use expand/migrate/verify/contract. Do not contract legacy Asset data
until at least one stable release has proven the new read/write path.

### Gate 7 — Introduce Projects and relationships

**Current execution:** `ACCEPTED`; the owner accepted the terminology, migration,
membership, relationship, lifecycle, and export package plus ADRs 0009–0011 on
2026-08-23. Subgate 7A is implemented at local commit `6d06e6f`; schema-8 migration,
Project CRUD, many-to-many membership, artifact Trash interaction, and the complete
repository gate pass in [the 7A results](evidence/gate-7/SUBGATE_7A_RESULTS.md),
accepted by the owner on 2026-08-23. Subgate 7B is implemented locally at
`04c6b4c`; its bounded workspace, retrieval, optional association, compensation,
and full-gate evidence are in
[the 7B results](evidence/gate-7/SUBGATE_7B_RESULTS.md), accepted by the owner on
2026-08-23. Subgate 7C is implemented locally at `e4746f3`; its additive schema-10
migration, relationship invariants, bounded workspace UI, cleanup/Trash behavior,
and full-gate evidence are in
[the 7C results](evidence/gate-7/SUBGATE_7C_RESULTS.md), accepted by the owner on
2026-08-25. Subgate 7D is implemented locally at `3c2edd2`; its metadata-only
lifecycle, isolated permanent deletion, complete-history export, explicit content
truth, bounded UI, and full-gate evidence are in
[the 7D results](evidence/gate-7/SUBGATE_7D_RESULTS.md), accepted by the owner on
2026-08-25. Subgate 7E is implemented locally at `2e71369`; Project-aware matched
recovery, compatibility, corruption refusal, and full-gate evidence are in
[the 7E results](evidence/gate-7/SUBGATE_7E_RESULTS.md). The owner accepted the
complete Gate 7 evidence and closed the gate on 2026-08-26.

**Objective:** Represent the thing being built without creating an unnecessary
grouping layer.

**Dependencies:** Gate 6 accepted.

**Required work:**

- Validate Project, Artifact, and Artifact Revision terminology with real mixed-
  discipline examples.
- Define migration for every existing Asset: unassigned artifact, generated
  project, or explicit user-assisted grouping.
- Introduce a small relationship vocabulary only where it produces useful UI:
  `derived_from`, `source_of`, `documentation_for`, `assembly_of`, `attachment`.
- Define project provenance, export, deletion, restore, search, and permission
  inheritance before later multi-user work.
- Avoid arbitrary custom fields until common metadata is stable.

**Exit evidence:** representative existing libraries migrate without losing folder
organization; projects export and restore; relationships cannot orphan content;
the UI improves retrieval rather than merely exposing a graph editor.

**Owner checkpoint:** complete. The architecture package and 7A–7E evidence were
approved; Gate 7 closed on 2026-08-26.

**Rollback:** legacy artifact browsing remains available through the compatibility
window; project association is additive until verified.

### Gate 8 — Generalize trusted local application adapters

**Current execution:** `COMPLETE — ACCEPTED 2026-08-26`. Gate 7 was accepted on
2026-08-26 and the untouched `df62abf` entry harness passed. Current bridge/API/web
behavior and the owner-approved built-in, local custom-command,
Windows/Linux/macOS, compatibility, and subgate contract are recorded in
[the Gate 8 baseline](evidence/gate-8/BASELINE.md) and
[ADR 0012](adr/0012-versioned-local-application-adapters.md). The matched 8A–8C
implementation and full verification are recorded in
[the Gate 8 results](evidence/gate-8/GATE_8_RESULTS.md). The owner accepted the
complete verified Gate 8 implementation on 2026-08-26. Publication remains
prohibited.

**Objective:** Evolve slicer/LightBurn handoff into a safe `Open with` contract for
workshop applications.

**Dependencies:** Gate 1 handoff grants proven; stable file roles from Gates 6–7.

**Required work:** define adapter manifest, supported roles/extensions, platform
support, arguments, installation, diagnostics, approval, and revocation; prove the
contract with several built-in adapters before publishing an SDK.

**Exit evidence:** adapters cannot fetch arbitrary URLs, claim unsupported roles,
or launch unapproved executables silently; slicer and LightBurn behavior remains
compatible; failures are diagnosable without exposing secrets.

**Owner checkpoint:** complete. Built-in applications, constrained custom commands,
and the three-platform scope were approved, and the verified Gate 8 implementation
was accepted on 2026-08-26.

**Rollback:** adapter versions are explicit; the existing supported handoffs
remain available until replacements pass compatibility evidence.

### Gate 9 — Add descriptive machine context

**Current execution:** `ACCEPTED`. Gate 8 was accepted on
2026-08-26 and the untouched `fc29837` entry harness passed. Current prepared
metadata, export, and recovery behavior plus the approved descriptive-only profile,
relationship, lifecycle, and versioning boundaries are recorded in
[the Gate 9 baseline](evidence/gate-9/BASELINE.md). The owner approved those
recommendations without amendment on 2026-08-26; the accepted contract is recorded
in [ADR 0013](adr/0013-descriptive-machine-profiles.md). The schema-11 profile
lifecycle implementation and full verification are recorded in
[the Gate 9A results](evidence/gate-9/SUBGATE_9A_RESULTS.md). Owner acceptance is
recorded on 2026-08-27. The 9B schema gap and additive schema-12 recommendation are
recorded in [the Gate 9B baseline](evidence/gate-9/SUBGATE_9B_BASELINE.md). The
owner approved that amendment on 2026-08-27, and 9B is authorized. Publication
remains prohibited. The schema-12 implementation and complete repository evidence
are recorded in [the Gate 9B results](evidence/gate-9/SUBGATE_9B_RESULTS.md); the
owner accepted 9B on 2026-08-28. The bounded export, retrieval, and interface
recommendations are recorded in
[the Gate 9C baseline](evidence/gate-9/SUBGATE_9C_BASELINE.md). The owner approved
them without amendment on 2026-08-28; 9C implementation is authorized.
The format-2 exports, current-state Machine retrieval, Settings lifecycle, lazy
Artifact context, and complete repository verification are recorded in
[the Gate 9C results](evidence/gate-9/SUBGATE_9C_RESULTS.md). Owner acceptance is
recorded on 2026-08-28. The recovery-contract-4, compatibility, and closeout
recommendations are recorded in
[the Gate 9D baseline](evidence/gate-9/SUBGATE_9D_BASELINE.md). The owner approved
them without amendment on 2026-08-28. Recovery contract 4, Machine integrity and
historical-compatibility regressions, and the complete repository verification are
recorded in [the Gate 9D results](evidence/gate-9/SUBGATE_9D_RESULTS.md).
Implementation is verified at `002a5e7`; the owner accepted Gate 9D and closed Gate
9 on 2026-08-31. Complete traceability is recorded in
[the Gate 9 results](evidence/gate-9/RESULTS.md).

**Objective:** Let MakersVault describe relevant workshop machines without
becoming a machine controller.

**Dependencies:** prepared-print and project models stable.

**Required work:** define descriptive profiles and their relationship to prepared
metadata and artifacts; keep network credentials, telemetry, queues, job dispatch,
and start/stop controls out of scope.

**Exit evidence:** deleting or changing a profile does not damage prepared files;
exports preserve references; the interface never implies a job was sent.

**Owner checkpoint:** complete. The architecture and 9A–9D contracts and
implementations were accepted. Gate 10 was separately authorized on 2026-08-31.
The minimal common fields and categories, neutral Artifact association, exact
prepared target, explicit matching, archive/delete lifecycle, export/recovery
versioning, and 9A–9D sequence were approved without amendment on 2026-08-26. The
verified 9A implementation and additive schema 12 for 9B were accepted on
2026-08-27. The verified 9B implementation was accepted on 2026-08-28. The
verified 9C implementation was accepted on 2026-08-28. The
accepted schema-11 and schema-12 migrations will not be rewritten. Gate 9D was
verified at `002a5e7` and accepted on 2026-08-31.

**Rollback:** machine references are optional and nullable.

### Gate 10 — Deliver portable backup and storage abstraction

**Current execution:** `COMPLETE — ACCEPTED 2026-08-31`. Gate 9 was accepted
and the owner authorized Gate 10 to begin on 2026-08-31. Current backup, export,
import, storage, and recovery truth plus the proposed 10A–10E sequence are recorded
in [the Gate 10 baseline](evidence/gate-10/BASELINE.md). The archive compatibility,
clean-instance restore, encryption ownership, local-first storage interface, and S3
deferral recommendations were accepted without amendment on 2026-08-31 at the
[Gate 10 owner checkpoint](evidence/gate-10/OWNER_CHECKPOINT.md). Subgate 10A's
normative v1 format, independent streaming verifier, and adversarial evidence were
accepted on 2026-08-31 in [the 10A results](evidence/gate-10/SUBGATE_10A_RESULTS.md).
Subgate 10B's local ContentStore seam, maintenance-mode streaming exporter, atomic
verified publication, and regression evidence were accepted on 2026-08-31 in
[the 10B results](evidence/gate-10/SUBGATE_10B_RESULTS.md). The owner authorized
10C on the same date for clean-instance isolated staged restore. Gate 10C was
implemented, verified, and accepted in
[the 10C results](evidence/gate-10/SUBGATE_10C_RESULTS.md). The owner separately
authorized 10D on 2026-08-31 for the offline operator workflow and user-owned
standard encryption boundary. Gate 10D was implemented, verified, and accepted in
[the 10D results](evidence/gate-10/SUBGATE_10D_RESULTS.md). The owner separately
authorized 10E on 2026-08-31 for scale, compatibility, recovery, documentation,
storage-provider evaluation, and Gate 10 closeout evidence. Gate 10E is now
implemented and verified in [the 10E results](evidence/gate-10/SUBGATE_10E_RESULTS.md),
and consolidated [Gate 10 results](evidence/gate-10/RESULTS.md) were accepted by
the owner on 2026-08-31. Merge restore, S3 implementation, application key custody,
and live-instance import remain unopened. Gate 11 discovery was separately opened.

**Objective:** Make the vault independently verifiable and restorable before any
managed backup offering.

**Dependencies:** project/revision schemas stable enough to version an archive.

**Required work:** specify the `.mvault` manifest and versioning, checksums,
essential/derived/external content, streaming export/import, interruption recovery,
compatibility policy, optional encryption boundary, and storage interface; evaluate
S3-compatible storage only against these requirements.

**Exit evidence:** large representative vaults export without unbounded memory,
verify independently, restore on a clean compatible instance, and clearly report
missing no-copy content; the format is documented and usable without a paid
service.

**Owner checkpoint:** approve archive compatibility, encryption ownership, and
whether S3 support enters this gate.

**Rollback:** export is read-only. Import stages and verifies before committing a
new vault state.

### Gate 11 — Evolve authentication deliberately

**Current execution:** `GATE 11E-1 ACCEPTED — CLOSED 2026-09-05`.
Gate 10 was accepted and the owner directed Gate 11 to open on 2026-08-31. The
entry identity, token,
browser, route, ownership, audit, backup, and recovery truth plus the proposed
11A–11E+ sequence are recorded in
[the Gate 11 baseline](evidence/gate-11/BASELINE.md). The recommended shared-vault
tenancy, three fixed roles, admin-created enrollment, Argon2id bootstrap,
revocable cookie sessions, stopped-instance recovery, audit, and portability
decisions were accepted without amendment in
[the Gate 11 checkpoint](evidence/gate-11/OWNER_CHECKPOINT.md). Accepted
[ADR 0018](adr/0018-shared-vault-identity-and-authorization.md) governs the work.
Subgates 11A and 11B are accepted. The owner authorized 11C's accepted three-role
shared-vault permission model, deny-by-default classification and enforcement,
capability-aware UI, and focused evidence on 2026-09-01. Account administration,
recovery, durable audit, and later subgates remained unauthorized at that checkpoint.
Gate 11C is implemented and verified locally at `8b89bab`; the owner accepted it
and authorized 11D on 2026-09-02. Gate 11D is limited to the accepted
administration, recovery, audit, and portability contract. Later authentication
stages remain unauthorized.

**Objective:** Add multiple users only when authorization, recovery, and auditing
can be treated as a coherent system.

**Dependencies:** stable project ownership semantics, formal migrations, secure
single-admin baseline, and restore drills.

**Sequence:** users and password hashing -> sessions/revocation -> roles and object
authorization -> MFA/API keys -> OIDC/SSO. Each arrow may be split into its own
release gate.

**Exit evidence:** deny-by-default authorization tests cover every resource path;
ownership migration is explicit; account recovery and last-admin safety are
documented; audit records avoid secrets; security review covers sharing, imports,
exports, bridge grants, and backups.

**Owner checkpoint:** approve tenancy, sharing, registration, account-recovery, and
administrator policies before schema work.

**Rollback:** expand the single-admin record into the new user model without
removing recoverability; never down-migrate password or ownership data lossy.

Gate 11A is implemented at `0095f6e`, verified, and owner-accepted in
[the Gate 11A results](evidence/gate-11/SUBGATE_11A_RESULTS.md). Gate 11B is now
implemented at `5ca1a42` and locally verified in
[the Gate 11B results](evidence/gate-11/SUBGATE_11B_RESULTS.md), and the owner has
accepted it. Gate 11C is implemented at `8b89bab` and locally verified in
[the Gate 11C results](evidence/gate-11/SUBGATE_11C_RESULTS.md), and the owner has
accepted it. The Gate 11D contract comprises administrator-created accounts,
password/reset and recent-reauthentication policy, last-Administrator safety,
stopped-instance recovery, durable secret-free audit, raw-recovery session
revocation, and focused portability evidence, followed by its owner checkpoint.

Gate 11D-1 is implemented at `cf8fcad` and locally verified in
[the Gate 11D-1 results](evidence/gate-11/SUBGATE_11D1_RESULTS.md). Administrator-
created accounts, password/reset and recent-reauthentication policy,
last-Administrator safety, and affected-session revocation are complete. The owner
accepted 11D-1 and authorized 11D-2 on 2026-09-03. Gate 11D-2 is implemented at
`3c0fa69` and locally verified in
[the Gate 11D-2 results](evidence/gate-11/SUBGATE_11D2_RESULTS.md). Mandatory
durable secret-free audit and Administrator retrieval are complete. The owner
accepted 11D-2 by authorizing 11D-3 on 2026-09-03. Gate 11D-3 is implemented at
`3ed6991` and locally verified in
[the Gate 11D-3 results](evidence/gate-11/SUBGATE_11D3_RESULTS.md). Recovery contract
5, restored-session revocation/startup auditing, and stopped-instance existing-
Administrator recovery are complete. The owner accepted 11D-3 and authorized Gate
11E on 2026-09-03. The consolidated Gate 11 security/recovery matrix passed 118
tests and is recorded in [Gate 11 results](evidence/gate-11/RESULTS.md). Gate 11E is
governed by the accepted stronger-authentication design in
[its baseline](evidence/gate-11/SUBGATE_11E_BASELINE.md),
[owner checkpoint](evidence/gate-11/SUBGATE_11E_OWNER_CHECKPOINT.md), and accepted
[ADR 0019](adr/0019-origin-bound-passkey-mfa.md). Local 11E-1a adds the pinned
verifier, additive schema 17, recovery contract 6, recovery mutation, and `.mvault`
exclusion proof; its evidence is in
[the 11E-1a results](evidence/gate-11/SUBGATE_11E1A_RESULTS.md). The owner accepted
11E-1a on 2026-09-04 and authorized 11E-1b registration and self-management. Login
assertions and UI remain later sequential slices. Gate 11E-1b is now implemented and
verified locally in
[the 11E-1b results](evidence/gate-11/SUBGATE_11E1B_RESULTS.md). The owner accepted
11E-1b on 2026-09-04 and authorized 11E-1c. Gate 11E-1c is now implemented and
verified locally in
[the 11E-1c results](evidence/gate-11/SUBGATE_11E1C_RESULTS.md). The owner accepted
11E-1c on 2026-09-04 and authorized 11E-1d. Gate 11E-1d is implemented at `1a209aa` and
verified locally in
[the 11E-1d results](evidence/gate-11/SUBGATE_11E1D_RESULTS.md). It completes the
browser, policy, live reset, recovery revalidation, and security closeout boundary
without changing schema 17 or recovery contract 6. The owner accepted closeout on
2026-09-05 and deferred Gate 12 to the desktop version. Gate 13 was then authorized
and is active for the current track. Any push, tag, release, deployment, or
publication remains unauthorized.

### Gate 12 — Enable sustainable optional services

**Current execution:** `DEFERRED — DESKTOP VERSION`, by owner decision on
2026-09-05. This gate is carried into the desktop roadmap with its requirements and
exit evidence intact. It is not implemented or verified and is not a prerequisite
to the current track's Gate 13 audit. The free-core, portability, and non-lock-in
commitments in `SUSTAINABILITY.md` remain in force.

**Objective:** Add paid convenience only after the free product can perform and
verify the same core ownership/recovery functions locally.

**Dependencies:** Gates 10–11 as required by the specific service; an operational
support plan and demonstrated demand.

**Required work:** apply every test in `SUSTAINABILITY.md`; isolate service
entitlements from core local capability; define encryption, deletion, export,
support, incident response, cost, and shutdown/exit behavior.

**Exit evidence:** a customer can stop paying and retain a complete usable export;
self-hosted core behavior has no artificial file/project limits; service failure
does not corrupt the local vault; operational costs and support obligations are
understood.

**Owner checkpoint:** explicit business approval for every external service,
vendor, recurring cost, telemetry category, and price model.

**Rollback:** services are optional adapters around open formats. Disabling an
entitlement must not disable local access or export.

### Gate 13 — End-state audit and re-cock

**Current execution:** `IN PROGRESS — 13C SECURITY / PLATFORM / RELEASE QUALIFICATION`; the owner accepted 13B at
`2f61b37` on 2026-09-06 and authorized the [13C working record](evidence/gate-13/SUBGATE_13C_RESULTS.md).
The owner accepted 13A at
`c2e9f94` on 2026-09-05. Gate 13 was opened by owner direction
on 2026-09-05 at `236c0fd`. The [baseline](evidence/gate-13/BASELINE.md) sequences
13A truth inventory, 13B current lifecycle/harness qualification, 13C user-workflow
and release-readiness evidence, and 13D owner acceptance/re-baselining. The
[13B results](evidence/gate-13/SUBGATE_13B_RESULTS.md),
[traceability ledger](evidence/gate-13/TRACEABILITY.md), and
[security revalidation](security/GATE_13_REVALIDATION.md) retain their named evidence.
The expanded full verification passed on `2c68d70` and passes again with the
approved picker implementation's `76b526d` inputs: 351 API / 56 web tests and the
joined production-HTTPS lifecycle. The [record](evidence/gate-13/FOLDER_PICKER_RESULTS.md)
explicitly notes the mid-API-phase TypeScript-only correction, rather than claiming
the full invocation started at that revision. These results supplement the accepted 13A inventory. The
[archive guard](evidence/gate-13/ARCHIVE_GUARD_RESULTS.md) is implemented, not
awaiting approval. Historical clean language scans remain dated evidence. The
[security closeout review](evidence/gate-13/SECURITY_CLOSEOUT.md) now repeats all
scans on `c42614e`: production language scopes are clean, development-tool findings
are new, and the exact-image scan retains 181 API / 3 web matches without waivers.
The owner subsequently approved [S01/S02 hardening](evidence/gate-13/SECURITY_HARDENING_RESULTS.md)
at `ac4a051`: full verification and fresh language audits pass, the reviewed
outbound IDNA path is mitigated, and exact images retain all 181 API / 3 web matches.
Native residual dispositions remain open. The
[browser corrections](evidence/gate-13/BROWSER_FIX_RESULTS.md) verify request ordering
and Firefox trust; earlier Chromium runs miss unchanged startup/interaction
budgets. Subsequent [profiling](evidence/gate-13/CHROMIUM_PROFILE_RESULTS.md) identified
repeated folder options and driver costs. The owner-approved
[picker and measurement slice](evidence/gate-13/FOLDER_PICKER_RESULTS.md) is now
implemented: three fresh 600/104 Chromium runs pass unchanged enforced budgets and
three-engine functional tests pass. The separate 1,040-folder stress and detail-preview
timing failures remain open. The [residual diagnosis](evidence/gate-13/RESIDUAL_DIAGNOSIS.md)
confirms hidden sidebar-menu DOM and driver-query costs, while the exact detail
native wait and folder-list API latency remain unresolved. The owner-approved
[sidebar-menu slice](evidence/gate-13/SIDEBAR_MENU_RESULTS.md) implements lazy contents
and the scoped accessible locator at `82cb2cc`, with a new full-gate pass;
no historical failure or risk was waived by that slice. The later
[bounded API pass](evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md) at `c42614e`
passes 354 API tests; the owner's time-box decision defers remaining performance
tuning without changing measured failures. The browser/platform and
selected-release matrix remains 13C;
13B does not reuse old timing as current evidence. Gate 12 remains desktop follow-up
with outstanding evidence, not delivered work. No new release candidate or
publication is authorized.

**Objective:** Demonstrate that the strategy documents' goals are met, record what
was learned, and deliberately create the next roadmap.

**Required evidence:** trace each product promise, invariant, roadmap capability,
security obligation, portability requirement, and sustainability commitment to
current behavior and tests; perform a clean install, representative upgrade,
disaster restore, portable export/import, and trust-boundary review.

**Exit:** every goal is `VERIFIED`, explicitly `SUPERSEDED` by owner decision, or
carried into the next roadmap with a reason and dependency. No silent omission is
allowed.

**Owner checkpoint:** accept the achieved end state and approve the newly
re-baselined roadmap. The runbook then returns to Gate 0 semantics for the next
major cycle.

## 9. Cross-cutting change runbooks

### 9.1 Database schema change

1. Name the old and new schema versions.
2. Create a sanitized prior-version fixture and matched storage tree.
3. Back up database and managed storage together.
4. Expand with nullable/default-safe structures.
5. Backfill in bounded, restartable units where data volume can be large.
6. Verify row counts, references, checksums, and application invariants.
7. Switch reads, then writes, with a documented compatibility window.
8. Test interruption at each phase and rerun safely.
9. Contract old structures only in a later release after restore evidence.
10. Record whether rollback is a reverse migration or snapshot restore.

SQLite foreign-key enforcement, transaction boundaries, and index behavior must
be tested explicitly rather than inferred from model declarations.

### 9.2 Database plus filesystem mutation

SQLite and the filesystem do not share an atomic transaction. Every operation
that changes both must use an explicit state machine:

```text
validate -> stage bytes -> verify -> commit metadata -> publish bytes -> reconcile
```

The exact order may vary, but failure at every boundary must leave either the old
state intact or a detectable, recoverable staged state. Use same-filesystem atomic
rename where available. Never overwrite the only copy before verification.

A reconciliation command/job must detect at least:

- Metadata pointing to missing content.
- Unreferenced staged or managed content.
- Size/hash mismatch.
- Missing external no-copy sources.
- Prepared payloads accidentally exposed as ordinary attachments.

### 9.3 Background or expensive work

Any hashing, preview, scan, import, backup, or restore job that can outlive one HTTP
request uses durable states:

```text
queued -> running -> succeeded
                  -> failed (reason, retryability)
                  -> canceled
```

Jobs require idempotency keys or equivalent duplicate protection, progress that
does not grow without bound, time/resource budgets, retry policy, and stale-worker
recovery. Moving work to a queue does not by itself make it safe.

### 9.4 API and client contract change

- Add fields before requiring them.
- Keep visibility and authorization decisions server-side.
- Never use a generic session bearer as a durable file URL.
- Return stable error codes for partial/bulk operations.
- Test an older supported client against the new API when compatibility is
  promised.
- Version the contract before a breaking change is unavoidable.

### 9.5 Import or parser change

- Treat remote servers, archives, models, images, and embedded metadata as hostile.
- Validate extension, detected type, size, count, nesting, expansion, and elapsed
  work independently.
- Validate each redirect and actual connection target.
- Keep credentials scoped to the intended destination and out of logs.
- Process failures per item and preserve an audit/report record.
- Prefer isolation and bounded fallbacks over attempting every file.

### 9.6 Release change

A release candidate is immutable. If its evidence fails, create another candidate.
For each candidate record source revision, dependency locks, container digests,
bridge checksums, schema range, supported upgrade origins, test results, known
limitations, and recovery instructions.

## 10. Evidence matrix

| Area | Minimum evidence |
|---|---|
| API/domain | Unit tests for policy; integration tests against a temporary SQLite database and storage tree. |
| Migration | Fresh install, oldest supported fixture upgrade, interrupted rerun, integrity queries, matched restore. |
| Web | Production build, type check, component/interaction tests, supported-browser smoke tests. |
| Preview/performance | Versioned corpus, repeatable script, timing/memory/concurrency/cache report. |
| Import/security | Malicious redirect, DNS, archive, symlink, oversized, malformed, and timeout fixtures. |
| Bridge | Protocol parser tests, origin/grant/file-role restrictions, platform build, local-launch smoke test. |
| Containers | Fresh deploy, upgrade deploy, non-root/runtime health, persistent-volume restart, configured reverse proxy. |
| Backup/export | Clean-machine restore, checksum failure, interruption, missing external source, version compatibility. |
| Documentation | Commands executed as written by someone starting from the declared prerequisites. |

Manual evidence is acceptable only where automation is impractical, and must name
the operator, build, environment, steps, expected result, actual result, and date.

## 11. Risk register

| Risk | Impact | Active mitigation gate |
|---|---|---|
| No formal migration/version framework | Data loss or irreproducible upgrades | Gate 0 |
| Dirty/generated artifacts obscure release source | Unreproducible builds and accidental data commits | Gate 0 |
| Duplicate deployment manifests drift | Operators run different architectures unknowingly | Gate 0 |
| Published credentials/signing fallback | Account and data compromise | Gate 1 |
| Broad bridge/custom-URI authority | Workstation file execution boundary abuse | Gate 1 |
| Hostile import/archive/image/model | SSRF, resource exhaustion, parser exposure | Gates 1–2 |
| Client-heavy preview pipeline | Frozen UI and repeated expensive work | Gate 2 |
| Database/filesystem partial failure | Missing, orphaned, or mismatched content | Gates 0 and 5; all data gates |
| Mounted no-copy dependencies | Incomplete backup and broken references | Gates 4–5 and 10 |
| Route/UI concentration | Regression risk and hard-to-test changes | Incremental extraction in each gate |
| Premature Project rewrite | v5.1 delay and unsafe migration | Gates 5–7 sequencing |
| Multi-user without authorization model | Cross-user data exposure | Gate 11 |
| Documentation drift | Decisions and implementation diverge | Every re-cock |
| Hosted service before portability/security | Lock-in and operational trust failure | Gates 10–12 |
| Experimental camera/AI monitoring leaks LAN endpoints, secrets, or incident images | Privacy, network pivot, or operator trust failure | Independent experimental monitoring discovery; never a Gate 6 dependency |

Risks are never closed only because a feature shipped. Closure requires evidence;
accepted residual risk names its owner, reason, review date, and containment.

## 12. Architecture decision records

Material decisions use short ADRs under `docs/adr/` when their gate begins. Each
ADR records context, verified facts, decision, alternatives, consequences,
migration, rollback, and superseding conditions.

The initial required ADR queue is:

1. Canonical development and production deployment manifests.
2. SQLite schema versioning and migration mechanism.
3. Secure first-run single-admin configuration.
4. File-scoped browser-to-bridge handoff grants.
5. Preview budgets and persisted preview state.
6. Content identity and duplicate-suggestion semantics.
7. Artifact/revision metadata and attachment ownership.
8. Trash retention and permanent deletion.
9. Existing-Asset to Project/Artifact migration.
10. Portable archive compatibility and encryption boundary.
11. Multi-user tenancy and authorization model —
    [ADR 0018](adr/0018-shared-vault-identity-and-authorization.md), accepted
    2026-08-31; implemented through Gate 11.
12. Origin-bound password-plus-passkey MFA —
    [ADR 0019](adr/0019-origin-bound-passkey-mfa.md), accepted 2026-09-04;
    implemented through accepted Gate 11E-1.

An ADR describes a decision; it does not replace implementation evidence.

## 13. Strategy traceability

This matrix prevents a goal from disappearing between documents and
implementation. Gate 13 closes the roadmap only when the listed proof exists.
The current goal-by-goal dispositions, named tests, gaps, and carry-forward
dependencies are in [Gate 13 traceability](evidence/gate-13/TRACEABILITY.md).

| Source commitment | Delivery gates | Final proof |
|---|---|---|
| Preserve product boundaries and remain the workshop source of truth | All gates | Invariant regression audit and representative end-to-end workflows |
| Fast, resilient v5.1 library | Gates 2 and 5 | Published benchmark and pathological-file results |
| Easy organization at scale | Gates 3 and 5 | Large-library navigation and bulk-workflow tests |
| Models with context, visible supporting files, hidden prepared payloads | Gates 3–5 | Visibility, handoff, download/export, and migration tests |
| Mounted import observability | Gates 4A and 5 | Repeatable scan reports and no-copy safety tests |
| Secure defaults and trustworthy deployment | Gates 0, 1, and 5 | Revalidated security report, abuse tests, and fresh-production smoke test |
| Upgrade, backup, and recovery confidence | Gates 0 and 5 | Representative upgrade and matched database/storage restore |
| Content identity and provenance | Gate 4B, or first subgate of Gate 6 | Bounded hashing, integrity, and duplicate-suggestion evidence |
| Artifact history and recoverable deletion | Gate 6 | Revision, Trash, export, and restore evidence |
| `Project -> Artifact -> Artifact Revision` without `AssetGroup` | Gate 7 | Existing-library migration and project recovery evidence |
| Useful relationships and project provenance | Gate 7 | Retrieval workflows and round-trip export evidence |
| Safe general local application handoff | Gates 1 and 8 | Scoped-grant and multi-adapter conformance tests |
| Descriptive machine context without control | Gate 9 | Boundary and export tests; no command/telemetry authority |
| Optional advisory print-failure alerts without printer control | Independent post-v5.1 experiment | Disabled-by-default provider isolation, measured detection quality, secret/privacy review, Discord delivery, and proof that monitor failure cannot impair the vault |
| Open, portable backup and storage evolution | Gate 10 | Independently documented and verified `.mvault` round trip |
| Deliberate authentication evolution | Gates 1 and 11 | Authorization, recovery, session, and audit test suites |
| Complete open source plus paid convenience | Gate 12 — deferred to desktop version, owner decision 2026-09-05 | Free-core commitments remain binding; service decision tests and non-lock-in exit drill remain outstanding for desktop delivery |
| All confirmed security findings resolved or explicitly accepted | Gates 0–2, 5, 8, 10–11 | Finding-by-finding evidence ledger with no unowned residual risk |

## 14. Re-cock protocol

After each gate is accepted:

1. Freeze the evidence against a commit or immutable release candidate.
2. Update the truth ledger with what is now verified, superseded, or still assumed.
3. Update the current component/data/deployment diagrams.
4. Reconcile the strategy, v5.1 scope, roadmap, security analysis, runbook, README,
   and operator documentation against the implementation.
5. Re-score risks and remove only those closed by evidence.
6. Record new debt and discoveries without silently expanding the completed gate.
7. Re-evaluate dependencies and the next gate's entry conditions.
8. Present owner decisions and scope choices together with evidence and a
   recommendation.
9. Mark the next gate `READY`, split it, reorder it, or leave it `BLOCKED`.
10. Update this document's baseline date and source revision.

The next gate begins only after this reset. A schedule may change; the product
invariants and evidence standard do not change silently.

## 15. Immediate next action

Gate 13B was accepted at `2f61b37` on 2026-09-06. The approved picker at `76b526d`
and subsequent [sidebar-menu slice](evidence/gate-13/SIDEBAR_MENU_RESULTS.md) at
`82cb2cc` are implemented locally. Review their retained results and every failed
sample; the [residual diagnosis](evidence/gate-13/RESIDUAL_DIAGNOSIS.md) remains
historical evidence, not a claim that all waits were fixed by reducing DOM.
The subsequent [bounded API pass](evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md)
is implemented at `c42614e`. The owner explicitly prefers to stop after this pass
even if stalls/API latency are not fully resolved. Carry G13-01 as deferred
performance tuning; do not start another investigation without renewed direction.
Historical and current timing failures remain failures, with unchanged budgets and
authentication controls. The owner-authorized
[security closeout review](evidence/gate-13/SECURITY_CLOSEOUT.md) is documented;
its S01/S02 proposal was explicitly approved and is now
[implemented and verified](evidence/gate-13/SECURITY_HARDENING_RESULTS.md) at `ac4a051`.
The [S04 decision checkpoint](evidence/gate-13/SECURITY_RESIDUAL_DECISIONS.md)
now covers every native CVE. The owner approved its bounded containment slice,
[implemented and verified](evidence/gate-13/SECURITY_CONTAINMENT_RESULTS.md) at `ea17494`,
preserving ownership, uploads and trusted recovery. The September 12
[E11/R59 owner event and C6 reopenings](evidence/gate-13/SECURITY_OWNER_ACCEPTANCE.md)
remain immutable historical decisions for the old images. The owner subsequently
approved the six-package stable refresh, now
[implemented and fully verified](evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md)
at `6306ccf`: exactly six signed package changes, 424 API tests, 58 reexecuted web
tests, current HTTPS lifecycle and exact-image containment. Fresh scans retain
**189 API / 3 web matches**: the newer database adds seven CVEs, while 20 targeted
vendor-fixed-version records still conflict with scanner unknown ranges. No
finding is suppressed and old-image E/R approvals do not transfer automatically.
The subsequent [vendor/byte reconciliation](evidence/gate-13/SECURITY_RECONCILIATION_RESULTS.md)
verifies **26 fixes already installed** (20 targeted plus six new PCRE2 IDs), using
the current primary feed, authenticated package archives and 931 runtime file
comparisons. No further package update is needed for that group. Its 28 historical
scanner matches remain visible; the precise upstream metadata cause is unproven.
The 87 native IDs now comprise **26 fixed, two proposed exclusions, 52 pending
new-image exceptions and seven unresolved holds**. No new waiver was granted.
The [current-image decision package](evidence/gate-13/SECURITY_CURRENT_IMAGE_DECISION.md)
is prepared: fresh known Debian records are unchanged, exact-image components
reconfirmed, and all 52 residual rationales individually reviewed. The BusyBox CNA
is unchanged, but current Alpine fix status could not be confirmed and needs
explicit acknowledgment. **Next checkpoint: owner decision on E2/R52 under C1–C7,
including that evidence gap; keep H7 unaccepted.** Only after approval record a new
exact-image event, then continue the bounded H review. No automatic waiver transfer
or authority for unreviewed remediation. Do not repeatedly rebuild to chase a
clean count. Preserve
the earlier October 12 00:00 America/New_York deadline, or earlier freeze/13D/C6
trigger; no renewal, extension or distribution migration is authorized here.
Current raw evidence is durable/private; historical temporary artifacts are not
recovered. Remaining H source/build gaps, physical/native-platform and operator/
release readiness follow. S04/G13-04 and Gate 13C closeout remain open.
Gate 12 remains deferred to desktop. End-state acceptance and the next roadmap remain 13D owner
decisions; the frozen Gate 5 release baseline is unchanged. Push, tag, image
publication, deployment, and release remain separately gated. Keep the
[print-monitoring experiment](EXPERIMENTAL_PRINT_MONITORING.md) independent and
disabled by default.
