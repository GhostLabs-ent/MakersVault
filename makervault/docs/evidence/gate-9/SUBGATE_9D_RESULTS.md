# Gate 9D Recovery, Compatibility, and Closeout Results

**Gate:** 9D — Machine recovery integrity, compatibility, and Gate 9 closeout

**Status:** Implementation verified; owner acceptance required

**Date:** 2026-08-28

**Authorized entry commit:** `899fafa`

**Implementation commit:** `002a5e7`

**Schema:** 12 (unchanged)

**Backup contract:** `makersvault-backup` outer format 1 (unchanged); recovery
contract 3 -> 4

**Export contracts:** artifact-history format 2; Project format 2 (unchanged)

**Publication state:** Local only. Nothing was pushed, tagged, released, deployed,
connected to a device, imported, or published.

## Delivered behavior

- Newly created matched backups use recovery contract 4 while retaining outer
  format 1, the established archive members, checksums, SQLite/storage paths, and
  stored bytes.
- Database summaries count Machine profiles and associations only when their
  tables exist. The consistency report deterministically counts active and
  archived profiles, associations, current exact targets, and historical Revision
  exact targets.
- Schema 11 requires the Machine profile table. Schema 12 additionally requires
  the association table and both nullable prepared-target columns.
- The audit reports invalid categories, case-insensitive duplicate active names,
  orphan or duplicate associations, orphan current and historical exact targets,
  and current-Asset/current-Revision target disagreement under the exact approved
  stable keys. Every finding is critical and prevents backup creation.
- Archived profiles and historical targets remain valid retained context. The
  audit does not infer relationships from supplied printer text, require Machine
  activity, repair records, or delete data.
- No-marker, contract-2, and pre-9D contract-3 archives remain supported as
  historical report subsets, but their SQLite/storage contents must independently
  pass the current audit. Contract 4 is strict and unsupported future markers
  still fail closed.

## Regression-first evidence

The new Gate 9D regressions were run against the accepted pre-implementation
recovery code before the fix. The run produced `16 failed, 23 passed in 7.82s`.
Failures were limited to the expected missing recovery-contract-4 marker and the
old audit returning `status: ok` for approved Machine corruption cases. No
unrelated failure was attributed to Gate 9D.

After implementation, the focused recovery suite passed `39 passed in 7.73s`.
The broader affected API set covering recovery, migrations, Machine lifecycle and
relationships, portability, Revisions, Trash, Project lifecycle/export, Projects,
and Project relationships passed `98 passed in 23.99s`. The complete API suite
also passed independently as `176 passed in 28.92s`.

Tests operate on real schema-12 SQLite files and real backup archives. The
representative matched pair includes active and archived Machines, neutral
associations across active and trashed Artifacts, current and historical exact
targets, prepared payloads, multiple Revisions, Project context, and unchanged
stored bytes. Corruption tests modify the SQLite inputs and execute the real audit
and backup path; the unit under test is not replaced by a stub.

The compatibility regression creates a valid contract-4 archive, derives the
historical contract-3 report shape with valid manifests and checksums, proves that
shape verifies, then introduces Machine-target corruption while correctly
rebuilding the archive metadata. Verification refuses the corrupted historical
archive, proving compatibility does not bypass current integrity checks.

## Complete verification

The complete repository `make verify` passed for the source committed as
`002a5e7` under a workstation sleep inhibitor:

- API: all `176` tests passed
- Web: TypeScript, all `24` tests, and the production build passed through the
  previously verified cached layer
- Bridge tests and the native build passed under Go 1.26.6
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation passed; production Compose still rejects missing authentication
  secrets
- Container smoke passed direct/same-origin API access, security headers, the
  512 MiB file policy, non-root API/web processes, and schema 12
- The immutable v5.1 release contract passed
- `git diff --check` and the staged credential-marker scan passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking. The unrelated untracked desktop architecture note remained
outside Gate 9 and was not modified or committed.

## Rollback and closeout boundary

Gate 9D adds no schema or filesystem migration. Code rollback leaves Machine,
Artifact, Revision, Project, prepared metadata, payload, path, and byte state
unchanged. A recovery-contract-4 manifest requires a contract-4-aware verifier;
operational rollback remains restoration of a previously verified matched
SQLite/storage pair while services are stopped.

Recommendation: accept Gate 9D at implementation commit `002a5e7` and close Gate
9. Gate 10 must begin only through its own architecture/baseline checkpoint.
Acceptance does not authorize import, device discovery or control, push, tag,
release, deployment, or publication.
