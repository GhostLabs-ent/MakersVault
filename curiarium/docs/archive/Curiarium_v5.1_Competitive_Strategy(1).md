# Curiarium Competitive Strategy and v5.1 Direction

> **Historical document — kept for provenance, not as a description of the
> current system.** Written for upstream's v5.1 gate process before this fork
> diverged; its counts, schema versions, roadmap and scope are stale. The
> authoritative documents are listed in [../README.md](../README.md).


## Executive decision

Curiarium should not compete by becoming a smaller printer-management platform.
Its strongest position is:

> **The self-hosted workspace for everything you make.**

Curiarium should become the digital system of record for a workshop: a place to
organize, preview, relate, and launch CAD, 3D-printing, laser, CNC, electronics,
artwork, and documentation files without taking control of the user's machines.

A useful short expression of that promise is:

> **Your workshop's source of truth.**

## Strategic lane

Printer-management products can own the path from a model to a printer:

```text
Model -> toolpath -> printer
```

Curiarium should own the larger workshop record:

```text
                 +-- CAD
                 +-- 3D printing
                 +-- Laser
Project / Vault -+-- CNC
                 +-- Electronics
                 +-- Artwork
                 +-- Documentation
```

This is broader than file storage, but it is not machine automation. Curiarium
understands what is being made, which files belong to it, where those files came
from, and which local applications can open them.

## Product boundaries

The following decisions are part of the product direction:

- Curiarium organizes and relays supplied files; it does not slice models.
- Curiarium does not send jobs to a printer or start a print.
- Prepared-print payloads are internal implementation details, not files exposed
  for users to browse or download.
- Prepared-print information is shown as useful context, for example:

  > Prepared for Bambu Lab P1S · PLA · 0.4 mm · 3h 12m

- Assembly PDFs, notes, diagrams, and other supporting documents remain visible
  attachments.
- Users are not expected to upload thumbnails. Preview generation, extraction,
  caching, fallback behavior, and failure handling are Curiarium's job.
- A difficult or unusually large model must never make the library unusable.
- Local application integrations are welcome; hidden printer control is not.

## Product model

For v5.1, an existing asset remains the logical model or artifact. It may contain:

```text
Model / artifact
+-- Primary design or project file
+-- Visible supporting documents
+-- Creator, collection, tags, notes, and provenance
+-- Preview state
`-- Internal prepared-print state
    +-- Target printer
    +-- Material
    +-- Nozzle and layer information
    +-- Estimated duration
    `-- Hidden prepared payload, when supplied
```

Do not add a temporary `AssetGroup` layer. The long-term structure can evolve
directly toward:

```text
Project
`-- Artifact
    `-- Artifact revision
```

This avoids an unnecessary `Project -> AssetGroup -> Asset -> File` hierarchy.

## v5.1 release philosophy

v5.1 is a confidence release. It should make the current application feel faster,
safer, clearer, and substantially easier to use with a real library.

Its four promises are:

1. **Fast and resilient** — cached previews, lazy work, pagination, and guardrails
   that prevent expensive files from freezing the library.
2. **Easy to organize at scale** — modern navigation, visible bulk workflows,
   breadcrumbs, folder search, and predictable import behavior.
3. **Models with context** — editable identity, rich metadata, supporting files,
   provenance, and prepared-print summaries without exposing machine payloads.
4. **A vault users can trust** — hardened authentication defaults, safe migrations,
   documented backup and restore, and clean release practices.

The complete release contract is in [V5.1_SCOPE.md](V5.1_SCOPE.md).

## Deferred architecture

The following ideas remain strategically valuable but must not delay v5.1:

- Full Project -> Artifact -> Revision architecture.
- Multi-user accounts, roles, MFA, API keys, and OIDC/SSO.
- Custom metadata fields.
- Generic machine integrations and printer telemetry.
- A public community-adapter SDK.
- Synchronization, hosted storage, and managed backup infrastructure.
- A fully hosted Curiarium service.

See [ROADMAP.md](ROADMAP.md) for sequencing.

## Competitive advantages to compound

Curiarium already has useful advantages:

- Self-hosted and Docker-friendly operation.
- Browser-based model previews.
- Nested folder organization, search, sorting, tags, and notes.
- Drag-and-drop, batch, ZIP, URL, and mounted-folder ingestion.
- Open-in-slicer and LightBurn workflows.
- Support for more than 3D-printing file types.
- Model metadata, configurable storage paths, supporting documents, and automatic
  prepared-print summaries.

The next competitive gap is not adding more extensions. It is making Curiarium
understand identity, provenance, integrity, revisions, and relationships while
remaining pleasant to operate.

## Features not to chase yet

- Print-farm scheduling or least-busy-printer routing.
- Deep printer telemetry and large compatibility matrices.
- Advanced filament accounting.
- Maintenance scheduling.
- Enterprise-scale object storage.
- Complex offline/PWA behavior.
- Broad localization before core workflows stabilize.

Those features move Curiarium onto a printer-management battlefield and dilute
the complete-workshop position.

## Open-source and business direction

Curiarium should remain complete, useful, and self-hostable as free open-source
software. Sustainable revenue should come from convenience and expertise rather
than artificial restrictions:

- Donations and sponsorship.
- Managed hosting.
- Managed encrypted backup and storage.
- Professional deployment and migration support.
- Optional hosted services with real infrastructure costs.

The governing phrase is:

> **Open software, paid convenience.**

The detailed policy is in [SUSTAINABILITY.md](SUSTAINABILITY.md).

## Supporting documents

- [PRODUCT_STRATEGY.md](PRODUCT_STRATEGY.md) — product identity, users, principles,
  and durable product boundaries.
- [V5.1_SCOPE.md](V5.1_SCOPE.md) — release scope, priorities, acceptance criteria,
  and explicit non-goals.
- [ROADMAP.md](ROADMAP.md) — architecture and feature sequencing after v5.1.
- [SUSTAINABILITY.md](SUSTAINABILITY.md) — open-source and revenue philosophy.
- [ARCHITECTURE_RUNBOOK.md](ARCHITECTURE_RUNBOOK.md) — the evidence-based gate
  sequence, migration rules, acceptance protocol, and re-baselining process used
  to execute this strategy.

## Core principle

> Build Curiarium into a universal, self-hosted system of record for makers and
> their entire workshop.
