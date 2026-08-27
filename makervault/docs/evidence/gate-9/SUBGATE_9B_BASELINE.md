# Gate 9B Relationship and Prepared-Target Baseline

**Gate:** 9B — Artifact associations and exact prepared-machine targets

**Status:** Owner checkpoint open; migration version amendment required

**Date:** 2026-08-27

**Entry commit:** `1467607`

**Accepted profile implementation:** `eb3f0bf`

**Entry schema:** 11

**Publication state:** Local only. Nothing is authorized for push, tag, release,
deployment, device connection, or publication.

## Verified entry state

Gate 9A was accepted on 2026-08-27 after the complete repository gate passed at
`eb3f0bf`: 154 API tests, 21 web tests plus typecheck/build, bridge tests/build,
Compose/security validation, schema-11 container smoke, and the immutable v5.1
release contract. Schema 11 is now an accepted immutable migration containing the
empty-by-default descriptive `machineprofile` table and lifecycle contract.

The unrelated untracked desktop architecture note remains outside Gate 9 and was
not modified.

## Current schema gap

Gate 9B requires new persisted structures that schema 11 does not contain:

- an optional many-to-many neutral Artifact-to-Machine association table;
- an optional exact `prepared_machine_id` on the current Asset mirror; and
- the same optional exact target on each immutable Artifact Revision.

There is no existing generic relationship table or safe JSON contract that can
represent these identities and enforce reference integrity. `AppConfig`, prepared
metadata JSON, and Project relationships have different ownership semantics and
must not be overloaded.

## Required migration decision

The Gate 9 architecture originally described all machine work as schema 11. Gate
9A used and proved that version for profiles before the 9B structures existed.
Migration-ledger entries are immutable once accepted: changing migration 11 now
would leave a database that already recorded version 11 without the new table and
columns, while a fresh database at the same version would contain them. The two
databases would falsely claim the same schema.

**Recommendation:** amend the Gate 9 version plan so 9B uses additive schema 12.
Do not rewrite migration 11, encode references in JSON, or defer integrity to the
interface. Artifact-history/Project export format 2, server-backup outer format 1,
and recovery contract 4 remain unchanged recommendations for 9C–9D.

## Proposed schema-12 contract

1. Add `artifactmachine` with `(asset_id, machine_id)` as its unique identity and a
   created timestamp. Foreign keys reference the existing Asset and Machine profile
   rows. The relationship remains neutral: **associated with**, never fabricated
   on, compatible with, queued for, or sent to.
2. Add nullable `prepared_machine_id` foreign keys to Asset and Artifact Revision.
   Both default to null; migration performs no matching or backfill and changes no
   prepared metadata, payload, path, revision, or stored byte.
3. Only active FDM/resin profiles may receive a new exact prepared target. Archived
   profiles remain readable on existing references but cannot receive new links.
4. New associations and prepared targets require explicit authenticated requests.
   Supplied printer text is never automatically or fuzzily linked.
5. Profile permanent deletion counts and removes association rows and clears both
   nullable prepared-reference columns in one transaction before deleting the
   archived profile. No Artifact, Revision, Project, prepared snapshot/payload, or
   byte is deleted or rewritten.
6. Artifact Trash retains machine context. Permanent Artifact purge removes its
   association rows in the existing ownership transaction; revision and Asset
   prepared references disappear only with their already-owned rows.

## Regression and rollback requirements

- Prove a representative schema-11 database reaches schema 12 idempotently with
  identical existing tables/rows and empty/null new state.
- Prove direct database constraints, explicit linking, category/archive rejection,
  revision-exact targets, no automatic matching, Trash behavior, and both permanent
  deletion cleanup directions through real migration/service/API seams.
- Re-run prepared-print, revision, Trash, Machine, Project, migration, and complete
  repository verification, including schema-12 container smoke.
- Operational rollback remains a matched schema-11 SQLite/storage restore. No
  filesystem migration or stored-byte move exists.

Implementation is paused until the owner approves the schema-12 amendment. That
approval authorizes only 9B; it does not authorize 9C export/UI work, 9D recovery
changes, machine control, push, tag, release, deployment, or publication.
