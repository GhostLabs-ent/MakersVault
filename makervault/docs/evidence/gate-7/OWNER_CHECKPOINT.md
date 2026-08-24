# Gate 7 Owner Checkpoint

**Status:** Accepted by the owner

**Prepared:** 2026-08-22

**Accepted:** 2026-08-23

Gate 7 changes how MakersVault represents the thing being built. These decisions
must be accepted before schema implementation.

The owner accepted the recommended package without amendments. This acceptance
authorizes subgate 7A only; later subgates retain their evidence checkpoints.

## Recommended decision package

1. **Terms and compatibility**
   - Project: the thing being built.
   - Artifact: the stable domain identity for a design, component, deliverable, or
     independently useful document; the database/API compatibility name stays
     `Asset` during Gate 7.
   - Artifact revision: immutable primary-file history already delivered by Gate 6.
   - Existing library copy may continue saying Model; Project screens use the more
     approachable label **Project items** rather than forcing “artifact” everywhere.

2. **Default migration experience**
   - Every existing artifact remains active, in its current folder, with identical
     metadata, IDs, paths, revisions, and bytes.
   - Existing artifacts start **Unassigned**. MakersVault does not generate one
     Project per artifact or reinterpret folders/collection values as Projects.
   - Later suggestions may offer folder-based grouping, but only an explicit user
     action creates membership.

3. **Membership**
   - Project membership is many-to-many so one reusable component can belong to
     several Projects without duplicating its history or bytes.
   - Projects do not nest and do not control storage paths.
   - Active Project names are globally case-insensitive unique. Initial common
     metadata is name, notes, creator, source URL, license, and tags; arbitrary
     custom fields, status taxonomies, and part-number systems remain deferred.

4. **Canonical relationship vocabulary**
   - Store `derived_from`: source item was derived from target item; display the
     inverse as **Source of** without storing a second relation.
   - Store `documentation_for`: source item documents target item.
   - Store `component_of`: source item is a component of target assembly; display
     the inverse as **Contains**.
   - Do not store `source_of` separately because it is the inverse of
     `derived_from`.
   - Do not store generic `attachment`: simple attachments are already `AssetFile`;
     independently versioned/reusable documents use `documentation_for`.
   - Replace the ambiguous roadmap label `assembly_of` with directional
     `component_of`.

5. **Relationship scope and safety**
   - Relationships are directed and scoped to one Project; both endpoints must be
     active members of that Project.
   - Self-links and duplicate canonical links are rejected. `derived_from` and
     `component_of` cycles are rejected.
   - Removing a member with relationships requires explicit confirmation and
     removes only those Project-scoped links, never either artifact.

6. **Trash and deletion**
   - Deleting a Project is metadata-only and preserves memberships/relationships for
     exact restore. Member artifacts are never trashed or deleted as a side effect.
   - Project metadata consumes negligible managed capacity, so it is retained until
     explicit permanent deletion rather than participating in file-capacity purge.
   - Permanent Project deletion removes only the Project, memberships, and scoped
     relationships after typed confirmation.
   - Trashing an artifact hides it in active Projects but retains membership for
     restore; permanent artifact purge removes its memberships and relationships in
     the same ownership transaction.

7. **Search, permissions, export, and recovery**
   - Projects and Project items are searchable; the standalone folder library and
     Unassigned view remain available.
   - All Project routes inherit the current single-administrator authorization;
     Gate 7 adds no per-Project permissions.
   - Project export composes complete artifact-history exports under a versioned
     Project manifest and records external/unavailable content honestly.
   - Matched backup verification covers Project rows, membership, relationships,
     Trash state, and endpoint ownership before Gate 7 closes.

## Why this package

It adds semantic grouping without turning Projects into storage folders, avoids
mass-created empty wrappers, supports reusable components without copies, and keeps
the initial relationship model small enough to yield understandable UI. It also
preserves every Gate 6 ownership, Trash, and recovery invariant.

## What approval authorizes

Approval accepts ADRs 0009–0011 and authorizes subgate 7A Project/membership schema,
service, API, migration, and focused tests. It does not authorize automatic grouping,
artifact deletion through Project deletion, arbitrary relationship types, nested
Projects, custom fields, per-Project permissions, Gate 8 adapters, or publication.

## Material alternatives

- Generate one Project per existing artifact instead of leaving artifacts
  Unassigned.
- Infer Projects from folders or `collection` metadata.
- Restrict each artifact to one Project.
- Store all five roadmap relationship labels literally, including redundant inverse
  and generic attachment records.
- Apply artifact Trash retention automatically to Project metadata.

Any of these alternatives changes migration, recovery, or user-visible behavior and
must amend the ADRs before schema work.
