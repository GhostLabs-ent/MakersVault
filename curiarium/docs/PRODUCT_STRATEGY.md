# Curiarium Product Strategy

## Product promise

> **The self-hosted workspace for everything you make.**

Curiarium is the workshop's digital source of truth. It organizes the designs,
projects, supporting material, provenance, and application handoffs involved in
making something, while leaving fabrication decisions and machine control with
the user.

## Who it is for

Curiarium is primarily for:

- Individual makers with years of files spread across drives and downloads.
- Multi-discipline hobbyists working across CAD, printing, laser, electronics,
  artwork, and documentation.
- Home workshops and small maker spaces that want a self-hosted library.
- Users who value ownership, portability, and local integrations.
- People who need to rediscover and reproduce prior work, not merely store it.

It is not primarily a print-farm scheduler, printer dashboard, or manufacturing
execution system.

## User problem

A maker rarely has only one file for a thing. A reproducible project may include:

```text
ATAK Relay Enclosure
+-- enclosure.step
+-- enclosure.3mf
+-- front-panel.lbrn2
+-- logo.svg
+-- carrier-board-gerbers.zip
+-- bom.csv
+-- assembly.pdf
`-- wiring-diagram.png
```

Traditional folders preserve proximity but not identity, provenance, metadata,
revision history, relationships, previews, or application workflows.

Curiarium should understand the thing being made, not only the files stored
beside one another.

## Product principles

### Self-hosting is a feature

Installation, upgrades, backup, recovery, security defaults, and storage behavior
are part of the user experience. A self-hosted product is not trustworthy merely
because it runs in Docker.

### Automation should remove chores

Curiarium should extract embedded thumbnails, generate and cache previews,
inspect supplied metadata, and remember source information automatically.
Users should not have to manufacture thumbnails or duplicate metadata just to
make the library pleasant.

### Context should be visible; machinery should remain explicit

Prepared-print context can be displayed prominently:

> Prepared for Bambu Lab P1S · PLA · 0.4 mm · 3h 12m

The underlying machine payload stays internal. Curiarium may relay a supplied
file to a configured local application, but it does not slice, transmit a job to
a machine, or start fabrication.

### Broad workflows, coherent interface

Supporting CAD, laser, electronics, and artwork does not mean adding a different
product inside every card. Common concepts should remain consistent:

- Identity.
- Preview.
- Metadata.
- Provenance.
- Supporting documents.
- Revisions.
- Relationships.
- Open with a local application.

### Safe suggestions beat silent guesses

Curiarium may suggest that matching files belong together or appear duplicated,
but it should not silently merge, overwrite, reorganize, or delete user data.

### Portability is non-negotiable

Users must be able to retrieve their original files and metadata without depending
on a paid service. Future backup and export formats should be documented and
verifiable.

## Preview policy

Library previews follow this order:

1. Extract a trustworthy embedded thumbnail when present.
2. Reuse a previously generated and cached thumbnail.
3. Generate a bounded preview for a manageable source file.
4. Use a polished type-aware placeholder or explicit on-demand action.

Future imports may retain source-site artwork automatically when licensing and
source behavior permit it. There is no manual thumbnail-upload workflow.

Preview generation must have size and time guardrails. A failure should be saved
so every browser does not repeat the same expensive attempt indefinitely.

## Model and file policy

An artifact/model has one primary identity and may have several related records:

```text
Artifact
+-- Primary file
+-- Supporting files visible to the user
+-- Preview and extracted metadata
`-- Internal prepared-print state
```

Examples of visible supporting files:

- Assembly instructions.
- Wiring diagrams.
- Bills of materials.
- Notes and Markdown.
- Reference archives.

Prepared-print payloads are not shown as supporting files and are not included in
normal downloads or ZIP exports. Their useful metadata is shown in the interface,
and the payload can be cleared or relayed through the configured slicer action.

## Provenance and trust

Every artifact should eventually answer:

- What is this?
- Who created it?
- Where did it come from?
- What license applies?
- Has its content changed?
- Which revision is current?
- What other artifacts depend on it?
- Which application should open it?
- Can the vault be restored somewhere else?

Source URL, license, and SHA-256 content identity are therefore more strategically
valuable than adding large amounts of discipline-specific metadata prematurely.

## Differentiation

Printer-management platforms connect models to printers. Curiarium connects the
whole workshop record to the applications a maker already uses:

```text
Curiarium
+-- OrcaSlicer / PrusaSlicer / Cura / Bambu Studio
+-- LightBurn
+-- FreeCAD and other CAD tools
+-- KiCad and electronics tools
`-- Future community application adapters
```

The adapter idea is a long-term direction, not a promise that every application
belongs in v5.1.

## Product success

Curiarium succeeds when a user can return months later, find the thing they
built, understand its context, recover every relevant document, and reopen the
correct supplied project in the correct local tool with confidence.
