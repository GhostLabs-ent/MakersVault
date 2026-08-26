# Gate 7C Project-Scoped Artifact Relationship Contract

**Gate:** 7C — useful artifact relationships

**Status:** Implemented at `e4746f3`; pending owner evidence acceptance

**Opened:** 2026-08-23

**Entry commit:** `8ed8798`

**Entry schema:** 9

**Dependencies:** Gate 7B owner-accepted; ADR 0010 accepted

## Verified entry baseline

`make verify` passed at `8ed8798` before 7C changes:

- API: `122 passed`
- Web: `15 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-9 container smoke, and the
  immutable v5.1 release contract passed

Schema 9 has Project identity, many-to-many membership, bounded workspace retrieval,
and optional ingestion association. It has no relationship table, service, schema,
route, or UI. Membership removal has no relationship ownership to inspect.

## Implementation contract

1. Schema 10 additively creates one empty Project-owned relationship table and no
   backfill. Existing Project, membership, artifact, folder, revision, path, Trash,
   and byte state remains identical through repeated migration.
2. Store only canonical directed `derived_from`, `documentation_for`, and
   `component_of`. `source_of`, `documented_by`, and `contains` are computed display
   labels; generic attachment remains `AssetFile`; arbitrary kinds are rejected.
3. Both endpoints must be distinct, active artifacts with active membership in the
   same active Project. The canonical `(project, source, target, kind)` tuple is
   unique. Cross-Project, inactive, self, missing, and duplicate links fail closed.
4. `derived_from` and `component_of` creation rejects a directed cycle inside the
   same Project and kind. Cycle detection executes in SQLite rather than loading an
   arbitrary relationship graph into application/browser memory.
   `documentation_for` has no traversal rule.
5. Relationship list reads are authenticated, deterministically ordered, filtered
   to active endpoints, and incrementally paged. Creation/deletion returns readable
   endpoint metadata without creating inverse rows.
6. Removing a Project member with links requires an explicit confirmation retry in
   the domain service. Confirmed removal transactionally deletes only that Project's
   incident links and membership; it never moves, trashes, deletes, or rewrites an
   artifact, revision, file, path, or byte.
7. Project metadata Trash retains relationships. Ordinary artifact Trash retains
   them but active Project reads hide links with an inactive endpoint; restore makes
   them visible again. Permanent artifact purge removes incident relationships and
   membership in the existing ownership transaction.
8. Add a compact relationship surface to the Project workspace with bounded member
   search, readable forward/inverse labels, explicit create/delete actions, and
   session-expiry handling. Do not build a general graph editor.
9. Preserve all Gate 7B library, folder, Project, Unassigned, ingestion, and legacy
   API behavior. 7C adds no Project export, Project restore/permanent deletion,
   recovery-format change, nested Projects, ACL, public view, or byte migration.

## Required evidence

- relationship and schema-10 regressions fail against the accepted schema-9 source;
- additive/idempotent migration and empty-by-default table preserve all schema-9
  identities, paths, revisions, memberships, Trash state, and bytes;
- kind, authentication, active Project/member/endpoint, self, canonical duplicate,
  cross-Project, and cycle invariants are enforced through one domain service;
- bounded deterministic list/search and computed inverse labels are proven;
- membership confirmation cleanup, Project/artifact Trash retention, restore
  visibility, and permanent artifact purge cleanup are transactional and isolated;
- relationship UI helpers pass tests and the Project workspace builds;
- the complete repository harness and schema-10 container smoke pass.

## Rollback and deferrals

Schema 10 is additive. Operational rollback after relationship writes requires a
verified matched schema-9 SQLite/storage pair; an older binary must not start
against the newer ledger, and manual ledger/table edits are unsupported. No
filesystem migration or byte rollback exists.

Gate 7D lifecycle/export and Gate 7E recovery/compatibility closeout remain separate
checkpoints. Nothing may be pushed, tagged, or published.

Implementation and verification evidence are recorded in
[SUBGATE_7C_RESULTS.md](SUBGATE_7C_RESULTS.md).
