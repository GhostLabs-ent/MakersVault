# Gate 7A Project Identity and Membership Results

**Gate:** 7A — Project identity and membership expansion

**Status:** Accepted by the owner

**Date:** 2026-08-23

**Entry commit:** `7682971`

**Implementation commit:** `6d06e6f`

**Accepted:** 2026-08-23

**Schema:** 8 -> 9

**Publication state:** Local only. Nothing was pushed, tagged, or published.

## Accepted contract

The owner accepted the Gate 7 decision package and ADRs 0009–0011 on 2026-08-23.
Gate 7A was authorized to add Project identity and explicit many-to-many artifact
membership while leaving every existing artifact Unassigned and preserving folders,
metadata, revision history, paths, and bytes.

## Delivered behavior

- Schema 9 adds `project` and `projectmembership` without creating Project or
  membership rows during migration.
- Active Project names are globally case-insensitive unique. Name, notes, creator,
  HTTP(S) source URL, license, tags, timestamps, and metadata-only Trash state are
  bounded and validated.
- Authenticated endpoints create, list, retrieve, update, and metadata-delete
  Projects; list, add, and remove Project items; and return active member counts.
- One artifact can be a member of several Projects without copies or changes to its
  folder, storage path, current revision, metadata, or primary bytes.
- Project deletion hides only Project metadata and retains membership. It never
  deletes or trashes an artifact.
- Artifact Trash retains membership but hides the artifact from active Project item
  queries. Restore makes the retained membership visible again.
- Permanent artifact purge removes Project membership in the same database
  transaction as the artifact's other owned rows before quarantine cleanup.
- Project list and item reads are authenticated, deterministic, paginated, and
  bounded. Gate 7A adds no Project UI or authorization boundary.

## Regression-first evidence

`api/tests/test_projects.py` and the schema-9 migration assertions were run before
the implementation. Collection failed because `Project` and `ProjectMembership`
did not exist in the schema-8 model, confirming that the new checks detect the
missing behavior rather than merely exercising the harness.

After implementation, the focused gate passed:

```text
python -m pytest -q tests/test_migrations.py tests/test_projects.py tests/test_trash.py
24 passed
```

The tests directly prove authentication, metadata validation, active-name
uniqueness, additive/idempotent schema-8 migration, many-to-many reuse, duplicate
rejection, byte/path/revision preservation, membership removal isolation, Project
metadata deletion, artifact Trash/restore visibility, and permanent-purge cleanup.

## Full verification

The untouched entry baseline at `7682971` passed `make verify` before changes:

- API: `112 passed`
- Web: `13 passed`; TypeScript and production build passed
- Bridge: Go tests and build passed
- Compose/security and container smoke passed at schema 8
- Release contract passed; the immutable v5.1 candidate remained unchanged

After implementation, `make verify` passed on 2026-08-23:

- API: `118 passed`
- Web: `13 passed`; TypeScript and production build passed
- Bridge: Go tests and build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose checks
  passed
- Container smoke passed with non-root API/web processes and schema 9
- Release contract passed; the immutable v5.1 candidate remained unchanged
- `git diff --check` and Python compile checks passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking.

## Migration and rollback evidence

The schema-8 fixture reaches schema 9 repeatedly with identical Asset and revision
IDs, folders, source paths, managed paths, current revisions, and Trash state. The
new tables remain empty, and their unique/index/foreign-key declarations are
inspected directly.

No filesystem migration or backfill exists. Code rollback must not start an older
binary against schema 9 because its migration ledger correctly rejects an unknown
newer version. Operational rollback remains restoration of the matched schema-8
SQLite/storage pair; schema contraction and manual ledger editing are unsupported.

## Residual scope and next checkpoint

- Gate 7B owns Project navigation, workspace UI, Project search/retrieval workflows,
  explicit add/remove interaction, optional upload/import membership, and bounded
  large-Project evidence.
- Gate 7C owns canonical artifact relationships and cycle rules.
- Gate 7D owns visible Project Trash/restore/permanent deletion and Project export.
- Gate 7E owns schema-aware matched backup verification and Gate 7 closeout.

Owner acceptance of this evidence authorizes the 7B baseline and implementation.
It does not authorize push, tag, publication, relationships, export, or later-gate
features.
