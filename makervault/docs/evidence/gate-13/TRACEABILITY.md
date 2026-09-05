# Gate 13 strategy and invariant traceability

**Date:** 2026-09-05

**Baseline:** `236c0fd` / application `1a209aa`, schema 17

**Status:** 13A evidence review; final Gate 13 acceptance pending

## Reading this ledger

`VERIFIED` below is limited to the named source/test/runtime layer. It does not
mean release-qualified, supported on every platform, or owner-accepted at Gate 13.
Historical Gate 5 benchmarks remain evidence for `f6ff55b`, not current schema-17
performance. The [13A results](SUBGATE_13A_RESULTS.md) name current executions.
Carry-forward IDs have reasons, dependencies, and a review checkpoint below.

Source commitments are from [Product Strategy](../../PRODUCT_STRATEGY.md),
[Competitive Strategy](../../MakersVault_v5.1_Competitive_Strategy(1).md),
[v5.1 Scope](../../V5.1_SCOPE.md), [Roadmap](../../ROADMAP.md),
[Sustainability](../../SUSTAINABILITY.md), and runbook sections 2, 3, 6, and 13.

## Product and architecture coverage

Test paths in this table are relative to `api/tests/` unless qualified otherwise.

| ID / commitment | Current behavior and direct proof | Remaining evidence or disposition |
|---|---|---|
| P01 — find a large mixed library without stalls | Bounded worker previews, static thumbnail reuse, pagination; `test_preview_policy.py`, `test_api_smoke.py`; historical Gate 2/5 corpus and browser reports | G13-01: repeat current cold/warm/detail/LightBurn and organization timing; no new performance claim yet |
| P02 — modern folder navigation and bulk organization | Folder-scoped naming, nested lookup, conflicts, breadcrumbs, explicit selected IDs; `test_organization.py`, web `organization.test.ts`; Gate 3/5 browser evidence | G13-01 for current browser workflow; C04 for server-wide selection, narrow/touch/accessibility and density polish |
| P03 — editable identity, metadata, configurable paths | Names, creator/collection/tags/notes/provenance and managed-storage templates; `test_organization.py`, `test_revisions.py`, `test_content_identity.py` | Renaming never moves immutable historical or external no-copy bytes; C05 for custom fields and automatic source artwork |
| P04 — supporting documents and prepared context | Visible supporting files, internal prepared role and supplied summary, scoped slicer handoff; `test_handoff.py`, `test_revisions.py`, `test_project_lifecycle_export.py` | No thumbnail-upload chore or machine operation; browser reprise in G13-01 |
| P05 — observable copy/no-copy imports | Restartable scans, bounded failures/counts, repeat-path safety; `test_mount_scan.py`, `test_mount_security.py` | G13-01 current mounted browser drill; C04 continuous watching/exclusions/live per-file progress |
| P06 — content identity, provenance and trust | SHA-256 ingest/backfill/changed-state and suggestion-only duplicates; `test_content_identity.py`, `test_revisions.py` | VERIFIED at API/test layer; no automatic repair or merge promise |
| P07 — revisions and recoverable deletion | Immutable linear revisions; restore-as-new; metadata-only Trash; explicit journaled purge and accepted retention choices; `test_revisions.py`, `test_trash.py` | VERIFIED at API/test layer; rollback and whole-instance workflow remain G13-02 |
| P08 — Project → Artifact → Revision and useful relationships | Optional many-to-many Project membership, bounded canonical relationships, provenance/lifecycle/history exports; `test_projects.py`, `test_project_relationships.py`, `test_project_lifecycle_export.py` | ADRs 0009–0011 govern the concrete model; legacy Asset projection remains, not an `AssetGroup`. No arbitrary graph, separate ContentBlob table, or byte-deduplication claim |
| P09 — safe broad local-tool workflows | Versioned built-in/local adapters and exact-file grants; `test_handoff.py`, web `handoff.test.ts`, bridge adapter/handoff/install contract tests | C03 real workstation qualification; C05 dedicated KiCad integration/community SDK not delivered by FreeCAD/Inkscape support |
| P10 — descriptive Machine context | Six categories, explicit links and portable snapshots; `test_machines.py`, `test_machine_relationships.py`, `test_machine_portability.py` | VERIFIED at API/test layer; no telemetry, safety certification, compatibility inference, or commands |
| P11 — independent free backup/export/restore | Raw format 1/contract 6; local ContentStore; schema-17 content export → verified `.mvault` v1 → clean schema-12 import; recovery/portable/content-store suites and current 1,200-Artifact drill | G13-02 full startup/upgrade/restore sequence; C02 for S3, live/merge import, browser jobs and synchronization |
| P12 — secure defaults and trustworthy upgrades | Fail-closed secrets, bootstrap identity, protected cookie sessions, three roles, audit, optional passkeys, stopped recovery; current complete test gate and fresh-container smoke | G13-02 current operator lifecycle; G13-03 current exact-image release; finding-by-finding [security ledger](../../security/GATE_13_REVALIDATION.md) |
| P13 — deliberate authentication evolution | Accepted ADRs 0018/0019 implemented; identity/session/authorization/account/audit/passkey/recovery suites | C01 API keys/OIDC and alternate recovery/factors; private tenancy intentionally excluded, not accidentally omitted |
| P14 — complete free core plus optional paid convenience | Local organization/history/projects/adapters/export/backup work without entitlement checks; current tests run without any paid service | **DECIDED:** Gate 12 deferred to desktop. C06 carries all service/support/donation/vendor/exit decisions and outstanding proof; not VERIFIED service delivery |
| P15 — optional advisory failure alerts | Documented independent disabled-by-default discovery only, `EXPERIMENTAL_PRINT_MONITORING.md` | C07: no provider/feed/model/Discord implementation or accuracy claim |
| P16 — maintainable modular monolith | Extracted identity, revision, Project, Machine, storage and recovery services; single API process and SQLite | C08: route/UI concentration and remaining concrete filesystem seams; section 6 logical target is not a claim of complete layering |
| P17 — versioned, reproducible, recoverable public release | Accepted Gate 5 immutable image/bridge/SBOM/normalized-rebuild evidence; current release-contract check | G13-03: no later matched artifact qualification or publication; frozen scope remains authoritative until owner changes it |

## All ten non-negotiable invariants

| Runbook invariant | Proof and boundary |
|---|---|
| I01 — no slicing, fabrication jobs or machine control | Handoff grants select supplied files; descriptive Machine schemas/routes; API/bridge handoff and Machine tests. Source-boundary review, not a hardware test |
| I02 — prepared payload internal | Separate roles in handoff, supporting-file lists and normal ZIP exports; revision/Project export tests preserve the accepted archive visibility boundary |
| I03 — supporting documents visible/retrievable | Supporting selection/download checks and revision/Project export tests; current browser repeat remains G13-01 |
| I04 — automatic previews, no manual thumbnail obligation | Embedded/cache/worker/fallback policy; preview policy/API tests; automatic generated-thumbnail persistence is not a manual user-upload feature |
| I05 — never rewrite mounted no-copy libraries | Descriptor/symlink tests, mounted scan ownership, revision/Trash external-preservation tests, portable external-remount truth |
| I06 — duplicate suggestions, never silent merge/delete | Content identity tests and immutable identical-replacement no-op; no automatic deduplication mutation |
| I07 — original files/metadata portable without subscription | Independent verifier, current scale export/import/re-export, corruption/nonempty-target tests; external bytes explicitly outside vault ownership |
| I08 — local integrations confer no hidden control | API/bridge grant separation, role/extension/catalog/origin restrictions and constrained local arguments; no remote executable or shell authority |
| I09 — no temporary AssetGroup | Actual Project membership and ArtifactRevision migration tests; accepted ADRs 0009–0011 specialize the original conceptual hierarchy |
| I10 — hostile file cannot monopolize library | Import/archive/image/preview budgets and failure persistence; adversarial API tests; current browser timing requires G13-01 |

## Open audit findings — repair inside Gate 13

These are verification gaps, not demonstrated data loss or a discovered auth bypass.
Owner: MakersVault maintainer; implementation/evidence: local delivery work under
the next accepted slice. Re-review at that slice and again at 13D.

| ID | Source evidence / effect | Required next proof |
|---|---|---|
| G13-01 | `benchmarks/preview/preview-baseline.mjs`, organization and mounted-scan `.mjs` harnesses read login `.token` and send Bearer auth; current `test_sessions.py` explicitly rejects those mechanisms | 13B: cookie/CSRF test helpers with no production bypass; 13C: current browser/corpus/mount matrix with exact baseline and fixture |
| G13-02 | `scripts/gate5-recovery-drill.sh` still asserts post-upgrade schema 5. Current API migration/recovery tests do not constitute one production-Compose upgrade → backup → independent restore → rollback → portable-startup drill | 13B: dedicated current-build disposable lifecycle drill; keep old candidate evidence intact; include schema-17 security state and startup behavior |
| G13-03 | `scripts/release-candidate-smoke.sh` reads `.token`, sends Bearer auth, and asserts schema 5; `make verify-release` is a static contract check, not exact-image runtime qualification | 13B: current smoke contract; 13C: owner-selected immutable scope/revision and matched-image/bridge/reproducibility evidence before any release claim |
| G13-04 | Original security ledger still assigns removed browser JWT/session/RBAC behavior to future Gate 11; dependency audit dates are historical | Current finding dispositions reconciled in 13A; 13C repeats advisory scans/operator trust review and records explicit residual decisions |

## Carry-forward register — next-roadmap proposal, not new authorization

Owner for each row is the MakersVault maintainer; the next review is **Gate 13D**
unless an earlier checkpoint is named. Existing accepted boundaries remain binding;
new prioritization below is proposed until the owner accepts the re-baselined roadmap.

| ID | Unmet/deferred commitment and reason | Dependency / destination / required evidence |
|---|---|---|
| C01 | API keys/OIDC/SSO, TOTP/passwordless/recovery codes, invitations/email, custom roles/private ACLs: intentionally outside accepted shared-vault/passkey scope | Separate identity ADR and owner need; migrations, grant scope/revocation, recovery, audit and abuse proof before implementation |
| C02 | S3, managed/provider storage, synchronization, live/merge portable import and browser job orchestration: local-first/no-go provider decision and stronger mutation boundaries | Portability/provider gate reopened only with demand and atomicity/capacity/failure/exit evidence; application never takes custody of `age` keys |
| C03 | Physical security keys/platform prompts, Firefox/WebKit passkey ceremonies, OS-specific real-app launch/signing/notarization: Docker/virtual/cross-build evidence is insufficient | Review at 13C with owner-supplied test hardware/OS access or explicitly bounded supported release claims; do not automatically defer release blockers to desktop |
| C04 | Server-wide select-all, continuous NAS watching/exclusions/live progress, mobile/touch/accessibility and density polish: accepted P1/scale boundaries | Dedicated UX/API scopes with bounded jobs and representative device/assistive-tool evidence; existing loaded-ID/no-copy semantics preserved |
| C05 | Custom metadata, dedicated KiCad support, public adapter SDK/marketplace, automatic source-site artwork and expanded format previews: strategic direction beyond delivered integrations | Demonstrated workflows, schema/adapter/source-rights and parser-isolation decisions; no manual-thumbnail requirement or unsafe STEP preview fallback |
| C06 | **Gate 12 deferred to desktop by owner on 2026-09-05**; optional support links/donation setup and paid hosting/backup/storage services not completed by policy text | Desktop roadmap must retain all Sustainability decision tests, explicit vendor/cost/telemetry/business approval, export-after-cancellation, service-failure isolation and operational/shutdown/support evidence |
| C07 | Advisory camera/AI/Discord experiment remains discovery-only and disabled | Independent experiment gate; authorized input/provider, measured false/missed alerts and latency/resource use, secret/privacy/isolation review; never printer control |
| C08 | Architecture debt and operational limits: concentrated API/UI, residual local-path coupling, single-process throttling/policy locks, indefinite audit retention | Incremental tested extraction and explicit capacity/retention design before topology or retention changes; no microservice/schema contraction inferred |
| C09 | Public rollout and coordinated bridge/server distribution remain unauthorized | Explicit release scope/revision and known-limitations decisions after Gate 13 evidence; publication permission separate from local acceptance |

The explicitly deprioritized printer routing/scheduling/control, filament and
maintenance accounting, broad telemetry/compatibility matrices, enterprise workflow,
offline/PWA and localization work stays deprioritized. It is not a hidden
completion claim or a dependency for the current gate.
