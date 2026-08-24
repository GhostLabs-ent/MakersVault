# Gate 7B Project Workspace and Retrieval Contract

**Gate:** 7B — Project workspace and retrieval

**Status:** Implemented at `04c6b4c`; pending owner evidence acceptance

**Opened:** 2026-08-23

**Entry commit:** `42e9397`

**Entry schema:** 9

**Dependencies:** Gate 7A owner-accepted; ADRs 0009–0011 accepted

## Verified entry baseline

`make verify` passed at `42e9397` before 7B changes:

- API: `118 passed`
- Web: `13 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-9 container smoke, and the
  immutable v5.1 release contract passed

Schema 9 provides authenticated Project CRUD and many-to-many membership APIs, but
the web client has no Project type, navigation, workspace, or membership action.
`App` selects only library/settings/Trash views, `Sidebar` navigates folders only,
and `AssetGrid` scopes reads and uploads only by folder. Link, file, folder, drag,
and ZIP imports cannot request Project membership.

## Implementation contract

1. Add a distinct Projects section to navigation without replacing All files,
   folders, folder breadcrumbs, or the standalone library.
2. Project lists are authenticated, server-searchable, deterministically ordered,
   and incrementally paginated. The client must not load an arbitrary Project list
   or membership set in one request.
3. A Project workspace shows common metadata, active member count, searchable/tag-
   filterable Project items, and explicit metadata editing. Project screens say
   **Project items** while compatibility library copy may continue saying Models.
4. Adding existing artifacts uses a bounded candidate query that excludes current
   members. Removing an item deletes only that membership after clear confirmation;
   it never moves, trashes, or deletes the artifact or any revision/file bytes.
5. Add an Unassigned Project view for active artifacts that have no membership in
   an active Project. A membership retained only by a trashed Project does not hide
   an artifact from this active-workspace view.
6. File upload, folder upload, drag/drop, direct link import, whole-ZIP import, and
   selected ZIP extraction may optionally request one active Project membership.
   Folder creation and storage placement remain controlled solely by the existing
   folder/path contracts.
7. Project association is validated before a write and committed before success is
   returned. A membership failure cleans up the just-created artifact rather than
   reporting a Project upload that became silently Unassigned.
8. No Project selection preserves every legacy upload/import response and creates
   no membership. Existing artifacts and APIs remain compatible.
9. Project UI and API routes inherit the current administrator boundary and handle
   session expiry consistently. 7B adds no ACL, public view, or durable bearer URL.
10. 7B adds no relationship rows, Project export, permanent Project deletion,
    nested Projects, automatic grouping, custom fields, or artifact byte migration.

## Required evidence

- regression tests fail against the accepted 7A source before implementation;
- Project list, item, candidate, and Unassigned paging/filter semantics are bounded
  and deterministic;
- existing-item add/remove and optional upload/import association preserve artifact
  paths, folders, revisions, bytes, and many-to-many reuse;
- invalid/trashed Project association cannot leave a new artifact or managed file;
- file/folder/drag/ZIP client helpers retain Project scope while nested folders
  retain their independent semantics;
- Project navigation/workspace builds and its pure workflow helpers pass tests;
- the complete repository harness and schema-9 container smoke pass.

## Rollback and deferrals

No schema migration is authorized in 7B. Code rollback to accepted 7A ignores the
new presentation and optional request fields; database/storage rollback is not
required because 7B creates only ordinary Project memberships through the accepted
schema-9 contract. Operator rollback remains a matched pair whenever data rollback
is actually requested.

Gate 7C relationships, 7D lifecycle/export, and 7E recovery closeout remain
separate checkpoints. Nothing may be pushed, tagged, or published.

Implementation and verification evidence are recorded in
[SUBGATE_7B_RESULTS.md](SUBGATE_7B_RESULTS.md).
