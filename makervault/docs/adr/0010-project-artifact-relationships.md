# ADR 0010: Project-scoped artifact relationships

**Status:** Accepted

**Proposed:** 2026-08-22

**Accepted:** 2026-08-23

## Context

The roadmap names `derived_from`, `source_of`, `documentation_for`, `assembly_of`,
and `attachment`. Storing that list literally would store both directions of one
fact, duplicate existing attachment ownership, and leave assembly direction unclear.
A generic graph vocabulary would create UI and integrity work without a proven maker
workflow.

## Decision

Store three canonical directed relationship kinds inside one Project:

| Stored kind | Direction | Computed inverse label |
|---|---|---|
| `derived_from` | derived item → source item | Source of |
| `documentation_for` | document item → documented item | Documented by |
| `component_of` | component item → containing assembly item | Contains |

Both endpoints must be distinct, active artifact members of the same active Project.
The canonical `(project, source, target, kind)` tuple is unique. Directed cycles are
rejected for `derived_from` and `component_of`; documentation links need no graph
traversal semantics.

`source_of` is a computed inverse, not a stored kind. Generic `attachment` remains
the existing artifact/revision `AssetFile` contract. A document should become an
Artifact plus `documentation_for` only when independent revision history, reuse,
search, or application handoff adds value. `component_of` replaces the ambiguous
`assembly_of` label.

## Lifecycle

Relationship rows are Project-owned metadata. Project Trash retains them. Permanent
Project deletion removes them. Removing Project membership requires confirmation
when links exist and deletes only links in that Project. Permanent artifact purge
removes every relationship endpoint and membership transactionally; ordinary
artifact Trash retains both for exact restore.

## Alternatives considered

- **Store forward and inverse rows:** makes reads easy but permits disagreement and
  doubles lifecycle work.
- **Use the five roadmap strings unchanged:** retains redundancy and ambiguity.
- **Allow global cross-Project relationships:** obscures which workspace owns the
  meaning and complicates Project export/deletion.
- **Allow arbitrary custom types:** flexible but produces a graph editor before
  useful common workflows are proven.

## Consequences

The UI can show readable forward/inverse labels without exposing graph mechanics.
Relationship creation and membership mutation must go through one service that owns
cycle, duplicate, active-state, and cleanup checks. Later vocabulary additions
require a new migration/decision rather than accepting arbitrary strings.
