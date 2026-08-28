# Gate 9D Recovery, Compatibility, and Closeout Recommendations

**Gate:** 9D — Machine recovery integrity, compatibility, and Gate 9 closeout

**Status:** Owner checkpoint; implementation not authorized

**Opened:** 2026-08-28

**Entry commit:** `d1fb8a7`

**Accepted Gate 9C implementation:** `0485184`

**Entry schema:** 12

**Entry backup contract:** `makersvault-backup` format 1; recovery contract 3

**Entry export contracts:** artifact-history format 2; Project format 2

**Publication state:** Local only. Nothing is authorized for implementation,
push, tag, release, deployment, device connection, import, or publication.

## Verified entry state

Gate 9C was accepted on 2026-08-28 after its complete repository gate passed for
`0485184`: 162 API tests, the verified web typecheck/24-test/production-build
layer, bridge tests/build, Compose/security validation, schema-12 container smoke,
and the immutable v5.1 release contract. Artifact-history and Project exports now
carry deterministic format-2 Machine references, and authenticated current-state
retrieval plus the descriptive Settings/detail interface are complete.

Schema 12 and recovery contract 3 remain unchanged. The unrelated untracked
desktop architecture note remains outside Gate 9 and is not modified.

## Current recovery gaps

- `database_summary` does not count `machineprofile` or `artifactmachine`, even
  when a schema-12 database contains them.
- The consistency audit does not select Machine profiles or associations and does
  not read `prepared_machine_id` from current Assets or Artifact Revisions.
- Schema-aware required-table checks stop at the schema-10 Project domain.
  Missing Machine tables, dangling association endpoints, dangling exact targets,
  and current-Asset/current-Revision target disagreement therefore are not named
  as critical inconsistencies.
- A contract-3/schema-12 backup created during Gates 9A–9C legitimately lacks
  Machine-domain report keys. Advancing the current report without an explicit
  historical-subset rule would reject those already-created backups.
- Artifact-history and Project format-2 ZIPs are retrieval exports, not matched
  server backups or restore inputs. They do not close the recovery gap.

## Recommended recovery contract

1. Keep schema 12, outer `makersvault-backup` format 1, archive members, component
   checksums, SQLite/storage paths, stored bytes, export formats, and stopped
   matched-pair operating procedure unchanged. Advance only the independent
   recovery-contract marker from 3 to 4 for newly created backups.
2. Count `machineprofile` and `artifactmachine` rows when their tables exist.
   Databases predating those tables retain their historical summary shape rather
   than acquiring invented zero-valued Machine fields.
3. Add deterministic Machine-domain report counts for active and archived
   profiles, neutral associations, current exact targets, and historical Revision
   exact targets. Validate the six stored categories and case-insensitive active
   name identity without treating archive state as damage.
4. For schema 11 require `machineprofile`; for schema 12 require
   `artifactmachine` and the two nullable prepared-target columns. Validate that
   each neutral association references an existing Artifact and Machine and is
   unique by `(asset_id, machine_id)`.
5. Validate that every non-null current or historical `prepared_machine_id`
   references an existing profile. For an Asset with a valid current Revision,
   its current exact target must equal that Revision's exact target. Archived
   profiles and historical targets remain valid retained context; the audit must
   not infer current state from supplied printer text or require a profile to be
   active.
6. Report every defect with deterministic sorted stable identifiers and make it
   critical: missing required Machine structures, invalid profile categories,
   duplicate active names, orphan association endpoints, duplicate associations,
   orphan current/historical exact targets, and current-mirror disagreement.
   Live audit, component audit, backup creation, backup verification, extraction,
   and restored-component verification must share this standard-library report
   and must never repair or delete data while inspecting it.
7. Preserve verification of valid older outer-format-1 archives. Explicitly prove
   the original no-marker shape, contract-2 schema-8/schema-10 archives, and
   contract-3 schema-12 archives created before 9D remain accepted as historical
   report subsets only when their actual contents independently pass the current
   audit. Contract 4 is strict; unsupported future markers fail closed.
8. Add a representative schema-12 matched-pair fixture with active and archived
   Machines, neutral associations, active and trashed Artifacts, current and
   historical exact targets, prepared payloads, multiple Revisions, Project
   membership, and stored bytes. Prove create, verify, extract, and exact restored
   verification without changing identity, metadata, paths, or bytes.
9. Add regressions before implementation by corrupting SQLite inputs through the
   real audit seam. Prove each required missing/orphan/duplicate/mismatch case is
   reported as inconsistent and prevents backup creation. Do not replace the
   audit or recovery function under test.
10. Re-run recovery, migration, Machine lifecycle/context, Artifact/Project
    format-2 export, Revision, prepared-print, Trash, Project ownership, legacy
    backup compatibility, web, bridge, Compose/security, schema-12 smoke, and the
    complete repository harness. Gate 9 closes only after the owner accepts the
    resulting evidence.

## Recommended report vocabulary

The exact JSON keys should be stable and additive:

- counts: `active_machine_count`, `archived_machine_count`,
  `machine_association_count`, `current_prepared_machine_count`, and
  `revision_prepared_machine_count`;
- required structure: `missing_machine_tables` and
  `missing_machine_reference_columns`;
- profile identity: `invalid_machine_category_ids` and
  `duplicate_active_machine_name_ids`;
- neutral associations: `orphan_machine_association_asset_keys`,
  `orphan_machine_association_machine_keys`, and
  `duplicate_machine_association_keys`;
- exact targets: `orphan_asset_prepared_machine_ids`,
  `orphan_revision_prepared_machine_ids`, and
  `prepared_machine_mirror_mismatch_asset_ids`.

Keys are present only when the Machine domain exists by schema version or table
presence, matching the established Project-domain compatibility pattern. Finding
lists use stable IDs or explicit composite keys and are sorted before serialization.

## Required evidence

- Recovery-contract-4 and Machine-integrity regressions fail against the accepted
  Gate 9C source for the expected missing marker/report/refusal behavior.
- A valid schema-12 Machine graph survives matched backup create, verify, extract,
  and restored-component verification with format 1 and recovery contract 4.
- Every approved Machine-domain corruption produces the exact deterministic key,
  `status: inconsistent`, and backup-creation refusal.
- No-marker, contract-2, and pre-9D contract-3 archives remain verifiable while
  future contracts fail closed and corrupt historical archives are refused.
- Gate 9A–9C lifecycle, context, export, retrieval, and interface behavior remains
  green with schema 12 and unchanged stored bytes.
- Final diff, secret/debug, release-contract, publication-boundary, and unrelated
  untracked-file review passes before evidence is presented.

## Rollback and closeout boundary

Gate 9D requires no schema or filesystem migration. Code rollback leaves schema-12
Machine, Artifact, Revision, Project, prepared metadata, payload, path, and byte
state unchanged. Newly created recovery-contract-4 manifests require the matching
verifier; operational rollback remains restoration of a previously verified
matched SQLite/storage pair with services stopped.

Gate 9 closes only after the owner accepts 9D evidence. Gate 10, Machine import,
device discovery/control, push, tag, release, deployment, and publication remain
unauthorized.

## Recommended owner decisions

1. Approve recovery contract 4 while keeping outer backup format 1 and schema 12.
2. Approve the deterministic Machine counts, reference checks, and exact report
   vocabulary above.
3. Approve historical-subset compatibility for no-marker, contract-2, and
   pre-9D contract-3 archives, with independent current-audit enforcement.
4. Approve a real schema-12 matched-pair fixture and corruption-input regressions.
5. Authorize only Gate 9D implementation and Gate 9 closeout evidence. Do not
   authorize import, device authority, push, tag, release, deployment, or
   publication.

Recommendation: approve all five decisions without amendment. This completes
Machine recovery truth using the established additive compatibility pattern and
does not change live data, archive ownership, or MakersVault's descriptive-only
boundary.
