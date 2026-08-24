# Gate 7 Baseline and Entry Record

**Gate:** 7 — Introduce Projects and relationships

**Status:** In progress — subgate 7B

**Opened:** 2026-08-22

**Entry commit:** `db715d0`

**Entry schema:** 8

**Publication state:** Local only. No Gate 7 commit, image, binary, tag, or release
may be pushed until the owner changes the standing publication decision.

## Entry decision

Gate 6 is accepted with stable artifact identity, immutable revisions, recoverable
artifact Trash, and revision-aware matched backup. On 2026-08-23 the owner accepted
the Gate 7 terms, default migration experience, membership cardinality,
relationship vocabulary, and Project lifecycle/export contract without amendment.
That decision authorized subgate 7A implementation.

## Verified current truth

| Area | Current schema-8 behavior | Gate 7 consequence |
|---|---|---|
| Artifact identity | `Asset` is the compatibility table/API name for one stable artifact; `ArtifactRevision` owns immutable primary history | Add Projects around artifacts; do not wrap or replace them with `AssetGroup` |
| Organization | Nested `Folder` controls browse location and human-readable managed paths; `collection` is free-form artifact metadata | Folder, collection, and Project cannot be auto-converted into one another |
| Cardinality | An artifact has one folder but no semantic parent/container | Reusable components favor many-to-many Project membership |
| Existing libraries | Every artifact works independently and may be a useful single-file record | Migration must leave all existing artifacts usable and Unassigned by default |
| Supporting files | Simple documents can already attach artifact-wide or to one revision | A document becomes a related artifact only when it needs independent identity, revision history, reuse, or handoff |
| Artifact Trash | Soft deletion preserves revisions/files and hides the artifact; permanent purge deletes complete ownership through quarantine | Membership and relationship behavior must preserve restore and prevent dangling IDs |
| Export | An artifact can export complete revision history with a versioned manifest | Project export should compose proven artifact exports rather than invent weaker file copying |
| Recovery | Format-1 matched backup verifies all schema-8 tables, paths, revisions, Trash, and purge journals | Project/membership/relationship tables must join the schema-aware audit before closeout |
| Search/UI | Folder navigation and model search address Assets directly; there is no Project route, view, or filter | Project navigation must remain incremental and keep the existing library available |
| Authorization | One administrator protects all metadata and file routes | Gate 7 adds no per-Project ACL or misleading permission inheritance UI |

Primary evidence is `api/models.py`, `api/schemas.py`, `api/main.py`, the revision,
Trash, export, migration, and recovery services/tests, plus `web/src/ui/App.tsx`,
`Sidebar.tsx`, and `AssetGrid.tsx`.

## Representative terminology examples

```text
ATAK Relay Enclosure                         Single downloaded STL
Project                                      Unassigned artifact
+-- Enclosure CAD (artifact)                 `-- revision history
+-- Print plate (artifact, derived)
+-- Carrier PCB (artifact/component)
+-- Wiring diagram (artifact if versioned)
`-- assembly.pdf (supporting file if simple)
```

```text
Laser-cut workshop sign
Project
+-- logo.svg (source artifact)
+-- sign-layout.lbrn2 (derived artifact)
`-- mounting-template.pdf (documentation artifact or simple attachment)
```

`Project` means the thing being built. `Artifact` remains the architecture/domain
term and `Asset` remains the compatibility table/API name during expansion. Existing
library copy may continue saying Model; a Project surface can say Project items so
Gate 7 does not force a disruptive application-wide terminology rename.

## Proposed Gate 7 subgates

### 7A — Project identity and membership expansion

- Accepted ADR 0009 on 2026-08-23.
- Add Project and many-to-many Project membership without touching artifact bytes.
- Leave every existing artifact Unassigned.
- Add authenticated Project CRUD and membership APIs with strict validation.

Implemented at local commit `6d06e6f`. Migration, API, membership, artifact Trash,
and full-repository evidence are in [SUBGATE_7A_RESULTS.md](SUBGATE_7A_RESULTS.md),
accepted by the owner on 2026-08-23.

### 7B — Project workspace and retrieval

- Add Project navigation, details, search, member counts, and explicit add/remove
  workflows while preserving folders and the standalone library.
- Let upload/import optionally add a new artifact to the current Project without
  changing its folder semantics.
- Prove large Project lists and membership changes remain bounded.

Opened after 7A acceptance under
[the 7B implementation contract](SUBGATE_7B_BASELINE.md).

### 7C — Useful artifact relationships

- Accept ADR 0010.
- Add only canonical directed relations that produce useful labels/actions.
- Enforce same-Project endpoints, membership, no-self-link, duplicate, and cycle
  invariants in one domain service.
- Add a compact relationship editor and readable forward/inverse labels, not a
  general graph editor.

### 7D — Project lifecycle and export

- Accept ADR 0011.
- Add metadata-only Project Trash/restore and explicit permanent metadata deletion;
  never delete member artifacts as a side effect.
- Export a Project manifest, relationships, and complete available artifact history
  with explicit external/missing states.

### 7E — Recovery, compatibility, and closeout

- Extend recovery summaries and consistency checks to Project membership and
  relationship ownership while retaining older format-1 backup verification.
- Prove schema-8 upgrades, Project restore/export, artifact Trash interactions,
  relationship cleanup, and matched backup/restore.
- Keep Asset and legacy projection compatibility; no contraction is authorized.

## Migration and rollback contract

1. Take and verify a matched schema-8 SQLite/storage backup.
2. Expand with new Project and join structures; do not rewrite Asset rows or bytes.
3. Create no Projects or memberships automatically.
4. Keep Folder, collection, tags, and standalone artifact workflows unchanged.
5. Verify foreign ownership and counts before enabling Project writes.
6. Extend backup consistency before Gate 7 closes.

Code rollback during expansion may ignore additive Project tables. Operational
rollback restores the matched schema-8 database/storage pair. Schema contraction or
manual ledger edits are not authorized.

## Entry risks to test

- A Project must not become a second folder tree or alter storage paths.
- Reusable artifacts must not require copies merely to appear in two Projects.
- Removing membership or deleting a Project must not delete artifact history.
- Trashing/restoring an artifact must not corrupt its retained Project memberships.
- Relationship inverses must not be stored twice or disagree.
- Project export cannot expose prepared payloads as ordinary browse files or claim
  external no-copy bytes were included.
- Large Project membership and export must use bounded queries/streaming rather than
  loading arbitrary libraries into browser memory.

## Owner checkpoint

The owner accepted [the decision package](OWNER_CHECKPOINT.md) and ADRs
[0009](../../adr/0009-project-identity-and-membership.md),
[0010](../../adr/0010-project-artifact-relationships.md), and
[0011](../../adr/0011-project-lifecycle-export-and-recovery.md) on 2026-08-23.
Subgate 7A was accepted and 7B is in progress; later subgates retain their own
evidence/acceptance stops.
