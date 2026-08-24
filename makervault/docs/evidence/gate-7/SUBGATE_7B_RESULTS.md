# Gate 7B Project Workspace and Retrieval Results

**Gate:** 7B — Project workspace and retrieval

**Status:** Implemented; pending owner evidence acceptance

**Date:** 2026-08-23

**Entry commit:** `42e9397`

**Implementation commit:** `04c6b4c`

**Schema:** 9 (unchanged)

**Publication state:** Local only. Nothing was pushed, tagged, or published.

## Delivered behavior

- The sidebar now has a bounded, server-searchable Projects section, Project
  creation, active member counts, incremental paging, and an Unassigned view while
  retaining All files, the folder tree, root-folder creation, and the standalone
  library.
- A Project workspace shows and edits name, notes, creator, source URL, license,
  and tags; reports the active member count; and reuses the searchable/tag-filtered,
  incrementally paged artifact grid.
- Adding existing artifacts uses a bounded candidate endpoint that excludes current
  members. Bulk removal requires confirmation and deletes only membership; the
  artifact's folder, history, files, and bytes remain owned by the library.
- Project, item, and candidate lists are deterministically ordered and use
  `X-Has-More`/`X-Next-Offset` page metadata. Candidate pages are capped at 200 and
  the UI requests 40; Project navigation requests 50 at a time.
- Unassigned means an active artifact with no membership in an active Project. A
  membership retained by a metadata-trashed Project does not conceal the artifact.
- File, folder, drag/drop, direct-link, whole-ZIP, and selected-ZIP imports may add
  the new artifact to one active Project. Folder and nested-path inputs remain
  independent of Project membership.
- Association is validated before artifact creation/download and committed before
  success. A simulated post-write membership failure proves compensation removes
  both the new artifact row and managed file.
- Omitting `project_id` keeps the legacy upload/import contract and produces no
  membership. No schema, artifact path, revision, relationship, export, lifecycle,
  ACL, or public-access behavior changed.

## Regression-first evidence

New Project paging/scope and upload-association checks were first run against the
accepted 7A source. They failed at the expected missing behavior: Project responses
had no bounded-page headers and upload ignored `project_id`, leaving no membership.
The checks therefore detect the 7B behavior rather than merely exercising the
harness.

After implementation, the focused API gate passed:

```text
python -m pytest -q tests/test_projects.py
9 passed
```

The focused tests prove authenticated CRUD compatibility, many-to-many reuse,
metadata-only deletion, artifact Trash/restore/purge behavior, bounded Project/item/
candidate retrieval, tag/search scope, active-Project Unassigned semantics, folder-
independent upload association, validation-before-write for invalid and trashed
Projects, cleanup after membership failure, direct-link association and pre-download
validation, and selected-ZIP association with byte preservation.

The pure web workflow regression proves nested folder creation and Project
membership remain separate upload inputs, while a legacy upload supplies neither.
The complete web verification passed with `15 passed`, TypeScript type checking,
and a production build.

## Full verification

The untouched entry baseline at `42e9397` passed `make verify` before changes:

- API: `118 passed`
- Web: `13 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-9 container smoke, and the
  immutable v5.1 release contract passed

After implementation, `make verify` passed on 2026-08-23 while sleep was inhibited:

- API: `122 passed`
- Web: `15 passed`; TypeScript and production build passed
- Bridge: Go tests and build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose checks
  passed; production Compose still rejects missing authentication secrets
- Container smoke passed for direct and same-origin API access, security headers,
  file-size policy, non-root API/web processes, and schema 9
- The immutable v5.1 release contract passed unchanged
- `git diff --check` and the staged secret-pattern review passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking.

## Rollback and residual scope

Gate 7B creates no migration. Code rollback to the accepted 7A implementation can
ignore the optional request fields and workspace presentation; existing schema-9
Project memberships remain valid ordinary 7A data. If data rollback is explicitly
requested, restore a verified matched SQLite/storage pair rather than editing the
migration ledger or deleting files manually.

- Gate 7C still owns canonical artifact relationships and cycle rules.
- Gate 7D still owns visible Project Trash/restore/permanent metadata deletion and
  Project export.
- Gate 7E still owns schema-aware Project recovery checks, compatibility, and Gate
  7 closeout.

Owner acceptance of this evidence may open Gate 7C planning/implementation. It does
not authorize push, tag, publication, relationships, export, or later-gate work.
