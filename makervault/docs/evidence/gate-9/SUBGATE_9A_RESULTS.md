# Gate 9A Machine Profile Lifecycle Results

**Gate:** 9A — Minimal descriptive profiles and lifecycle

**Status:** Accepted by the owner

**Date:** 2026-08-27

**Accepted:** 2026-08-27

**Gate entry commit:** `fc29837`

**Opening checkpoint:** `560eb40`

**Architecture approval:** `41898e1`

**Implementation commit:** `eb3f0bf`

**Schema:** 10 -> 11

**Publication state:** Local only. Nothing was pushed, tagged, released, deployed,
connected to a device, or published.

## Delivered behavior

- Additive schema 11 introduces `machineprofile` with a stable ID, unique active
  name, bounded category, optional manufacturer/model/location/notes, and created,
  updated, and archived timestamps. Migration creates no profile rows and changes
  no existing record or stored byte.
- Categories are restricted in both the API and SQLite to `fdm_printer`,
  `resin_printer`, `laser`, `cnc`, `pcb`, and `other`.
- Authenticated bounded endpoints list, search, filter, create, retrieve, update,
  archive, restore, and permanently delete profiles. Reads are deterministic and
  paginated.
- Input schemas reject unknown fields, so a client cannot smuggle an address,
  hostname, credential, device setting, or other undeclared control field into a
  profile.
- Active names are case-insensitively unique. Archiving releases the name;
  restoration fails with an actionable conflict if another active profile now
  uses it.
- Archived profiles remain directly readable but are excluded from the default
  list and cannot be updated. Permanent deletion requires archival and the exact
  `PERMANENTLY DELETE MACHINE` confirmation.
- The deletion result already reports association and prepared-reference cleanup
  counts as zero. Subgate 9B will extend that same transaction when those optional
  relationships exist; 9A deletes only the profile row.

## Regression-first evidence

The new machine lifecycle and schema-11 tests were first run against the accepted
pre-9A implementation. The result was `5 failed, 7 passed`:

- all three machine tests received `404` because the authenticated routes did not
  exist;
- the fresh-schema assertion could not find `machineprofile`; and
- the schema-10 fixture remained at version 10 instead of reaching 11.

After the bounded implementation, one older schema-9-to-10 test followed the full
migration list and correctly observed version 11. Pinning that historical test to
the first ten migrations restored its intended boundary; it was a test-maintenance
issue, not a product failure.

The final focused run passed `12 passed in 7.19s`. It exercises the real migration,
SQLite constraints/indexes, authentication, validation, query pagination, name
conflicts, archive/restore, and permanent-delete service and HTTP paths. No unit
under test is replaced by a stub.

## Verification

The complete API suite passed before the implementation commit:

- `154 passed in 21.97s`

The complete repository `make verify` then passed at `eb3f0bf` under a sleep
inhibitor on the workstation:

- API: `154 passed in 22.30s`
- Web: the complete gate reused its verified Docker layer; an immediate explicit
  run passed TypeScript, all `21` tests, and the production build
- Bridge tests and native build passed under Go 1.26.6
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation passed; production Compose still rejects missing authentication
  secrets
- Container smoke passed for direct/same-origin API access, security headers, the
  512 MiB file policy, non-root API/web processes, and schema 11
- The immutable v5.1 release contract passed
- `git diff --check`, Python compile checks, and the staged credential-marker scan
  passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking. The workstation slept during an earlier focused rerun and
dropped SSH before producing a result; Wake-on-LAN plus the authorized sleep
inhibitor allowed the complete recorded runs above to finish. This was an
environment interruption, not a product failure.

## Migration and rollback evidence

A representative schema-10 fixture reaches schema 11 repeatedly with byte-for-byte
identical Asset, Artifact Revision, Project, membership, and relationship rows.
The new profile table is empty, its active-name index permits reuse only after
archive, and its category check rejects unknown values.

No filesystem migration or backfill exists. Application rollback must not start an
older binary against schema 11 because the migration ledger correctly rejects an
unknown newer version. Operational rollback remains restoration of the matched
schema-10 SQLite/storage pair; manual schema contraction or ledger editing is not
supported.

## Remaining boundary and next checkpoint

- Gate 9B owns neutral Artifact associations, exact prepared-machine references on
  current Assets and immutable Revisions, explicit matching, category enforcement,
  and transactional nullable cleanup.
- Gate 9C owns export format 2, retrieval, and the Settings/artifact interface.
- Gate 9D owns recovery contract 4, compatibility proof, and Gate 9 closeout.

The owner accepted this evidence on 2026-08-27. Gate 9B may proceed after its
additive migration-version checkpoint is resolved. Acceptance does not authorize
machine control, telemetry, device/network fields, export/UI/recovery work, push,
tag, release, deployment, or publication.
