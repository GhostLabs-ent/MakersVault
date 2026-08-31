# Gate 9 Baseline and Owner Checkpoint

**Gate:** 9 — Add descriptive machine context

**Status:** Gate complete; accepted by the owner

**Closed:** 2026-08-31

**Opened:** 2026-08-26

**Approved:** 2026-08-26

**Entry commit:** `fc29837`

**Entry schema:** 10

**Entry export/recovery contracts:** artifact-history format 1, Project format 1,
server-backup format 1, recovery contract 3

**Publication state:** Local only. Gate 9 does not authorize a push, tag, release,
deployment, device connection, or publication.

## Verified entry baseline

The complete untouched repository harness passed at `fc29837` on 2026-08-26:

- API: `150 passed in 20.92s`
- Web: `21 passed`; TypeScript and production build passed in an explicit
  invocation after the complete harness reused its verified build layer
- Bridge tests and native build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation and production security assertions passed
- Container smoke passed for direct and same-origin API access, security headers,
  the 512 MiB file policy, non-root processes, and schema 10
- The immutable v5.1 release contract passed

The existing frontend dependency-age and bundle-size warnings remain unchanged
and non-blocking. The unrelated untracked desktop architecture note remained
untouched.

## Current executable truth

MakersVault already records preparation context without controlling a machine:

- the current Asset and its immutable Artifact Revisions retain exact prepared
  file pointers and bounded extracted metadata;
- prepared metadata can contain a supplied `printer` string plus material, nozzle,
  layer height, duration, and format values, but it does not identify a trusted
  MakersVault entity;
- the web describes an artifact as prepared for a supplied printer name without
  claiming that MakersVault sent or fabricated it;
- artifact-history and Project exports embed prepared metadata, but no machine
  profile or relationship exists; and
- schema-aware recovery audits Projects and their ownership but has no machine
  tables or references.

Gate 8's trusted local application adapters only open an exact file in an approved
workstation application. They do not grant machine-control authority and must not
become a dispatch path in Gate 9.

## Proposed Gate 9 contract

### 9A — Minimal profiles and lifecycle

1. Add a first-class `MachineProfile`, labelled **Machine** in the interface, with
   a stable ID, unique active name, category, optional manufacturer, model,
   location, and notes, plus created, updated, and archived timestamps.
2. Use the bounded categories `fdm_printer`, `resin_printer`, `laser`, `cnc`,
   `pcb`, and `other`. Display labels may be clearer, but stored values remain
   stable and versioned.
3. Provide bounded authenticated list/create/update/archive/restore operations in
   Settings. An archived profile remains visible on existing references and cannot
   receive a new association.
4. Keep Gate 9 descriptive. A profile has no address, hostname, MAC address,
   serial connection, credential, API key, camera URL, command, online state, or
   other device-discovery/control field.
5. Permanent deletion is an explicit archive-first operation with typed
   confirmation. It removes only association rows and clears nullable profile
   references in one transaction. It never deletes or rewrites artifacts,
   revisions, prepared metadata, prepared payloads, or stored bytes.

### 9B — Artifact and prepared-context relationships

1. Add an optional many-to-many Artifact association with deliberately neutral
   semantics: a machine is **associated with** or **relevant to** an artifact. The
   relationship does not claim compatibility, fabrication, historical use, or
   successful output.
2. Add an optional exact prepared-machine target to both the current Asset mirror
   and the immutable Artifact Revision. The revision retains the target that was
   selected when that prepared payload was attached even if the current Asset
   later changes.
3. Preserve extracted prepared metadata as the immutable source snapshot. Renaming,
   editing, archiving, or deleting a profile never rewrites its supplied `printer`
   string or other extracted fields.
4. Never silently convert a supplied printer string into a profile relationship.
   The interface may suggest a likely match, but the owner must confirm it.
5. Limit prepared-machine targets to FDM and resin printer categories. Other
   machine categories use the neutral Artifact association until a later gate
   defines discipline-specific preparation semantics.

### 9C — Retrieval, interface, and portable references

1. Add compact machine management under Settings and optional machine selectors
   in artifact/prepared context. Every relevant state says that the relationship
   is descriptive and that no job was sent.
2. Retrieval may filter by associated or prepared machine, but no queue, schedule,
   routing, availability, or machine status is inferred.
3. Advance artifact-history and Project export manifests to format 2. Include the
   referenced profile ID and bounded profile snapshot alongside association and
   exact prepared-target references so an export remains understandable without
   access to the live database. Gate 9 does not add import.
4. Keep server-backup outer format 1, because it already contains the database and
   bytes, but advance the schema-aware recovery contract to 4. Audit machine table
   counts, reference integrity, and nullable cleanup while retaining verification
   compatibility for older supported recovery contracts.

### 9D — Regression and recovery evidence

1. Add schema 11 as an additive migration. Prove migration from a representative
   schema-10 library without changing existing artifact, revision, Project,
   prepared-file, metadata, or stored-byte identity.
2. Before implementation, add regressions proving the broken/no-contract version
   lacks profile lifecycle, exact revision targets, portable export references,
   and recovery integrity checks. Exercise real API, migration, export, and
   recovery seams rather than replacing the unit under test.
3. Prove profile edits and archive/restore leave source snapshots and stored files
   unchanged. Prove permanent deletion performs only the documented nullable
   cleanup and that exports remain self-describing.
4. Re-run prepared-print, revision, Project, Trash, export, recovery, handoff,
   web, container schema/security smoke, and the complete repository harness.

## Recommended owner decisions

1. Approve the minimal fields and six stable categories above. Do not add arbitrary
   custom JSON, device specifications, tags, or category-specific fields yet.
2. Approve the neutral Artifact association plus an optional exact prepared target
   recorded on both current Asset state and its immutable revision.
3. Require explicit confirmation before linking supplied printer text to a profile;
   do not use fuzzy or automatic identity matching.
4. Approve archive/restore and the archive-first permanent-delete behavior. Existing
   references remain readable while archived; permanent deletion clears only
   optional references and associations.
5. Approve schema 11, artifact-history/Project export format 2, and recovery
   contract 4 while leaving server-backup outer format 1 unchanged.
6. Implement as four bounded subgates: 9A profile lifecycle, 9B relationships and
   exact prepared targets, 9C exports/retrieval/UI, and 9D recovery/full evidence.

## Explicit exclusions

- No IP address, hostname, MAC address, port, serial path, API key, credential,
  camera URL, firmware setting, or network/device discovery.
- No polling, online/offline state, telemetry, queue, scheduling, routing,
  maintenance, consumables, job history, or utilization tracking.
- No slicing, toolpath generation, file transfer to a device, start, pause,
  resume, cancel, stop, or other machine command.
- No connection between a Machine profile and Gate 8 adapter launch authority.
- No merge of experimental print-monitoring work and no arbitrary machine-specific
  extension fields.
- No Project-export import, push, tag, release, deployment, or publication.

## Rollback and checkpoint

All Gate 9 references are optional and nullable. Rolling back application behavior
leaves profiles inert; a schema-aware rollback may remove only the new association
and profile data after proving no artifact, revision, prepared metadata, prepared
payload, Project, or stored byte will be changed.

The owner approved the field/category vocabulary, relationship semantics, manual
matching rule, lifecycle, contract versioning, and subgate sequence without
amendment on 2026-08-26. [ADR 0013](../../adr/0013-descriptive-machine-profiles.md)
records the accepted architecture. Subgate 9A may implement schema 11 and the
bounded Machine profile lifecycle before any artifact association, prepared-target,
export, retrieval UI, or recovery-contract work.

On 2026-08-27, after accepting the schema-11 profile lifecycle, the owner approved
additive schema 12 for Gate 9B's association table and prepared-target columns.
Migration 11 remains immutable. Export format 2, server-backup outer format 1, and
recovery contract 4 remain unchanged.
