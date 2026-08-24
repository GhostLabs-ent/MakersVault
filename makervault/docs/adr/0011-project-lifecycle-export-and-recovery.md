# ADR 0011: Project lifecycle, export, and recovery

**Status:** Accepted

**Proposed:** 2026-08-22

**Accepted:** 2026-08-23

## Context

Projects add valuable organization but do not own artifact bytes. Treating Project
delete as recursive artifact deletion would be surprising and dangerous. Project
export and backup must preserve relationship meaning without weakening the revision,
prepared-payload, external ownership, or matched-pair contracts from Gate 6.

## Decision

### Trash and deletion

Normal Project deletion is metadata-only. It hides the Project but retains its
membership and relationship graph for exact restore. It never trashes or deletes a
member artifact. Project metadata is retained until explicit permanent deletion and
does not participate in capacity-based artifact Trash purge because it owns no
managed content bytes.

Permanent Project deletion requires typed confirmation and removes only Project
metadata, membership, and scoped relationships. Artifact rows, revisions, files,
folders, and external sources remain untouched.

Ordinary artifact Trash retains membership/relationships while hiding the endpoint
from active Project views. Artifact restore makes those links visible again.
Permanent artifact purge removes its membership and relationship rows inside the
same durable ownership transaction before managed-byte cleanup completes.

### Export

Project export is an explicit ZIP64-capable operation with a versioned Project
manifest containing Project metadata, membership, relationship direction/types,
artifact IDs, and per-artifact export status. It composes the proven complete
artifact-history inventory: available revision primaries, visible artifact/revision
attachments, internal-role prepared payloads in labelled internal paths, hashes,
and explicit unavailable/changed external references.

Prepared payloads do not become ordinary browsable supporting files. External
no-copy bytes are included only if a future explicit copy/import operation creates
managed ownership; the export never claims absent external bytes are present.

### Search, authorization, and recovery

Project metadata and active membership are searchable through bounded authenticated
queries. Gate 7 adds no ACLs. Server backup remains format 1 and must enumerate and
validate Project, membership, relationship, and Project Trash ownership while still
verifying older manifests. Operational rollback remains a matched SQLite/storage
restore; export is portability/retrieval evidence, not a substitute for server
backup.

## Alternatives considered

- **Cascade Project delete into artifact Trash:** dangerous when artifacts are shared
  across Projects and contradicts membership semantics.
- **Apply file-capacity retention to Projects:** destroys useful metadata without
  reclaiming meaningful storage.
- **Export current files only:** loses the history and provenance Gate 6 made
  authoritative.
- **Treat export as a full server backup:** omits configuration and unrelated vault
  state and confuses two recovery contracts.

## Consequences

Project Trash can restore semantic organization exactly without duplicating bytes.
Exports may be large because they deliberately include complete available histories;
capacity reserve, streaming, cleanup, and per-artifact outcomes are required.
Recovery inspection gains relational integrity checks but the outer backup format
does not need to change.
