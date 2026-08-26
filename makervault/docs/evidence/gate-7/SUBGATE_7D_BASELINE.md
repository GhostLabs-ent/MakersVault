# Gate 7D Project Lifecycle and Export Contract

**Gate:** 7D — Project lifecycle and complete-history export

**Status:** Implemented at `3c2edd2`; accepted by the owner

**Opened:** 2026-08-25

**Entry commit:** `47dd233`

**Entry schema:** 10

**Dependencies:** Gate 7C owner-accepted; ADR 0011 accepted

## Verified entry baseline

`make verify` passed at `47dd233` before 7D changes:

- API: `128 passed`
- Web: `17 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-10 container smoke, and the
  immutable v5.1 release contract passed

Schema 10 already preserves Project membership and relationships through metadata
Trash, but there is no Project Trash list, restore route, permanent Project deletion,
Project export service, or Project export UI. Artifact history export is the proven
single-artifact inventory that 7D must compose without weakening it.

## Implementation contract

1. Keep schema 10 unchanged. Gate 7D adds no database/filesystem migration, no
   Project-owned bytes, and no change to artifact paths, revisions, files, or
   capacity-based artifact Trash retention.
2. Existing Project delete remains metadata-only and retains the Project,
   memberships, and relationships. Add an authenticated, deterministic, bounded
   Project Trash list with retained active/trashed member and relationship counts.
3. Restore only a trashed Project. Preserve its ID, metadata, memberships, and
   relationships exactly; clear `deleted_at` and update its timestamp. If its name
   now conflicts with an active Project, fail with a structured conflict rather
   than silently renaming either Project.
4. Permanently delete only a trashed Project after the exact typed confirmation
   `PERMANENTLY DELETE PROJECT`. In one Project-domain transaction, delete its
   relationships, memberships, and Project row only. Never move, trash, delete, or
   rewrite any member artifact, revision, file, path, external source, or byte.
5. Export only an active Project through one authenticated download. Snapshot all
   retained membership rows, including members currently in artifact Trash, and
   all stored Project relationships so semantic state is not silently omitted.
6. Use a versioned `makersvault-project-export` manifest with Project metadata,
   membership timestamps/states, canonical relationship direction/type, artifact
   IDs, and a per-artifact `complete`, `partial`, or `unavailable` export outcome.
   Ordering and archive paths must be deterministic and collision-safe.
7. Compose the proven artifact-history inventory directly under an artifact-ID
   namespace. Include each available immutable revision primary, visible artifact
   and revision attachments, and internal-role prepared payload under explicitly
   labelled internal paths with hashes and content states. Do not expose prepared
   payloads as ordinary attachments.
8. Never claim absent bytes are present. Pending, failed, unavailable, changed,
   unreadable, or missing primaries and related files remain explicit in manifests
   with no archive entry. External no-copy bytes are not imported or copied by
   export.
9. Use ZIP64, the existing protected-download headers, storage-reserve check, safe
   names, temporary `.exports` ownership, failure cleanup, and response-background
   cleanup. Read membership/relationship state in deterministic batches and write
   one artifact inventory at a time rather than loading an arbitrary Project into
   browser memory.
10. Add compact Project restore/permanent-delete controls to Trash and an Export
    action to the active Project workspace with session-expiry handling. Project
    Trash is never included in Empty model Trash and has no retention timer.
11. Preserve Gate 7C relationship, Gate 7B workspace/ingestion, standalone library,
    folder, artifact history/export, and legacy API behavior. Add no recovery-format
    changes, import/restore from Project export, nested Projects, ACL, public view,
    server backup claim, push, tag, or publication.

## Required evidence

- lifecycle/export regressions fail against the accepted 7C source;
- Project Trash list, restore, name conflict, typed permanent deletion, and
  authentication rules are enforced through the Project domain service;
- restore preserves relationship/member identities and permanent deletion removes
  only Project-owned rows while member histories, paths, files, and bytes remain;
- the Project manifest preserves metadata, membership, canonical relationships,
  Trash state, stable ordering, and per-artifact outcomes;
- managed histories, supporting files, revision attachments, and prepared internal
  payloads are correctly namespaced and hashed while changed/missing/external bytes
  are represented honestly;
- ZIP64/resource/temporary cleanup and response headers are proven;
- Project Trash/export UI helpers pass tests and the complete web build passes;
- the complete repository harness and unchanged schema-10 container smoke pass.

## Rollback and deferrals

Gate 7D has no migration. Code rollback leaves ordinary schema-10 Project,
membership, and relationship data valid. A permanently deleted Project cannot be
reconstructed from live rows; recovery requires a previously verified matched
SQLite/storage backup. Project export is a retrieval/portability artifact, not a
server backup or an authorized import format.

Gate 7E recovery/compatibility and Gate 7 closeout remain separate. Nothing may be
pushed, tagged, or published.

Implementation and verification evidence are recorded in
[SUBGATE_7D_RESULTS.md](SUBGATE_7D_RESULTS.md).
