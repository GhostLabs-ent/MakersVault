# MakersVault Roadmap

This roadmap expresses sequencing, not promised dates. Reliability and migration
safety take priority over reaching a named architectural milestone quickly.

Execution is governed by [ARCHITECTURE_RUNBOOK.md](ARCHITECTURE_RUNBOOK.md). A
roadmap item is complete only after its gate evidence is accepted and the
architecture is re-baselined.

## Active gate — end-state audit

**2026-09-10:** Gates 13A–13B are owner-accepted. The accepted
[13B lifecycle results](evidence/gate-13/SUBGATE_13B_RESULTS.md) were captured
at verification implementation `2c68d70`: the complete gate and production-HTTPS
upgrade/restore/rollback/portable-startup checks pass. This is local development
evidence, not final end-state acceptance or a newly qualified release.

[13C](evidence/gate-13/SUBGATE_13C_RESULTS.md) is in progress. Approved dependency/
runtime maintenance, the [archive guard](evidence/gate-13/ARCHIVE_GUARD_RESULTS.md)
and [browser corrections](evidence/gate-13/BROWSER_FIX_RESULTS.md) are verified.
The owner-approved [folder-picker slice](evidence/gate-13/FOLDER_PICKER_RESULTS.md)
is implemented at `76b526d`: one searchable, explicit-confirmation dialog replaces
per-card destination lists. Full-gate executed inputs match that revision under the
recorded source note (351 API / 56 web tests and HTTPS lifecycle). Three baseline
Chromium organization runs and three-engine functional checks pass. Historical
failures, the 1,040-folder stress failures and a separate detail-preview long task
remain open. The [residual diagnosis](evidence/gate-13/RESIDUAL_DIAGNOSIS.md) now
confirms hidden sidebar-menu DOM and driver-query costs. The subsequently approved
[sidebar-menu slice](evidence/gate-13/SIDEBAR_MENU_RESULTS.md) implements on-demand
contents and the scoped accessible locator at `82cb2cc`; full verification passes
351 API / 58 web tests and current HTTPS lifecycle. Exact detail native wait and
folder-API latency remain separate investigative tracks, not claimed fixed by menus.
Current repetitions retain a 1,368.5 ms startup failure and 113.3/108.3 ms stress
folders API p95 failures, despite fast search and zero observed interaction tasks.
The owner's subsequent [bounded performance pass](evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md)
adds a read-only folder-list projection at `c42614e`, with 354 API tests passing.
The stress API target still fails. Further performance tuning is deferred at the
owner's request; historical/current failures remain recorded, not converted to passes.
The [security closeout review](evidence/gate-13/SECURITY_CLOSEOUT.md) led to the
owner-approved [S01/S02 hardening](evidence/gate-13/SECURITY_HARDENING_RESULTS.md)
at `ac4a051`: targeted test dependencies updated; outbound hostname identity uses
strict IDNA2008. Full verification passes 422 API tests and the same-source 58-test
web preflight, plus current HTTPS lifecycle. Fresh language audits are clean; exact
images retain 181 API / 3 web matches. Remaining native risks, including trusted
raw recovery, are not waived; security acceptance remains open. Production HTTPS
is required even on LAN/VPN.
Browser/platform and release-readiness
evidence remain unfinished, followed by 13D owner acceptance of the end state and next
roadmap. The [traceability/carry-forward register](evidence/gate-13/TRACEABILITY.md)
records every unmet commitment with its reason, owner and dependency. It includes
Gate 12's explicit desktop deferral, later identity/provider/adapter/UX work,
real-platform qualification, architecture debt and the independent monitoring
experiment. These are not automatic feature authorizations. Publication and any
replacement for the frozen Gate 5 candidate require separate owner decisions.

## v5.1 — confidence release

Theme: make the current product fast, safe, and deliberate.

- Preview performance and failure guardrails.
- Visible bulk workflows.
- Breadcrumbs and folder-location clarity.
- Mounted-library scan reporting and manual rescan.
- Hardened authentication configuration.
- Backup, restore, migration, and release documentation.
- Content hashing and provenance metadata when stable.
- Polish for model bundles, prepared-print summaries, LightBurn, and the local
  bridge.

The binding details are in [V5.1_SCOPE.md](V5.1_SCOPE.md).

## After v5.1 — identity and history foundation

**Status update (2026-09-05):** The identity/history, Project, adapter, Machine,
portability, and shared-vault authentication sequence is implemented in later local
history through accepted Gates 6–11 and the accepted Gate 11E passkey slices. The
frozen Gate 5 candidate remains at `f6ff55b`. The sections below preserve the
direction that produced those features; their current status is tracked in the
runbook. Sustainability, API-key/OIDC decisions, hosted/provider work, and the
disabled print-monitoring experiment remain separately gated. The owner deferred
Gate 12 sustainable optional services to the desktop version on 2026-09-05. Its
free-core and non-lock-in commitments remain binding; Gate 13 is now active for
the current track.

### Content identity

Extend SHA-256 content identity into:

- Duplicate suggestions across import sources.
- Integrity verification.
- Changed-source detection for mounted libraries.
- Backup manifests.
- Revision detection.

MakersVault should suggest and explain; it should not silently merge or delete.

### Artifact revisions

Allow one logical artifact to retain prior primary-file states:

```text
Housing
+-- Current revision
`-- Revision history
    +-- Rev 1
    +-- Rev 2
    `-- Rev 3
```

Revision behavior must define:

- Which file is current.
- Whether metadata belongs to the artifact or revision.
- How supporting documents are shared or versioned.
- How previews are retained.
- How storage paths change.
- How old revisions are exported and restored.

### Trash and recovery

Introduce recoverable deletion before making broad destructive bulk operations
more powerful. Trash should have clear retention, storage, restore, and permanent
deletion behavior.

## Next architectural milestone — projects

A project represents the thing being built. An artifact represents a component or
deliverable within it, and an artifact revision represents history.

```text
Project
`-- Artifact
    `-- Artifact revision
```

Examples:

```text
ATAK Relay
+-- Enclosure
+-- Lid
+-- Front panel
+-- Carrier PCB
+-- Wiring diagram
`-- Assembly instructions
```

The project system should be introduced through migration from existing assets,
not by adding a temporary `AssetGroup` entity.

### Relationships

Begin with a small, meaningful vocabulary:

- `derived_from`
- `source_of`
- `documentation_for`
- `assembly_of`
- `attachment`

Avoid exposing relationship types that do not produce a useful interface or
workflow. Prepared-print state remains internal rather than becoming a browsable
`sliced_from` file graph.

### Project provenance

Projects may include:

- Source repositories and model-site links.
- Creator and license information.
- Component references.
- Fabrication notes.
- Status and part numbers.

Custom fields should follow only after common metadata behavior is stable.

## Application adapters

The existing slicer and engraving bridge can evolve into a general local
application-adapter model:

```text
Open with
+-- OrcaSlicer
+-- LightBurn
+-- FreeCAD
`-- KiCad
```

An adapter should define:

- Supported file roles and extensions.
- A safe local launch mechanism.
- Optional command arguments.
- Platform support.
- Installation and diagnostics.

Adapters open supplied files in user-selected applications. They do not grant
MakersVault permission to fabricate, transmit machine programs, or automate
unrelated desktop actions.

A community SDK should wait until the internal adapter contract has proven stable
across several built-in integrations.

## Generic machine records

Machine records may eventually provide context for prepared files and workshop
inventory:

```text
Machine
+-- FDM printer
+-- Resin printer
+-- Laser
+-- CNC
+-- PCB machine
`-- Other
```

Initial machine records should be descriptive. Live telemetry, scheduling,
maintenance systems, and remote control are separate capabilities with greater
security and support requirements.

MakersVault should not make printer control its primary product identity.

### Experimental print-failure alerts

The first post-v5.1 release may carry an independent, disabled-by-default
experiment for local print-failure detection and Discord alerts. The experiment
samples an authorized camera through an optional external inference provider and
reports advisory incidents. It does not slice, start, pause, cancel, schedule, or
route prints.

This experiment is not a Gate 6 completion requirement and cannot weaken revision,
Trash, migration, or recovery evidence. Generic HTTP/RTSP cameras, OctoPrint, and
Moonraker are the preferred initial inputs. Native Bambu camera access remains
experimental until it is proven against real hardware and firmware. Promotion
requires measured false-positive, missed-failure, latency, resource, privacy, and
service-isolation evidence.

The complete boundary and discovery gate are in
[EXPERIMENTAL_PRINT_MONITORING.md](EXPERIMENTAL_PRINT_MONITORING.md).

## Backup and portable export

Gate 10 implemented the documented [portable format v1](MVAULT_FORMAT_V1.md),
separate from raw SQLite/storage disaster-recovery archives:

```text
library.mvault (tar.gz)
`-- mvault/
    +-- header.json
    +-- content/
    +-- derived/
    +-- catalogs/
    +-- manifest.json
    `-- checksums.sha256
```

Requirements:

- Documented, versioned format.
- Integrity verification.
- Export without a paid service.
- Restore to a clean compatible instance.
- Clear handling of externally mounted no-copy files.
- Migration utilities as schemas evolve.

Storage abstraction and S3-compatible support should be driven by this portability
model rather than added solely for a hosted offering.

## Authentication roadmap

Security should advance in deliberate stages:

```text
Safe single-admin setup
        -> multiple users
        -> roles and sessions
        -> MFA and API keys
        -> OIDC / SSO
```

Each stage needs migrations, auditability, recovery, and threat-focused tests.
Multi-user authentication should not be slipped into an unrelated release as a
small settings feature.

**Current status (2026-09-05):** Gates 11A–11D and 11E-1a–1d are accepted and
closed. The shared vault now has persistent Argon2id accounts, protected revocable
sessions, three fixed deny-by-default roles, mandatory audit, stopped-instance
recovery, and optional password-plus-passkey MFA. API keys and OIDC/SSO remain
separate future decisions; no push, release, deployment, hosted tenancy, or
publication is implied.

## Explicitly deprioritized

- Print-farm routing and scheduling.
- Broad printer telemetry and automatic printer control beyond the bounded,
  alert-only experiment.
- Advanced filament accounting.
- Large compatibility matrices.
- Enterprise workflow orchestration.
- Broad offline/PWA support.

These may be reconsidered if user demand and the product identity change, but they
are not the current path to differentiation.
