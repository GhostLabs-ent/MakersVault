# Gate 9C Export, Retrieval, and Interface Results

**Gate:** 9C — Portable machine references, retrieval, and descriptive interface

**Status:** Implementation verified; owner acceptance required

**Date:** 2026-08-28

**Entry commit:** `9826070`

**Implementation commit:** `0485184`

**Schema:** 12 (unchanged)

**Export contracts:** artifact-history 1 -> 2; Project 1 -> 2

**Recovery contract:** 3 (unchanged)

**Publication state:** Local only. Nothing was pushed, tagged, released, deployed,
connected to a device, or published.

## Delivered behavior

- Artifact-history format 2 retains every existing ZIP path and stored payload
  byte while adding the current and revision exact-target IDs, ordered neutral
  associations, deterministic bounded Machine snapshots, and explicit unresolved
  IDs for corrupt legacy references.
- Project format 2 embeds independently usable format-2 Artifact histories and
  adds a deterministic, de-duplicated top-level Machine catalog plus per-Artifact
  referenced and unresolved IDs. Trashed Project members retain their descriptive
  context in export.
- Authenticated Asset and tag-facet retrieval accepts a validated `machine_id`
  and the bounded `any`, `associated`, or `prepared` current-state scope. The
  filter composes with folder, Project, text, tag, ordering, and pagination
  behavior and uses a correlated `EXISTS` predicate so associations cannot create
  duplicate Artifacts.
- Archived profiles remain usable for retained-context retrieval. Supplied
  printer text and historical Revision targets are never treated as current
  Machine relationships.
- Settings now provides bounded Machine search/category/archive views and the
  accepted create, edit, archive, restore, and archive-first permanent-delete
  lifecycle. Permanent deletion requires the exact confirmation and reports
  association and prepared-reference cleanup counts.
- Artifact detail lazily loads Machine context only after the detail view opens.
  It displays supplied printer text separately, manages explicit neutral
  associations, and permits exact prepared targets only from active FDM/resin
  profiles when prepared context exists. Existing archived exact targets remain
  visible but cannot be newly selected.
- Library and Project retrieval expose the explicit `Any relationship`,
  `Associated`, and `Prepared for` scopes. Context mutations refresh the current
  retrieval while retaining the open detail view and current navigation scope.
- The accepted wording `Descriptive context only. No job was sent.` is shared by
  the API and interface. No matching suggestion, device field, address,
  credential, discovery, telemetry, queue, dispatch, or command behavior was
  added.

## Regression-first evidence

The new portability and retrieval regressions were run against the accepted
pre-9C implementation before the fix. Two API tests failed in `2.56s` for the
expected reasons: Artifact export still reported format 1, and Machine query
parameters were ignored and returned the unfiltered library. The new web
regression also failed at typecheck because the Machine-context contract module
did not exist. These were expected pre-implementation failures, not existing
suite failures.

After implementation, the first focused API run passed `5 passed in 3.46s`,
covering the three new portability/retrieval cases plus existing Artifact-history
and Project export cases. The finalized API suite passed `162 passed in 25.48s`.
The explicit web gate passed TypeScript, all `24` tests, and the production build.
Tests exercise real ZIP generation and bytes, SQLite state, HTTP routes,
pagination, archived and deliberately unresolved identities, Project Trash, and
the browser contract helpers; no unit under test is replaced by a stub.

## Portability and retrieval evidence

Regression fixtures prove active, archived, neutral-only, current-target,
historical-target, trashed, and deliberately missing-profile states. Exported
Machine catalogs and associations have deterministic ordering, Project catalogs
de-duplicate stable IDs, repeated Project exports produce identical manifests and
entry sets, and primary/revision/prepared bytes remain exact at their established
paths.

Retrieval tests prove all three scopes, archived-profile lookup, Project scope,
folder/text/tag composition, matching tag facets, pagination, no duplicate result
from multiple associations, invalid-scope rejection, and absence of printer-text
inference. Retrieval reads only active Artifact current state; immutable historical
targets remain available through the existing bounded detail/export paths.

No schema migration, filesystem migration, import, profile merge, backfill,
source-text match, or stored-byte rewrite exists. Application rollback restores
format-1 export and removes the new browser surfaces; already-downloaded format-2
archives remain immutable external artifacts.

## Complete verification

The complete repository `make verify` passed for the source committed as
`0485184` under a workstation sleep inhibitor:

- API: `162 passed in 25.43s`
- Web: TypeScript, `24` tests, and the production build passed in the explicit
  immediately preceding web gate; the complete run reused that verified Docker
  layer
- Bridge tests and native build passed under Go 1.26.6
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation passed; production Compose still rejects missing authentication
  secrets
- Container smoke passed direct/same-origin access, security headers, the 512 MiB
  file policy, non-root API/web processes, and schema 12
- The immutable v5.1 release contract passed
- `git diff --check` and the staged credential-marker scan passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking. The unrelated untracked desktop architecture note remained
outside Gate 9 and was not modified or committed.

## Remaining boundary and owner checkpoint

- Gate 9D owns recovery contract 4, compatibility proof, complete Gate 9
  regression/recovery evidence, and closeout. It is not authorized yet.
- Server-backup outer format 1, schema 12, and recovery contract 3 remain current.
- Import, automatic/fuzzy matching, discovery, device/network fields, telemetry,
  queues, file transfer, slicing, job history, and machine commands remain
  excluded.

Recommendation: accept Gate 9C at `0485184` and authorize only Gate 9D recovery
and closeout work. Acceptance does not authorize push, tag, release, deployment,
device connection, import, machine control, or publication.
