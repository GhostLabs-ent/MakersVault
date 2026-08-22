# Gate 6 Baseline and Entry Record

**Gate:** 6 — Establish revisions and recoverable deletion

**Status:** In progress — owner checkpoint accepted; subgate 6A authorized

**Opened:** 2026-08-22

**Entry commit:** `c004c60`

**Qualified v5.1 source:** `f6ff55b33fd64c7a5037e8eb642bed048c3e0e4f`

**Publication state:** Local only. The owner directed post-v5.1 work to continue
from the accepted candidate while all commits, tags, images, binaries, and releases
remain unpublished until coordinated rollout.

## Entry decision

Gate 5 is accepted locally against an immutable qualified candidate. Public release
publication remains deliberately deferred because MakersVault is a watched public
project. This does not change the candidate: Gate 6 work begins after it in local
history and cannot be included in a later v5.1 artifact.

Only the Gate 6 architecture and owner-decision subgate opens here. Schema and
behavior implementation begins after the metadata, revision, storage, and Trash
decisions are accepted.

## Verified current truth

The Gate 5 candidate and current source establish:

| Area | Current schema-5 behavior | Gate 6 consequence |
|---|---|---|
| Logical identity | One UUID `Asset` owns the user-facing name, organization, metadata, current primary fields, prepared summary, and preview state | Separate stable artifact identity from immutable primary-file revisions without changing existing IDs |
| Primary content | One filename/MIME/size and either managed `storage_path` or external `source_path`; no digest | Seed revision 1 without relocation, then add bounded SHA-256 truth |
| Content identity | Mounted scans skip exact recorded source paths; no byte identity, changed-source state, or duplicate suggestion exists | Content identity is Gate 6A, not an optional later enhancement |
| Supporting content | `AssetFile` is either visible `supporting` or internal `prepared`; a prepared pointer also lives on Asset | Define artifact-wide, revision-specific, and always revision-specific prepared ownership |
| Prepared UI | Useful extracted metadata is visible; payload is excluded from normal supporting-file browse/download | Preserve the hidden-payload invariant for every revision |
| Preview | One derived thumbnail filename and one preview state live per Asset | Revision-specific previews must not overwrite or mislabel historical state |
| Rename/storage | Mutable metadata can relocate managed primary bytes through the configured template | Historical revision paths must become immutable even when artifact metadata changes |
| Delete | Asset rows, related rows, managed bytes, and thumbnails are deleted immediately; filesystem cleanup is best effort outside the database transaction | Replace normal delete with metadata-only Trash, then make permanent deletion durable and reconcilable |
| No-copy delete | The external source is not deleted | Preserve external ownership for Trash, permanent deletion, hashing, and revision restore |
| Recovery | Backup format 1 captures the complete schema-5 database and managed storage as a matched set | Extend manifests and consistency checks to revisions and Trash before Gate 6 closes |
| Migration | Ordered immutable SQLite ledger is at version 5 and fails closed on unknown/name-mismatched migrations | Use additive expansion and representative schema-5 upgrade fixtures; no in-place rewrite |

Primary evidence is `api/models.py`, `api/migrations.py`, `api/asset_service.py`,
`api/asset_file_service.py`, `api/main.py`, `api/recovery.py`, the schema/recovery
tests, and [accepted Gate 5 evidence](../gate-5/RESULTS.md).

## Gate 6 subgates

### 6A — Content truth and revision expansion

- Accept ADR 0006 and the relevant ownership/storage parts of ADR 0007.
- Add the revision expansion and seed exactly one revision per existing Asset with
  no byte relocation.
- Calculate SHA-256 during new streaming ingestion.
- Add bounded, durable, resumable backfill and explicit managed/no-copy content
  states.
- Suggest exact duplicates without merge or deletion.

### 6B — Immutable revision workflows

- Replace the current primary through staged, verified revision creation.
- Expose current revision and history without introducing Projects or AssetGroup.
- Keep prepared payloads internal and attach their summary to the correct revision.
- Restore history by creating a new current revision from verified historical bytes.
- Export current-only and complete history with explicit external limitations.

### 6C — Trash and permanent deletion

- Accept ADR 0008.
- Change ordinary delete into recoverable, metadata-only Trash.
- Add conflict-aware restore and a dedicated Trash view.
- Add durable, quarantined permanent deletion with per-item results and external
  no-copy protection.

### 6D — Recovery, compatibility, and closeout

- Upgrade representative schema-5 libraries without byte relocation or ID changes.
- Extend matched backup manifests, consistency audit, clean restore, and rollback to
  all revisions and Trash.
- Prove interrupted revision creation, hashing, restore, and purge paths.
- Keep legacy Asset projections through at least one stable release.

## Migration and rollback contract

1. Take a verified matched schema-5 database/storage backup before migration.
2. Expand with additive revision, content-state, job, and Trash structures.
3. Seed one revision per existing Asset using current paths; do not move or hash
   bytes inside the schema transaction.
4. Verify cardinality, paths, attachments, prepared pointers, and preview state.
5. Enable bounded hash backfill and dual revision/legacy projections.
6. Do not contract schema-5 Asset columns during Gate 6.

An interrupted seed or backfill must be idempotent. Code rollback before legacy
contraction can use maintained schema-5 projections; operational rollback restores
the matched pre-Gate-6 database/storage backup.

## Security and privacy impact

- Hashes are local integrity metadata and are not remotely disclosed.
- Revision history and Trash increase retained sensitive content; backup/export and
  UI visibility must include them deliberately.
- User-controlled names never determine an unvalidated filesystem path.
- Permanent deletion is the only Gate 6 path that destroys managed bytes and remains
  behind explicit owner policy, exact target resolution, quarantine, and evidence.
- External no-copy paths remain references. MakersVault never deletes or rewrites
  their source bytes.

## Entry assumptions to test

- A one-file-at-a-time default hash worker is sufficient to keep representative
  libraries responsive.
- Retaining historical previews is affordable and provides more value than
  regenerating them after every history view.
- Artifact-wide supporting files with optional revision scope match real maker
  workflows without burdening the common upload path.
- A stable internal revision namespace is preferable to relocating history whenever
  a configurable organization field changes.

None of these assumptions can satisfy exit evidence without implementation tests or
an explicit accepted residual-risk record.

## Owner checkpoint

The proposed decision package is
[OWNER_CHECKPOINT.md](OWNER_CHECKPOINT.md), backed by ADRs
[0006](../../adr/0006-content-identity-and-duplicate-suggestions.md),
[0007](../../adr/0007-artifact-revision-ownership.md), and
[0008](../../adr/0008-trash-retention-and-permanent-deletion.md).

The owner accepted the checkpoint on 2026-08-22 with the capacity-aware Trash
retention amendment recorded in ADR 0008. Subgate 6A schema and service work is
authorized.
