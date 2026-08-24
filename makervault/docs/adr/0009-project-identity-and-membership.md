# ADR 0009: Project identity and artifact membership

**Status:** Accepted

**Proposed:** 2026-08-22

**Accepted:** 2026-08-23

## Context

Gate 6 established stable artifacts and immutable revisions. Folders organize where
artifacts are browsed and may influence human-readable storage; free-form collection
metadata supplies a label. Neither represents the real-world thing being built.

Automatically treating folders or collections as Projects would silently guess at
user intent. Requiring one Project per artifact would add empty hierarchy around
the many useful standalone models already in a library. Restricting an artifact to
one Project would force duplicate records for reusable components.

## Decision

Add a stable `Project` identity and an explicit many-to-many Project/Asset membership
join. `Asset` remains the compatibility table/API term for the domain Artifact.

A Project initially owns:

- globally case-insensitive unique active name;
- notes, creator, source URL, license, and tags;
- created/updated timestamps; and
- metadata-only Trash state.

Projects are flat: no parent Project, folder, storage-template authority, custom
fields, status taxonomy, or part-number scheme is added in Gate 7.

Migration creates the additive tables but no Project or membership rows. Every
existing artifact remains Unassigned and unchanged. New and existing artifacts may
be added explicitly to any number of Projects. The standalone folder library remains
a first-class view.

## Invariants

- A membership pair is unique.
- Project membership does not move files or change folder, collection, tags,
  artifact metadata, current revision, or Trash state.
- A trashed Project retains membership. A trashed artifact retains membership but is
  hidden from the active Project view until restored.
- Project operations are authenticated under the existing single-administrator
  model; membership does not create an authorization boundary.

## Alternatives considered

- **One generated Project per artifact:** mechanically complete but creates clutter
  and a meaningless wrapper around standalone models.
- **Folder-to-Project migration:** convenient for some libraries but conflates
  physical organization with what is being built.
- **Collection-to-Project migration:** treats unvalidated free-form labels as stable
  identity and can merge unrelated artifacts.
- **One Project per artifact:** simpler foreign key but prevents safe reuse.
- **Temporary AssetGroup:** adds a disposable hierarchy already rejected by product
  strategy.

## Consequences

Project queries require a join, and UI must explain Unassigned versus folders.
Many-to-many membership makes reuse honest and keeps artifact history canonical.
The additive migration is cheap and performs no filesystem work.

## Migration and rollback

Expand with Project and membership tables, indexes, and uniqueness constraints;
create zero rows; verify every existing Asset and storage path is unchanged. Code
rollback may ignore the additive tables. Operational rollback remains restoration of
the matched schema-8 database/storage backup. No schema contraction is authorized.
