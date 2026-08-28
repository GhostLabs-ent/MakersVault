# Gate 9B Artifact-Machine Context Results

**Gate:** 9B — Artifact associations and exact prepared-machine targets

**Status:** Accepted by the owner

**Date:** 2026-08-27

**Accepted:** 2026-08-28

**Schema amendment approval:** 2026-08-27

**Entry commit:** `3af0669`

**Implementation commit:** `a9b09aa`

**Schema:** 11 -> 12

**Publication state:** Local only. Nothing was pushed, tagged, released, deployed,
connected to a device, or published.

## Delivered behavior

- Additive schema 12 creates the empty-by-default `artifactmachine` table with
  `(asset_id, machine_id)` identity and adds nullable `prepared_machine_id`
  foreign keys to current Assets and immutable Artifact Revisions. Migration 11
  remains unchanged.
- Authenticated endpoints explicitly add, list, and remove neutral associations.
  Results are deterministic and always say `Descriptive context only. No job was
  sent.` They do not claim compatibility, fabrication, dispatch, or provenance.
- A separate authenticated endpoint sets or clears an exact prepared target on
  both the current Asset mirror and current Revision in one transaction. Only an
  active FDM or resin profile can receive a new exact target, and a prepared
  snapshot must already exist.
- Supplied printer text is never automatically or fuzzily linked. A regression
  uses G-code whose extracted printer string exactly equals an existing profile
  name and proves both new reference columns remain null until the explicit
  request.
- Replacing or removing a prepared payload clears the current exact target.
  Replacing primary content creates a new unprepared Revision while retaining the
  historical target on its immutable Revision. Restoring that historical Revision
  creates a new current Revision with the same still-valid exact target and copied
  prepared payload.
- Archive retains existing associations and prepared references for descriptive
  reading but blocks new links. Archive-first permanent Machine deletion counts
  and removes association rows and clears current/historical nullable references
  in the same transaction.
- Artifact Trash retains associations and exact prepared context. Confirmed
  permanent Artifact purge removes its association rows inside the existing
  ownership transaction; its Asset and Revision references disappear with those
  already-owned rows.
- Association, archive, restore, and permanent-delete operations do not rewrite
  prepared metadata, payload bytes, primary bytes, storage paths, Revisions, or
  Projects.

## Regression-first evidence

The schema-12 migration test and authenticated route test were first run against
the accepted Gate 9A implementation. Both failed for the expected missing
behavior:

- the representative schema-11 fixture remained at version 11 instead of 12; and
- the new context route returned `404` instead of reaching the authentication
  boundary and returning `401`.

After implementation, the first affected-surface run passed `38 passed in 11.49s`
across migrations, Machines, Revisions, prepared payloads, and Trash. The final
complete API suite, including the strengthened exact-name/no-auto-link and archived
target cases, passed `159 passed in 23.99s` before the repository-wide run. Tests
exercise real migrations, SQLite constraints, services, file storage, and HTTP
routes; the unit under test is not stubbed.

## Migration and lifecycle evidence

A representative schema-11 database reaches schema 12 repeatedly while preserving
selected existing Asset, Revision, and Machine state exactly. The association
table starts empty; both new columns start null; the composite identity rejects
duplicates; and the association and nullable target foreign keys point to their
approved owners. Fresh databases also contain the schema-12 structures.

The lifecycle regressions prove both cleanup directions:

- permanent Machine deletion removes its association rows and clears all matching
  Asset/Revision references while retaining artifacts, history, prepared source
  snapshots, payloads, paths, and bytes; and
- permanent Artifact deletion removes its association rows while leaving the
  Machine profile intact.

No filesystem migration, backfill, source-text matching, or stored-byte move
exists. Operational rollback remains restoration of a matched schema-11
SQLite/storage pair. An older application must not be started against schema 12;
the immutable migration ledger correctly rejects unknown newer versions.

## Complete verification

The complete repository `make verify` passed at `a9b09aa` under a workstation
sleep inhibitor:

- API: `159 passed in 24.23s`
- Web: the complete gate reused its already-verified typecheck, `21` tests, and
  production-build Docker layer; no web source changed in 9B
- Bridge tests and native build passed under Go 1.26.6
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation passed; production Compose still rejects missing authentication
  secrets
- Container smoke passed direct/same-origin access, security headers, the 512 MiB
  file policy, non-root API/web processes, and schema 12
- The immutable v5.1 release contract passed
- `git diff --check` and Python compile checks passed

The unrelated untracked desktop architecture note remained outside Gate 9 and was
not modified.

## Remaining boundary and owner checkpoint

- Gate 9C owns format-2 artifact-history/Project exports, retrieval filters, and
  the Settings/artifact interface.
- Gate 9D owns recovery contract 4, compatibility proof, and Gate 9 closeout.
- Machine discovery, addresses, credentials, telemetry, queues, file transfer,
  slicing, job history, and start/pause/cancel/stop controls remain excluded.

The owner accepted Gate 9B at implementation commit `a9b09aa` with evidence commit
`d375cd2` on 2026-08-28. Gate 9C may proceed only after its separate
export/retrieval/UI recommendations are approved. Acceptance does not authorize
push, tag, release, deployment, device connection, recovery-contract changes, or
publication.
