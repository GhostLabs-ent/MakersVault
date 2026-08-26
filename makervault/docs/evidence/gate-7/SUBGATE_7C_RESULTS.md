# Gate 7C Project-Scoped Artifact Relationship Results

**Gate:** 7C — useful artifact relationships

**Status:** Accepted by the owner

**Date:** 2026-08-25

**Entry commit:** `8ed8798`

**Implementation commit:** `e4746f3`

**Accepted:** 2026-08-25

**Schema:** 9 -> 10

**Publication state:** Local only. Nothing was pushed, tagged, or published.

## Delivered behavior

- Schema 10 additively creates an empty Project-owned relationship table with
  Project/source/target foreign keys, distinct endpoints, and a unique canonical
  `(project, source, target, kind)` tuple. It performs no backfill or byte move.
- Only canonical `derived_from`, `documentation_for`, and `component_of` rows are
  stored. The API and UI compute readable forward/inverse labels (`Derived from` /
  `Source of`, `Documents` / `Documented by`, and `Component of` / `Contains`)
  without storing inverse rows.
- One relationship service enforces authenticated active Project, active distinct
  endpoints, same-Project membership, supported kind, duplicate, and cycle rules.
  `derived_from` and `component_of` cycle checks use a scoped recursive SQLite
  query; `documentation_for` remains non-transitive.
- Relationship reads are deterministic and bounded with incremental page headers.
  Create and delete actions return or preserve artifact identity, history, paths,
  files, and bytes.
- Removing a linked Project member first returns a structured confirmation
  requirement. A confirmed retry transactionally removes only that Project's
  incident relationships and membership.
- Project metadata Trash and ordinary artifact Trash retain relationship rows.
  Active reads hide relationships with a trashed endpoint, restore makes them
  visible again, and permanent artifact purge removes incident relationships and
  memberships in the existing ownership transaction.
- The Project workspace now has a compact relationship surface with two bounded
  member searches, explicit type/create/delete actions, readable inverse context,
  incremental loading, and existing session-expiry handling. It is not a general
  graph editor.
- Gate 7B library, folder, Unassigned, Project, ingestion, and legacy API behavior
  remains available. No Project export, lifecycle expansion, recovery-format
  change, ACL, public view, or byte migration was added.

## Regression-first evidence

The new backend relationship suite and schema-10 migration assertions were first
run against the accepted schema-9 source. Collection failed because
`ProjectRelationship` did not exist. The new web helper regression likewise failed
because the relationship module did not exist. These failures were the expected
missing 7C behavior rather than failures in an already-existing path.

After implementation, the focused backend gate passed:

```text
python -m pytest -q tests/test_migrations.py tests/test_project_relationships.py
13 passed
```

The broader Project/Trash ownership gate also passed:

```text
python -m pytest -q tests/test_migrations.py tests/test_project_relationships.py tests/test_projects.py tests/test_trash.py
34 passed
```

The relationship tests prove authentication; canonical kinds and labels; active,
same-Project member endpoints; self/duplicate/cross-Project rejection; deterministic
paging; explicit deletion without artifact loss; recursive cycle rejection;
membership cleanup confirmation; Project/artifact Trash retention; restore
visibility; and permanent-purge isolation. Web relationship-label regressions pass
as part of the complete `17 passed` client gate, TypeScript type checking, and the
production build.

## Full verification

The untouched entry baseline at `8ed8798` passed `make verify` before changes:

- API: `122 passed`
- Web: `15 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-9 container smoke, and the
  immutable v5.1 release contract passed

After implementation, `make verify` passed on 2026-08-25 while sleep was inhibited:

- API: `128 passed`
- Web: `17 passed`; TypeScript and production build passed
- Bridge: Go tests and build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose checks
  passed; production Compose still rejects missing authentication secrets
- Container smoke passed for direct and same-origin API access, security headers,
  the 512 MiB file policy, non-root API/web processes, and schema 10
- The immutable v5.1 release contract passed unchanged
- `git diff --check` and the scoped staged-file review passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking.

## Migration, rollback, and residual scope

The schema-9 fixture reaches schema 10 repeatedly with identical artifact,
revision, Project, and membership rows, including IDs, folders, managed paths,
current revisions, and Trash state. The relationship table remains empty; its named
unique index, foreign keys, and database-level kind constraint are inspected
directly.

Schema 10 is additive, but an older binary must not start against its newer ledger.
Operational rollback after relationship writes remains restoration of a verified
matched schema-9 SQLite/storage pair. Schema contraction, manual ledger edits, and
manual relationship-table removal are unsupported.

- Gate 7D still owns visible Project Trash/restore/permanent metadata deletion and
  Project export.
- Gate 7E still owns schema-aware relationship recovery checks, compatibility, and
  Gate 7 closeout.

The owner accepted this evidence on 2026-08-25 and authorized Gate 7D. The
acceptance does not authorize push, tag, publication, or Gate 7E work.
