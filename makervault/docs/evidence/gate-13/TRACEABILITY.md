# Gate 13 strategy and invariant traceability

**Date:** 2026-09-10

**Baseline:** audit entry `236c0fd` / application `1a209aa`; current verification
`ea17494` approved runtime containment and full verification after `ac4a051` S01/S02 hardening; folder-list optimization
`c42614e` and functional browser harness `7b0bb6e` remain separately named, schema 17 unchanged

**Status:** 13A–13B accepted; approved 13C picker/sidebar optimizations implemented;
remaining performance tuning deferred by owner after one bounded pass;
approved S01/S02 patches and runtime containment verified; S04 residual acceptance pending;
browser/platform evidence and final Gate 13 acceptance remain open

## Reading this ledger

`VERIFIED` below is limited to the named source/test/runtime layer. It does not
mean release-qualified, supported on every platform, or owner-accepted at Gate 13.
Historical Gate 5 benchmarks remain evidence for `f6ff55b`, not current schema-17
performance. The [13A results](SUBGATE_13A_RESULTS.md) and
[13B lifecycle results](SUBGATE_13B_RESULTS.md) name their executions; subsequent
[13C maintenance results](REMEDIATION_RESULTS.md) name the updated clean build,
full-gate repeat and separate audited-image smoke. The approved
[archive guard](ARCHIVE_GUARD_RESULTS.md) has a subsequent full-gate pass and
exact-image rescan at `ddf8cf4`; no image finding was waived.
The [browser correction record](BROWSER_FIX_RESULTS.md) adds the full gate and
same-image HTTPS lifecycle/browser/audit evidence at `1255933`: race regression
and Firefox trust pass, while Chromium performance remains unqualified.
The subsequent [profile record](CHROMIUM_PROFILE_RESULTS.md) uses the same images,
separates product/driver costs and retains two passing unprofiled controls alongside
all historical failures. The subsequently approved
[picker implementation](FOLDER_PICKER_RESULTS.md) adds full-gate inputs matching
`76b526d`, three-engine picker tests and three passing baseline Chromium repeats.
Its full-run source note is explicit; larger-folder and detail-preview failures
remain open, not erased by the optimization.
The [residual diagnosis](RESIDUAL_DIAGNOSIS.md) adds six same-image runs, confirms
hidden sidebar-menu DOM and driver-query costs, and leaves the exact detail native
wait and folder-API latency unresolved. The subsequent owner-approved
[sidebar-menu slice](SIDEBAR_MENU_RESULTS.md) implements lazy contents and the scoped
search locator on `82cb2cc`, with full-gate/HTTPS lifecycle and named browser checks.
It does not clear those separate causal questions or grant general performance acceptance.
Carry-forward IDs have reasons, dependencies, and a review checkpoint below.
The [bounded performance follow-up](BOUNDED_PERFORMANCE_RESULTS.md) at `c42614e`
passes 354 API tests but retains timing failures. The owner prefers to carry those
performance limitations for now; this decision does not waive other gate findings.

Source commitments are from [Product Strategy](../../PRODUCT_STRATEGY.md),
[Competitive Strategy](../../MakersVault_v5.1_Competitive_Strategy(1).md),
[v5.1 Scope](../../V5.1_SCOPE.md), [Roadmap](../../ROADMAP.md),
[Sustainability](../../SUSTAINABILITY.md), and runbook sections 2, 3, 6, and 13.

## Product and architecture coverage

Test paths in this table are relative to `api/tests/` unless qualified otherwise.

| ID / commitment | Current behavior and direct proof | Remaining evidence or disposition |
|---|---|---|
| P01 — find a large mixed library without stalls | Bounded worker previews, static thumbnail reuse, pagination; `test_preview_policy.py`, `test_api_smoke.py`; on-demand picker removes 4,200 closed options; `82cb2cc` adds lazy sidebar menus and current preview/cache/organization evidence in [results](SIDEBAR_MENU_RESULTS.md) | G13-01 retains all scale/startup/API/preview observations; reduced DOM does not establish a cause for every wait or blanket performance qualification |
| P02 — modern folder navigation and bulk organization | Folder-scoped naming, nested lookup, conflicts, breadcrumbs, explicit selected IDs, shared searchable move dialog and native on-demand folder menus; 17 named picker/sidebar cases across three engines, with explicit WebKit FileList-only limit, plus seven ordering regressions on `82cb2cc` images | G13-01 performance/support boundaries remain open; C04 for server-wide selection, whole-app narrow/touch/accessibility and density polish |
| P03 — editable identity, metadata, configurable paths | Names, creator/collection/tags/notes/provenance and managed-storage templates; `test_organization.py`, `test_revisions.py`, `test_content_identity.py` | Renaming never moves immutable historical or external no-copy bytes; C05 for custom fields and automatic source artwork |
| P04 — supporting documents and prepared context | Visible supporting files, internal prepared role and supplied summary, scoped slicer handoff; API/revision/export tests and current three-engine visibility/no-prepared-link assertions on `76b526d` images | No thumbnail-upload chore or machine operation; real local-tool launch remains C03 |
| P05 — observable copy/no-copy imports | Restartable scans, bounded failures/counts, repeat-path safety; mount/descriptor tests and current Chromium copy-mode scan/repeat/source-preservation drill on `76b526d` images | No blanket real NAS/provider qualification; C04 continuous watching/exclusions/live per-file progress |
| P06 — content identity, provenance and trust | SHA-256 ingest/backfill/changed-state and suggestion-only duplicates; `test_content_identity.py`, `test_revisions.py` | VERIFIED at API/test layer; no automatic repair or merge promise |
| P07 — revisions and recoverable deletion | Immutable linear revisions; restore-as-new; metadata-only Trash; explicit journaled purge and accepted retention choices; `test_revisions.py`, `test_trash.py` | VERIFIED at API/test layer and supplemented by 13B's G13-02 raw restore/exact stopped rollback proof |
| P08 — Project → Artifact → Revision and useful relationships | Optional many-to-many Project membership, bounded canonical relationships, provenance/lifecycle/history exports; `test_projects.py`, `test_project_relationships.py`, `test_project_lifecycle_export.py` | ADRs 0009–0011 govern the concrete model; legacy Asset projection remains, not an `AssetGroup`. No arbitrary graph, separate ContentBlob table, or byte-deduplication claim |
| P09 — safe broad local-tool workflows | Versioned built-in/local adapters and exact-file grants; `test_handoff.py`, web `handoff.test.ts`, bridge adapter/handoff/install contract tests | C03 real workstation qualification; C05 dedicated KiCad integration/community SDK not delivered by FreeCAD/Inkscape support |
| P10 — descriptive Machine context | Six categories, explicit links and portable snapshots; `test_machines.py`, `test_machine_relationships.py`, `test_machine_portability.py` | VERIFIED at API/test layer; no telemetry, safety certification, compatibility inference, or commands |
| P11 — independent free backup/export/restore | Raw format 1/contract 6; local ContentStore; schema-17 content export → verified `.mvault` v1 → clean schema-12 import; recovery/portable/content-store suites and current 1,200-Artifact drill | G13-02 joined startup/upgrade/restore VERIFIED in 13B; C02 remains for S3, live/merge import, browser jobs and synchronization |
| P12 — secure defaults and trustworthy upgrades | Fail-closed secrets, bootstrap identity, protected cookie sessions, three roles, audit, optional passkeys, stopped recovery; current complete test gate and fresh-container smoke | G13-02 current operator lifecycle VERIFIED in 13B; G13-03 selected-release qualification remains open; finding-by-finding [security ledger](../../security/GATE_13_REVALIDATION.md) |
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
| I03 — supporting documents visible/retrievable | Supporting selection/download and revision/Project export tests; current three-engine document-visibility reprise on `76b526d` images |
| I04 — automatic previews, no manual thumbnail obligation | Embedded/cache/worker/fallback policy; preview policy/API tests; automatic generated-thumbnail persistence is not a manual user-upload feature |
| I05 — never rewrite mounted no-copy libraries | Descriptor/symlink tests, mounted scan ownership, revision/Trash external-preservation tests, portable external-remount truth |
| I06 — duplicate suggestions, never silent merge/delete | Content identity tests and immutable identical-replacement no-op; no automatic deduplication mutation |
| I07 — original files/metadata portable without subscription | Independent verifier, current scale export/import/re-export, corruption/nonempty-target tests; external bytes explicitly outside vault ownership |
| I08 — local integrations confer no hidden control | API/bridge grant separation, role/extension/catalog/origin restrictions and constrained local arguments; no remote executable or shell authority |
| I09 — no temporary AssetGroup | Actual Project membership and ArtifactRevision migration tests; accepted ADRs 0009–0011 specialize the original conceptual hierarchy |
| I10 — hostile file cannot monopolize library | Server/preview controls have tests; 13C patches the specific fflate ZIP64 issue and guards unsupported member methods before BZIP2/LZMA reads. Interpreter inventory remains open under G13-04; general browser ZIP upload isolation is not implemented. Baseline organization passes, while larger-folder/detail-preview performance remains unqualified |

## Open audit findings — repair inside Gate 13

These include verification gaps and fresh dependency findings, not demonstrated
data loss or a discovered authentication bypass.
Owner: MakersVault maintainer; implementation/evidence: local delivery work under
the next accepted slice. Re-review at that slice and again at 13D.

| ID | Source evidence / effect | Required next proof |
|---|---|---|
| G13-01 | Approved picker/sidebar changes remove eager hidden controls. [Bounded API follow-up](BOUNDED_PERFORMANCE_RESULTS.md) at `c42614e` avoids folder ORM hydration and passes 354 API tests. HTTP instrumentation identifies garbage-collection contributions to some API spikes. New unprofiled stress still misses folders API <100 ms | DEFERRED tuning by owner's 2026-09-10 decision: one final pass is enough; carry remaining performance limitations for now. Historical/current startup, detail and API failures remain evidence, not passes. Reopen only with renewed owner direction or a materially worse user-visible regression. No changed budget, authentication relaxation, security/platform waiver or automatic 13C acceptance |
| G13-02 | 13A found stale schema-5 recovery assertions and no joined current lifecycle. **13B VERIFIED:** `gate13-lifecycle-drill.py` passes schema 4→17, contract-6 restore, pre-start revocation/audit, schema 12→17 portable bootstrap and exact stopped rollback on `2c68d70` | Owner accepted 13B at `2f61b37`; injected interruption tests and three no-mutation operator refusals pass. Named local development evidence, not release or physical-power-loss qualification |
| G13-03 | 13A found stale JWT/schema-5 exact-image smoke. **13B harness portion VERIFIED:** current production-HTTPS identity/security/persistence/schema-17 smoke against immutable local image IDs | 13C remains OPEN: owner-selected immutable scope/revision and matched-image/bridge/reproducibility evidence before any release claim; static `verify-release` remains only a contract check |
| G13-04 | Owner-approved [S01/S02 hardening](SECURITY_HARDENING_RESULTS.md) at clean `ac4a051` passes full verification: 422 API tests, same-source 58-test web preflight, security/passkeys and current HTTPS lifecycle. New language audits are clean; exact image matches remain 181 API / 3 web with reduced-record equality. Strict outbound IDNA2008 mitigates the reviewed application path; archive guard and seven dated Python branch exclusions remain | S01/S02 IMPLEMENTED/VERIFIED, SECURITY ACCEPTANCE OPEN. S04 native/raw-recovery residuals still need fixes or explicit scoped owner acceptance against exact images/architecture before candidate qualification. CPython remains matched/unpatched. No automatic waiver, release clearance or Gate 13C acceptance |

G13-04's [S04 per-CVE decision record](SECURITY_RESIDUAL_DECISIONS.md) retains 11
proposed exact-image precondition exclusions and 69 unwaived residual CVEs, all
owner-pending. Its approved [containment implementation](SECURITY_CONTAINMENT_RESULTS.md)
at `ea17494` passes the complete gate and verifies the actual API/Nginx capability
boundary. Default/custom ownership, uploads, preview persistence and trusted recovery
remain supported. New raw evidence is durable/private; historical temporary artifacts
are not recovered. Accept this bounded implementation separately from the remaining
CVEs and candidate/platform qualification. The final audit matches lifecycle IDs
and retains identical reduced records for 181 API / 3 web matches; the first
incomplete image attempt is separately recorded, never promoted to a complete scan.
The [current owner package](SECURITY_DISPOSITION_PROPOSAL.md) proposes E11 exact-image
exclusions, R59 exceptions under named C1–C7 local-qualification conditions and H10
holds. R59 includes two critical Perl CVEs; no decision is yet accepted. A new
durable CLI/symbol probe refines evidence without removing any scanner matches.
Approval of E/R would still leave S04/G13-04 open; candidate acceptance remains separate.

P07/P11/P12 now also have G13-02's joined current lifecycle proof, supplementing
their focused API tests. Raw restore preserves the complete content/security graph
with only required recovery mutations. Portable import preserves content without
transferring identity and requires renameable filesystem staging before copying to
empty production volumes. See 13B for exact derived-preview and external-state
boundaries; no broad catalog or payload comparison was removed.

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
