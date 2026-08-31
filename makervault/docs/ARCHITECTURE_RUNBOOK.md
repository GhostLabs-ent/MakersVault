# MakersVault Architecture and Delivery Runbook

**Status:** Governing working document

**Baseline date:** 2026-08-22

**Committed baseline:** `main` at `c004c60`

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
  React 18 + TypeScript + Vite + Tailwind + Three.js/OCCT
                 |
                 | HTTP/JSON and file responses
                 v
FastAPI application
  route-heavy API + auth + import/storage/model services
          |                         |
          v                         v
SQLite metadata              Managed filesystem storage
                              + external mounted no-copy files

Browser custom protocol link
          |
          v
Go desktop bridge -> local slicer or engraving application
```

The target is a well-factored modular monolith, not a fleet of microservices.
Background work may run in a separate process later, but domain boundaries are to
be made explicit before deployment boundaries are multiplied.

### 5.3 Truth ledger

| ID | State | Current truth | Primary evidence | Consequence |
|---|---|---|---|---|
| T-001 | `VERIFIED` | The API is Python 3.11, FastAPI, SQLModel, and SQLite by default. | `api/requirements.txt`, `api/db.py` | SQLite-safe migrations and recovery are release requirements. |
| T-002 | `VERIFIED` | The React/Vite client keeps card parsing, decompression, normal calculation, rendering, and LightBurn extraction in terminable workers behind one shared bounded queue; successful cards become persisted static thumbnails. | `web/src/lib/previewJobs.ts`, preview workers, Gate 2 candidate evidence | New preview formats must join the bounded queue and persistence contract rather than add main-thread card parsers. |
| T-003 | `VERIFIED` | Production web packaging is a static build served by unprivileged Nginx with runtime API configuration. | `web/Dockerfile`, `web/nginx.conf`, `web/40-runtime-config.sh` | The former production Vite-server finding is resolved in the Gate 0 baseline. |
| T-004 | `VERIFIED` | Production deployment separates `/app/data` and `/app/storage`; development layout differs. | Docker Compose files | Backup instructions must distinguish production and development. |
| T-005 | `VERIFIED` | Production Compose requires explicit credentials, and API startup independently rejects missing, published, short, or reused secrets. Development fixtures require an explicit non-production mode. | `api/security_config.py`, Compose manifests, Gate 1 slice 1A evidence | Authentication configuration is fail-closed; later Gate 1 slices still govern network, token, and bridge exposure. |
| T-006 | `VERIFIED` | Auth is one environment-configured administrator with 12-hour HS256 JWTs. There is no user, role, revocation, or MFA model. | `api/auth.py`, models | Multi-user security is a later dedicated architecture gate. |
| T-007 | `VERIFIED` | Some file handoffs place bearer material in URLs, including custom-protocol handoff. | API schemas/routes and bridge code | Replace broad reusable bearer URLs with narrow, short-lived grants. |
| T-008 | `VERIFIED` | The bridge accepts custom protocol input, downloads a URL, caches the result, and launches a local application. | `slicer-bridge` source | The bridge is a workstation trust boundary and needs protocol hardening. |
| T-009 | `VERIFIED` | Startup uses an ordered, immutable SQLite migration ledger at schema version 12, with dependency locking and fail-closed version/name checks. Schemas 6–12 add revision/content truth, immutable workflows, recoverable Trash, Projects, descriptive Machine profiles, and optional Artifact-machine context additively. | `api/migrations.py`, `api/db.py`, API migration tests | Larger model changes must extend this migration mechanism and retain old-database fixtures. |
| T-010 | `VERIFIED` | Metadata is split between SQLite and filesystem content; updates are not one atomic transaction. | API storage and asset services | File mutations require staging, compensation, and reconciliation. |
| T-011 | `VERIFIED` | Current records include `Folder`, `Asset`, `Project`, `ProjectMembership`, `ProjectRelationship`, `MachineProfile`, `ArtifactMachine`, immutable `ArtifactRevision`, scoped `AssetFile`, durable content jobs, `TrashPurgeOperation`, and `AppConfig`; several bounded journal/result structures are stored as JSON text. | `api/models.py`, Gate 6 evidence, Gate 7A/7C evidence, Gate 9A/9B evidence | Lifecycle/export work must build on these records rather than replace data in place. |
| T-012 | `VERIFIED` | Managed historical revisions, thumbnails, bundles, and purge quarantine use explicit storage layouts; no-copy revision records reference external paths. | revision/file/Trash services and Gate 6D recovery evidence | Backup completeness and storage invariants are enforced by schema-aware matched-pair verification. |
| T-013 | `VERIFIED` | Mounted scans deduplicate primarily by source path and report details to process logs. | `api/mount_import.py` | A durable scan job/report is required for v5.1 observability. |
| T-014 | `VERIFIED` | URL import performs important address checks, but redirect and DNS behavior still need adversarial tests. | `api/url_utils.py`, security review | SSRF safety is proven by tests at the security gate, not presumed. |
| T-015 | `VERIFIED` | Prepared payloads and visible supporting files already have distinct roles and response behavior. | `AssetFile`, prepared-print and ZIP services | Visibility/download invariants need regression tests. |
| T-016 | `VERIFIED` | The repository owns a unified `make verify` harness and GitHub Actions workflow covering API migrations/routes, web type-check/tests/build, bridge tests/build, Compose validation, and container smoke behavior. | `Makefile`, `.github/workflows/ci.yml`, Gate 0 evidence | Later gates extend the shared harness and cannot substitute undocumented local checks. |
| T-017 | `VERIFIED` | Large route and UI files concentrate behavior in `api/main.py` and `AssetGrid.tsx`. | source inventory | New work should extract seams incrementally; no rewrite gate is authorized. |
| T-018 | `VERIFIED` | Canonical local and production Compose manifests are named; compatibility aliases are tested; generated/runtime artifacts are ignored and absent from Git tracking. | ADR 0001, Compose validation, root `.gitignore`, Gate 0 evidence | Deployment and repository ownership drift is now detectable by the shared harness. |
| T-019 | `DECIDED` | v5.1 is single-admin; multi-user/MFA/SSO is deferred. | product strategy and v5.1 scope | Security analysis statements that assume v5.1 multi-user are stale. |
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
| T-038 | `VERIFIED` | Local Gate 10C imports independently verified `.mvault` v1 archives only into absent or compatible empty schema-12 targets, reconstructs records and streamed bytes in isolation, assigns SHA-256-derived provider-safe keys, marks external references unavailable, audits the staged pair, and publishes storage first/SQLite last behind a restart-safe rollback journal. | `api/mvault_import.py`, `docs/evidence/gate-10/SUBGATE_10C_RESULTS.md`, focused restore regressions | Owner acceptance is pending. Merge/replacement/live import, S3, encryption/key custody, publication, and Gate 10D remain unauthorized. |

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

This is a logical target, not a finalized table schema. Gate 6 decides revision
ownership rules; Gate 7 decides project migration and relationships. In
particular, whether a supporting document belongs to an artifact or one revision
must be proven through real workflows before tables are committed.

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

**Current execution:** `IN PROGRESS — 10C OWNER CHECKPOINT`. Gate 9 was accepted
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
10C on the same date for clean-instance isolated staged restore. Gate 10C is now
implemented and verified in [the 10C results](evidence/gate-10/SUBGATE_10C_RESULTS.md),
with owner acceptance pending. Merge restore, S3, encryption/key custody,
live-instance import, and 10D remain unopened.

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

### Gate 12 — Enable sustainable optional services

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
11. Multi-user tenancy and authorization model.

An ADR describes a decision; it does not replace implementation evidence.

## 13. Strategy traceability

This matrix prevents a goal from disappearing between documents and
implementation. Gate 13 closes the roadmap only when the listed proof exists.

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
| Complete open source plus paid convenience | Gate 12 | Sustainability decision tests and non-lock-in exit drill |
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

Review [the verified Gate 9D results](evidence/gate-9/SUBGATE_9D_RESULTS.md) and
accept Gate 9 closeout before opening Gate 10. Keep the
[print-monitoring experiment](EXPERIMENTAL_PRINT_MONITORING.md) independent and
disabled by default; it is not part of Gate 9.
