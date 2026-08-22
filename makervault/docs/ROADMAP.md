# MakersVault Roadmap

This roadmap expresses sequencing, not promised dates. Reliability and migration
safety take priority over reaching a named architectural milestone quickly.

Execution is governed by [ARCHITECTURE_RUNBOOK.md](ARCHITECTURE_RUNBOOK.md). A
roadmap item is complete only after its gate evidence is accepted and the
architecture is re-baselined.

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

The long-term portable archive may resemble:

```text
makersvault-backup.mvault
+-- manifest.json
+-- database/
+-- projects/
+-- assets/
+-- thumbnails/
+-- metadata/
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
