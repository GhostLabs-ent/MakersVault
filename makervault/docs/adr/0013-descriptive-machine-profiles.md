# ADR 0013: Descriptive machine profiles

**Status:** Accepted

**Proposed:** 2026-08-26

**Accepted:** 2026-08-26

## Context

MakersVault already preserves bounded preparation metadata, including a supplied
printer-name string, on current Assets and immutable Artifact Revisions. That text
is useful source context but is not a trusted identity. There is no first-class
machine record, artifact relationship, portable profile snapshot, or recovery
audit for machine references.

The product needs useful workshop-machine context without becoming a device
registry, network client, telemetry service, fabrication queue, or controller.
Gate 8's exact-file local application adapters do not grant any machine authority
and cannot be used to bypass this boundary.

## Decision

### Profiles and vocabulary

MakersVault introduces a first-class `MachineProfile`, labelled **Machine** in the
interface. Its bounded common fields are a stable ID, unique active name, category,
optional manufacturer, model, location, and notes, and created, updated, and
archived timestamps. The stable categories are `fdm_printer`, `resin_printer`,
`laser`, `cnc`, `pcb`, and `other`.

Gate 9 adds no arbitrary custom JSON, tags, category-specific specification bag,
address, hostname, MAC address, port, serial path, credential, API key, camera URL,
firmware setting, discovery, status, or command field.

### Lifecycle

Authenticated bounded APIs provide list, create, update, archive, and restore.
Archived profiles remain readable on existing references and cannot receive new
associations. Active names are unique; archived records do not reserve a name.

Permanent deletion requires the profile to be archived and an exact typed
confirmation. One database transaction removes only machine association rows and
clears nullable machine references. It never deletes or rewrites an Artifact,
Revision, Project, prepared metadata snapshot, prepared payload, or stored byte.

### Relationships and prepared context

An optional many-to-many Artifact relationship has deliberately neutral semantics:
a Machine is **associated with** or **relevant to** an Artifact. It does not claim
compatibility, historical use, successful fabrication, or output provenance.

An optional exact prepared-machine target is recorded on both the current Asset
mirror and the immutable Artifact Revision. Only FDM and resin profiles may be
prepared targets in Gate 9. Laser, CNC, PCB, and Other profiles use the neutral
Artifact association until later discipline-specific semantics are approved.

Extracted prepared metadata remains an immutable source snapshot. MakersVault may
suggest a likely profile for supplied printer text, but it never creates the link
without explicit user confirmation. Profile edits, archival, and deletion do not
rewrite the supplied text or any other extracted field.

### Export and recovery

Artifact-history and Project export manifests advance to format 2 and carry
referenced profile IDs, bounded profile snapshots, neutral associations, and exact
prepared-target references. Gate 9 adds no import.

Server-backup outer format remains 1 because it already contains the matched
database and storage inventory. The schema-aware recovery contract advances to 4
to count and validate machine tables and nullable reference cleanup while retaining
the documented verification compatibility for older supported contracts.

Schema 11 is additive. All machine references are optional and nullable; no
existing stored byte moves. Implementation proceeds as 9A profile lifecycle, 9B
relationships/prepared targets, 9C export/retrieval/UI, and 9D recovery/full
evidence.

## Alternatives considered

- **Use supplied printer text as identity:** rejected because untrusted metadata is
  ambiguous, mutable in meaning, and cannot safely name a database entity.
- **Automatically fuzzy-link names:** rejected because an incorrect identity claim
  is harder to detect than an explicit unlinked suggestion.
- **Store machine-specific arbitrary fields:** deferred until common retrieval
  needs are proven; an unbounded schema would quickly become a device registry.
- **Call the relationship compatible-with or fabricated-on:** rejected because the
  initial evidence cannot support either claim.
- **Add network control now:** rejected because it violates the product boundary
  and introduces credentials, device protocols, safety, and authorization concerns
  that require a separate architecture gate.

## Consequences

Machine context can improve organization and preserve preparation intent without
changing existing files or claiming fabrication. Export manifests become richer
and versioned; recovery auditing gains relational checks. The interface must use
descriptive wording and explicitly state that no job was sent. Machine telemetry,
scheduling, maintenance, consumables, job history, file transfer, slicing, and
start/pause/cancel controls remain excluded. No push, tag, release, deployment, or
publication follows from this decision.
