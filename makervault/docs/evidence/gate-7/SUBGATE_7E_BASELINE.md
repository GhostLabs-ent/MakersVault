# Gate 7E Recovery, Compatibility, and Closeout Contract

**Gate:** 7E — Project recovery, compatibility, and Gate 7 closeout

**Status:** In progress

**Opened:** 2026-08-25

**Entry commit:** `b66b83f`

**Entry schema:** 10

**Entry backup format:** `makersvault-backup` format 1; recovery contract 2

**Dependencies:** Gate 7D owner-accepted; ADR 0011 accepted

## Verified entry baseline

`make verify` passed at `b66b83f` before 7E changes:

- API: `132 passed`
- Web: `20 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-10 container smoke, and the
  immutable v5.1 release contract passed

The format-1 recovery implementation already proves matched SQLite/storage
integrity for schema-8 artifact history, Trash, related files, prepared payloads,
external references, previews, and purge journals. Schema 10 Project,
ProjectMembership, and ProjectRelationship rows are present in the database archive
but are not named in database row counts or checked for relational consistency.

## Implementation contract

1. Keep schema 10, artifact paths, managed bytes, outer `makersvault-backup` format
   1, archive members, and matched SQLite/storage operating procedure unchanged.
   Gate 7E adds inspection truth, tests, and closeout evidence only.
2. Advance the separate recovery-contract marker from 2 to 3 for newly created
   manifests. Count Project, ProjectMembership, and ProjectRelationship rows when
   their tables exist. Databases predating those tables retain their prior summary
   shape rather than acquiring invented Project fields.
3. Extend the standard-library consistency audit with deterministic Project-domain
   counts and sorted ID lists. Report active/trashed Projects and validate that each
   membership references an existing Project and artifact.
4. Validate each relationship's Project, source artifact, and target artifact;
   distinct endpoints; canonical kind; same-Project membership of both endpoints;
   and unique canonical `(project, source, target, kind)` identity. Project Trash is
   valid retained metadata and owns no filesystem path.
5. Treat broken Project ownership as a critical inconsistency. Live audit,
   component audit, backup creation, backup verification, and restored-component
   verification must all use the same Project-aware report and must not repair or
   delete records while inspecting them.
6. Preserve verification of valid older outer-format-1 archives. Explicitly prove
   the original manifest shape without a recovery-contract marker and contract-2
   schema-8 archives remain accepted; reject unsupported future recovery-contract
   markers rather than silently interpreting them as current.
7. Add a representative schema-10 matched-pair fixture with active and trashed
   Projects, active and trashed shared artifacts, memberships, canonical
   relationships, multiple revisions, related files, prepared data, and external
   no-copy truth. Prove create, verify, extract, and exact restored-component
   verification without changing Project or artifact identities.
8. Prove corruption detection from database inputs, not by substituting the audit:
   orphan Project/member endpoints, non-member relationship endpoints, self-links,
   unsupported kinds, and duplicate canonical relationships must make the matched
   pair inconsistent and prevent backup creation.
9. Re-run schema-8-to-10 idempotent migration and compatibility evidence together
   with Project lifecycle/export, relationship, Project, artifact Trash, recovery,
   and legacy API suites. Existing schema-5 and schema-8 fixtures must remain green.
10. Keep Project export a retrieval artifact, not an import or server-backup format.
    Add no restore-from-Project-export path, schema contraction, database repair,
    byte move, ACL, nested Project, push, tag, or publication.

## Required evidence

- Project recovery regressions fail against the accepted 7D source because schema-10
  tables are absent from row counts/audit output or corruption is not rejected;
- a valid schema-10 Project graph survives backup create/verify/extract/restored
  verification with outer format 1 and recovery contract 3;
- every required Project ownership corruption produces explicit deterministic IDs,
  `status: inconsistent`, and backup-creation refusal;
- original format-1 and contract-2 schema-8 archives remain verifiable while future
  recovery-contract versions fail closed;
- schema-8-to-10 migration preserves existing artifact/revision identities and
  paths and creates no Project graph automatically;
- Gate 7A–7D lifecycle, retrieval, relationship, Trash, and export behavior remains
  green with the complete repository harness and schema-10 container smoke;
- final diff, secret/debug, release-contract, and local publication-boundary review
  passes before evidence is presented.

## Rollback and closeout boundary

Gate 7E has no migration or filesystem mutation. Code rollback leaves format-1
archives and schema-10 live data unchanged; newly created recovery-contract-3
manifests require the matching verifier. Operational rollback remains restoration
of a previously verified matched SQLite/storage pair with services stopped.

Gate 7 closes only after the owner accepts 7E evidence. Gate 8, push, tag,
publication, schema contraction, and Project-export import remain unauthorized.
