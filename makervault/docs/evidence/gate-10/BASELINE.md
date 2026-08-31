# Gate 10 Baseline and Entry Record

**Gate:** 10 — Deliver portable backup and storage abstraction

**Status:** Owner-approved; subgate 10A accepted, 10B not yet authorized

**Opened:** 2026-08-31

**Approved:** 2026-08-31

**Entry commit:** `e4b2dfb`

**Entry schema:** 12

**Entry contracts:** server-backup outer format 1 / recovery contract 4;
Artifact-history format 2; Project-export format 2

**Publication state:** Local only. Gate 10 does not authorize a push, tag, release,
deployment, external storage connection, archive import, or publication.

## Entry decision

Gate 9 is accepted with stable Artifact/Revision, Project, relationship, Machine,
Trash, export, and matched-recovery ownership. Gate 10 may design a portable
whole-vault format and a provider seam on that foundation. Implementation follows
the owner-approved archive compatibility, encryption/key ownership, clean-instance
restore, external-content handling, and S3 deferral contract. Only subgate 10A is
currently authorized.

## Verified current truth

| Area | Current behavior | Gate 10 consequence |
|---|---|---|
| Operator backup | `backup.sh` stops API/web and archives raw `app.db`, all managed storage, and `.env` into format-1 gzip tar | Keep this disaster-recovery contract; `.mvault` must be distinct and secret-free |
| Recovery verification | Standard-library verifier validates archive structure, checksums, SQLite/storage consistency, schema 12, Trash, Projects, relationships, Machines, and historical contracts | Reuse its safe-path/checksum disciplines, not its raw-database portability model |
| Artifact export | ZIP format 2 includes complete available Revision history, attachments, internal prepared payloads, Machine snapshots, and missing external states | Reuse its logical ownership inventory inside whole-vault catalogs |
| Project export | ZIP format 2 composes Artifact histories, membership, relationships, and Machine catalog | Avoid nesting thousands of ZIPs; flatten the same logical records once |
| Import | ZIP import creates selected new Artifacts; no Artifact-history, Project-export, or whole-vault importer exists | Gate 10 import must be a new staged clean-restore path, not reuse ordinary upload |
| Storage | `STORAGE` is a local `Path`; writes depend on parent creation, direct open, atomic rename, unlink, quarantine directories, `disk_usage`, and local temporary exports | Define capabilities honestly; an S3-shaped URL wrapper is insufficient |
| Direct coupling | Asset, attachment, revision, content identity, mount import, Trash, Artifact export, and Project export services import local storage directly | Introduce one local adapter incrementally with contract tests before remote drivers |
| Content identity | Revision primaries normally have SHA-256; attachments and derived files may require export-time hashing | Stream and hash every included payload without holding payload bytes in memory |
| External no-copy | Authoritative bytes remain outside managed storage and server backup; exact source paths/states remain metadata | Default `.mvault` to reference-only; any byte inclusion must be explicit and change restored ownership to managed |
| Trash/quarantine | Trashed Artifacts are recoverable; permanent purge uses a durable same-filesystem journal/quarantine | Logical export includes Trash but requires purge reconciliation and excludes deletion journals/quarantine |
| Operational records | Mount scans, hash jobs/items, and purge-operation rows are bounded process/recovery journals | Exclude them from portable logical state and restart such work cleanly after import |
| Settings/secrets | SQLite holds storage template, Trash retention, and mount-import choices; `.env`, browser state, bridge config, and credentials live elsewhere | Use a portable settings allowlist; exclude credentials and host/mount activation |

Primary evidence is `api/recovery.py`, `revision_export.py`, `project_export.py`,
`asset_service.py`, `asset_file_service.py`, `revision_workflow.py`,
`trash_service.py`, `resource_limits.py`, `settings_service.py`, the canonical backup
and restore scripts, and their recovery/export/security tests.

## Proposed `.mvault` v1 shape

`.mvault` is a logical archive, not a renamed server backup. The proposed physical
container is a gzip-compressed POSIX PAX tar so both writer and verifier can operate
sequentially with bounded memory.

```text
makersvault-20260831.mvault
+-- mvault/header.json                 # first member: format/version/features
+-- content/revisions/<revision-id>    # original managed primary bytes
+-- content/files/<asset-file-id>      # supporting or internal prepared bytes
+-- derived/thumbnails/<revision-id>   # optional, explicitly derived
+-- catalog/folders.jsonl
+-- catalog/artifacts.jsonl
+-- catalog/revisions.jsonl
+-- catalog/files.jsonl
+-- catalog/projects.jsonl
+-- catalog/project-memberships.jsonl
+-- catalog/project-relationships.jsonl
+-- catalog/machines.jsonl
+-- catalog/artifact-machines.jsonl
+-- catalog/settings.jsonl
+-- manifest.json                      # counts, roots, archive-level state
`-- checksums.sha256                   # every preceding member; final member
```

Catalogs are canonical newline-delimited JSON in deterministic record order. The
exporter keeps large inventories in a disk-backed work index and streams payloads;
it never builds the entire catalog or any model file in memory. Archive paths use
validated stable IDs rather than user filenames. Filenames and logical metadata
remain in catalogs.

## Essential, derived, external, and excluded state

### Essential and included

- Folders; active and trashed Artifacts; immutable Revisions; attachments; hidden
  prepared payloads/metadata, Projects, memberships, relationships, Machine
  profiles/associations/exact targets, and their stable IDs/timestamps;
- original managed content bytes with independently computed size and SHA-256; and
- an allowlist of portable settings: storage naming template and Trash retention.

### Derived and optional

- revision thumbnails may be included for fidelity/performance but remain labelled
  derived and may be absent or regenerated;
- content-job and scan results are not required to restore authoritative state.

### External

- default export records exact no-copy source path, digest/state, size, and ownership
  but does not include the source bytes;
- an explicit future `include external snapshots` option may stream currently
  available bytes after confirmation; import must restore those snapshots as
  managed content while retaining original-source provenance.

### Excluded

- `.env`, administrator password/signing secret, cookies/tokens/sessions, remote-site
  credentials, bridge configuration/cache, provider credentials, host paths that
  activate mounts, completed/interrupted job journals, purge journals/quarantine,
  and temporary exports.

The archive still contains private workshop content, notes, external source paths,
and provenance and must be protected accordingly.

## Proposed Gate 10 subgates

### 10A — Normative format and independent verifier

**Implementation:** verified and accepted on 2026-08-31; see
[`SUBGATE_10A_RESULTS.md`](SUBGATE_10A_RESULTS.md). Subgate 10B remains closed
until separately authorized.

- Accept ADR 0014.
- Publish the v1 container/catalog/schema specification and golden fixtures.
- Implement a dependency-free verifier that safely streams, validates paths/types,
  recomputes every checksum, enforces declared counts/features, and emits a stable
  report without starting MakersVault.
- Prove malicious member, duplicate, truncation, oversized declaration, checksum,
  catalog-reference, and future-feature failures before writing the exporter.

### 10B — Local content-store seam and streaming export

- Accept ADR 0016.
- Introduce a capability-explicit `ContentStore` contract and filesystem adapter;
  preserve all current local behavior through contract and service regressions.
- Build a stopped/maintenance-mode source-owned exporter that reads logical records
  in batches, streams content through the adapter, hashes it, and atomically publishes
  only a verified complete archive.
- Keep format-1 operator backup unchanged.

### 10C — Staged clean-instance restore

- Accept ADR 0015.
- Import only into an empty compatible instance in v1; no merge semantics.
- Stream into an isolated staging database/store, validate every record/reference and
  byte, then publish storage first and SQLite last with restart-safe cleanup.
- Preserve IDs/history/Trash/Project/Machine meaning while assigning provider-safe
  managed keys; leave external references explicitly unavailable until remounted.

### 10D — Operator workflow and encryption interoperability

- Accept ADR 0017.
- Provide documented CLI export/verify/import workflows with secure permissions,
  progress, cancellation cleanup, and explicit external/reference summaries.
- Document user-owned standard `age` envelope interoperability without storing keys
  or inventing cryptography. Core v1 import consumes a decrypted `.mvault`.
- Consider authenticated UI orchestration only after the offline workflow and job
  lifecycle are proven; do not hold a browser request open for a multi-hour export.

### 10E — Scale, compatibility, and closeout

- Prove bounded-memory export/verify/import on a representative large mixed vault,
  clean-instance semantic/byte equality, interruption recovery, old format-1 backup
  compatibility, and v1 golden-fixture stability.
- Document corruption, capacity, unsupported feature/version, missing external,
  wrong-key/envelope, and rollback behavior.
- Complete the storage-provider evaluation; no S3 driver ships without a separate
  owner-approved capability/conformance result.

## Compatibility and rollback contract

- `format_version: 1` has fixed required semantics. Readers reject unknown major
  versions and unknown required features; optional features are explicit.
- Once released, v1 import support remains for at least two stable releases after a
  successor is introduced, with a source-owned migration/verifier path.
- New writers emit only the current approved format and deterministic catalogs.
- Export is read-only and publishes atomically. Failed output is removed.
- Import never mutates the current vault in place: v1 refuses non-empty targets,
  stages and verifies first, and keeps services stopped after any publish-phase
  failure.
- Operational rollback remains the verified format-1 matched backup. `.mvault` is a
  portability/clean-restore contract, not a replacement for pre-upgrade snapshots.

## Entry risks to test

- Large metadata catalogs can become an unbounded-memory problem even when payload
  streaming is correct.
- Tar member declarations, JSONL lines, counts, and relationships are hostile input
  during import and require independent limits and schema validation.
- Current local rename/quarantine/capacity behavior cannot be assumed for object
  storage.
- Importing external snapshots as external references would create a restored vault
  that depends on a path that may not exist; ownership must become managed.
- Format evolution must not silently reinterpret old archives or permit unknown
  required behavior.
- Optional encryption is useless if MakersVault stores the only recovery key or if
  a wrong key can produce partially committed state.

## Owner checkpoint

The proposed package is [OWNER_CHECKPOINT.md](OWNER_CHECKPOINT.md), backed by ADRs
[0014](../../adr/0014-portable-mvault-format.md),
[0015](../../adr/0015-staged-clean-vault-import.md),
[0016](../../adr/0016-local-first-content-store.md), and
[0017](../../adr/0017-user-owned-archive-encryption.md). Approval authorizes 10A
only; each later subgate retains its evidence and acceptance stop.
