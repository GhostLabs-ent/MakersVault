# Backup and Recovery

MakersVault v5.1 backs up the SQLite database and managed storage as one matched,
stopped snapshot. Never back up or restore only one side. A database can point to
files that are absent from a mismatched storage snapshot, while storage alone
cannot reconstruct names, folders, metadata, or relationships.

The supported production procedure uses `docker-compose.deploy.yml`, the exact
Compose project name used by the installation, and these canonical mounts:

| Data | Compose volume key | Container path |
|---|---|---|
| SQLite and migration records | `makersvault_db` | `/app/data` |
| Primary and historical revision files, supporting/prepared files, thumbnails, Trash, and pending purge quarantine | `makersvault_storage` | `/app/storage` |

The archive also contains the deployment `.env`. It therefore contains secrets
and must be protected like the vault itself. The tool creates it with mode `600`.

## Raw backup and portable export are different

The stopped format-1 server backup in this document remains the supported disaster
recovery and rollback mechanism. It contains exact SQLite, storage, deployment
configuration, and recovery journals.

Gates 10B–10C supply a secret-free logical `.mvault` v1 exporter, independent
verifier, and clean-instance importer. The exporter accepts schema 12, Gate 11A
schema 13, Gate 11B schema 14, Gate 11C schema 15, and Gate 11D-1 schema 16
sources; the importer deliberately reconstructs the frozen schema 12 content
contract. This portable workflow is not a replacement for the raw server backup:
it deliberately excludes deployment configuration, secrets, operational journals,
quarantine, and external no-copy bytes, and it does not support rollback,
replacement, or merge restore.

For schemas 13–16, this distinction includes authentication: raw format-1 backup
contains the SQLite `useraccount` password hash and, at schema 14, keyed browser
session records; schema 15 persists the fixed shared-vault role, and schema 16 adds
recent-password state plus reserved audit/recovery structures. It must be protected
accordingly. `.mvault` never contains users, roles, password hashes, session records,
audit/recovery state, or credentials. Starting an API against a clean `.mvault`
restore applies migrations 13–16 and bootstraps a new local administrator from that
installation's validated environment.

Schema 16 does not yet make the raw recovery tool detect a restore and revoke all
restored sessions automatically. Until Gate 11D-3 recovery is accepted,
keep a schema-16 raw restore isolated, sign in locally, confirm the password, use
revoke-all, and confirm the old browser session fails before exposing the service.
Identity/session-aware raw-backup audit remains an explicit Gate 11D-3 evidence
requirement.

From the repository root, against paths that are not being used by a running API:

```bash
./makervault/scripts/export-mvault.sh \
  --database /path/to/app.db \
  --storage /path/to/storage \
  --output /path/to/library.mvault \
  --makersvault-version 5.1.0 \
  --confirm-stopped

./makervault/scripts/verify-mvault.sh /path/to/library.mvault

./makervault/scripts/import-mvault.sh \
  --archive /path/to/library.mvault \
  --database /path/to/empty/app.db \
  --storage /path/to/empty/storage \
  --confirm-stopped-empty
```

The exporter refuses to overwrite an existing or racing output path, requires an
exclusive SQLite transaction, rehashes every managed Revision and File, records
missing no-copy external content honestly, independently verifies the temporary
archive, then publishes it atomically with mode `600`. Failure or interruption does
not create the requested output. Detailed v1 semantics are in
[`MVAULT_FORMAT_V1.md`](MVAULT_FORMAT_V1.md).
The complete offline procedure, progress/result contract, cancellation behavior,
and optional user-owned `age` envelope are documented in
[`PORTABLE_VAULT_WORKFLOW.md`](PORTABLE_VAULT_WORKFLOW.md).
Failure/rollback behavior and the remote-provider no-go decision are recorded in
[`PORTABLE_VAULT_FAILURE_MODES.md`](PORTABLE_VAULT_FAILURE_MODES.md) and
[`CONTENT_STORE_PROVIDER_EVALUATION.md`](CONTENT_STORE_PROVIDER_EVALUATION.md).

The importer requires API and web to remain stopped and accepts only an absent
target or a compatible schema-12 database plus an empty storage directory. It
copies and independently verifies the archive in private staging, reconstructs a
new database and content root, checks the logical graph and every managed byte,
then publishes storage first and SQLite last. Stable IDs, history, Trash, Projects,
Machines, prepared metadata, and portable settings are preserved. Managed content
receives provider-safe internal keys; external no-copy revisions retain their
recorded paths but are marked unavailable until the operator remounts them.

The importer never applies secrets or mount activation and never overwrites a
populated vault. A pre-publication failure leaves the target unchanged. A caught
failure or cancellation after publication starts rolls back the original empty
pair; a later invocation with the same targets detects and rolls back an
interrupted publication journal before doing new work. Keep services stopped and
investigate any import error. Use a verified raw format-1 backup—not `.mvault`
import—for replacement, upgrade rollback, or disaster recovery of an existing
installation.

## Create a production backup

First update or copy the v5.1 repository files so the recovery scripts are
available. This does not change a running older installation. From `makervault/`:

```bash
mkdir -p backups
chmod 700 backups
./scripts/backup.sh \
  --project-name makersvault \
  --output "backups/makersvault-$(date +%Y%m%d-%H%M%S).tar.gz" \
  --release v5.0 \
  --source-revision <deployed-tag-digest-or-revision>
```

Use the real Compose project if it is not `makersvault`. The script validates the
manifest and target, records which services are running, stops API and web, streams
both canonical volumes, restarts only the services that were running, creates the
archive atomically, and verifies it before reporting success.

Do not use `--overwrite` until the existing archive has been copied elsewhere or
is known to be disposable. Store at least one copy outside the Docker host.

## Verify without starting MakersVault

Verification needs Python 3 but does not start an application image:

```bash
./scripts/verify-backup.sh backups/makersvault-20260821-220000.tar.gz
```

The verifier rejects corrupt or unknown archive members, path traversal,
backslashes, symlinks, devices, duplicate members, checksum differences, an
unreadable SQLite database, an invalid backup version, missing managed content,
missing related files, broken revision/current/prepared ownership, changed managed
revision digests, malformed purge journals, and unknown quarantine content. It
reports:

- release, source revision, Compose project, manifest, mounts, and volume names;
- SQLite integrity, schema version, tables, and schema-aware row counts;
- SHA-256 for the manifest, component archives, and every stored file;
- active/trashed artifacts, every immutable revision, related/prepared ownership,
  external references, purge-operation/quarantine state, orphaned content, and
  derived-thumbnail state;
- whether externally owned no-copy bytes were included (always `false` in v5.1).

Checksums detect accidental corruption and incomplete copies. They are not a
signature from the project; release artifact signing is a separate concern.

The outer archive remains `makersvault-backup` format version 1. Current recovery
tools accept manifests produced by the earlier format-1 recovery contract and add a
separate recovery-contract version for schema-aware reports. This compatibility does
not weaken new backups: a new manifest must contain and exactly match the complete
current report.

## Schema 8 revisions and Trash

For post-v5.1 schema 8, a valid matched backup includes authoritative managed bytes
for both active and trashed artifacts. Every historical revision is checked, not
only the artifact's current revision. Artifact-wide and revision-owned supporting
files, hidden prepared payloads, prepared pointers, current-revision pointers, and
content identity are checked against SQLite ownership.

Thumbnails are derived content. Referenced thumbnails are inventoried when present,
and missing thumbnails are reported for regeneration without making authoritative
model content inconsistent.

An interrupted permanent-delete operation can leave files under
`.trash-quarantine/<operation-id>/`. The database journal identifies quarantine that
is still owned by a recoverable move or pending cleanup. The matched snapshot keeps
those bytes and the journal together so startup reconciliation can finish safely.
Unknown quarantine is an inconsistency: verification reports it and never deletes,
adopts, or guesses ownership.

Schema 7 upgrades add only the schema-8 Trash fields and purge-operation journal.
Existing artifacts begin active; current revisions, attachments, prepared metadata,
preview references, source ownership, IDs, and stored byte paths remain unchanged.

## Restore into empty production volumes

Prepare the v5.1 Compose manifest and a safe current `.env`, then verify the backup.
The restore command refuses non-empty database or storage volumes by default:

```bash
./scripts/restore.sh \
  --project-name makersvault-recovery \
  --archive /secure/path/makersvault-backup.tar.gz
```

The procedure verifies and extracts the archive before stopping services. It then
restores managed storage first and SQLite last, corrects ownership, snapshots the
live targets again, and proves every restored byte matches the archived inventory.
Only services that were running before the operation are restarted.

The archived `.env` is never applied automatically. To extract it for comparison,
choose a new path that does not exist:

```bash
./scripts/restore.sh \
  --project-name makersvault-recovery \
  --archive /secure/path/makersvault-backup.tar.gz \
  --config-output ./archived.env.review
```

The comparison file is created with mode `600`. Review image tags, host paths,
URLs, proxy origins, UID/GID values, and credentials before transferring any value
to the active `.env`. Delete the comparison file securely when finished.

## Replace an existing installation

`--replace` clears the exact project-scoped `/app/data` and `/app/storage` targets.
Before using it, create and verify a new backup of the installation being replaced:

```bash
./scripts/restore.sh \
  --project-name makersvault \
  --archive /secure/path/makersvault-backup.tar.gz \
  --replace
```

If the restore fails before volume mutation, previously running services are
restarted. If it fails after clearing or extraction begins, services remain stopped
and the script prints an operator-recovery warning. Preserve the failed state and
logs; do not repeatedly run `--replace` without understanding the failure.

Use `--leave-stopped` for release rollback so the restored older database is not
started by the newer image:

```bash
./scripts/restore.sh \
  --project-name makersvault \
  --archive /secure/path/pre-upgrade-backup.tar.gz \
  --replace \
  --leave-stopped
```

Select the older matched API and web image tags in `.env`, then start the stack.

## External no-copy content

Mounted index-in-place files are owned outside MakersVault and are deliberately
not copied into this backup. Their asset IDs, metadata, and exact container-visible
source paths remain in SQLite for every affected revision. After recovery, remount the external library at the
same `/imports`-relative paths. Until then, managed content continues to work and
the external file routes return unavailable.

Schema-14 server backup includes keyed server-side browser-session rows but never
the browser's HttpOnly cookie value. It excludes source-site cookies, browser
preferences, and workstation-local bridge configuration/cache. Follow the isolated
restore/revoke-all warning above and reinstall or restore the v5.1 bridge separately.

## Development-path compatibility

The current source-development manifest stores SQLite at
`makervault/data/db/app.db` and managed content at `makervault/data/storage`. An
older source checkout may instead have `makervault/api/app.db` and
`makervault/api/storage` because the whole API directory was mounted at `/app`.

Stop the development stack. Preserve a matched copy of the old `app.db` and
`storage` directory outside the repository, then copy—not move—the database to
`data/db/app.db` and the storage contents to `data/storage`. Keep the originals
until the current application has started, migration is complete, files open, and
a new v5.1 backup verifies. Never point production at these development bind paths.

## Tested recovery contract

The source-owned `scripts/gate5-recovery-drill.sh` operates only on generated
fixtures and unique disposable Compose projects. A clean committed revision must:

1. create and verify a stopped schema-4 backup;
2. upgrade nested folders, renamed content, old thumbnails, supporting/prepared
   files, prepared summaries, external records, and interrupted preview state;
3. validate IDs, metadata, and bytes through authenticated APIs;
4. restore into an independent empty project with external no-copy bytes absent;
5. restore the original project byte-for-byte to the pre-upgrade snapshot; and
6. remove its project-scoped containers, networks, and volumes.

`--allow-dirty` exists only for developing the drill. Its output is not release
evidence because the image cannot be tied to an immutable source revision.

Gate 6D adds source-owned API recovery fixtures that keep this Gate 5 contract and
also prove a schema-8 create/verify/extract/restore round trip containing active and
trashed multi-revision artifacts, artifact-wide and revision-owned files, a hidden
prepared payload, revision thumbnails, external no-copy content, and a pending
quarantine cleanup. Negative fixtures prove that missing or changed historical
bytes, broken cross-artifact pointers, malformed ownership, and unknown quarantine
cannot produce a valid new backup.

## Rollback boundary after schema 8

Rollback is restoration, not schema contraction. Stop API and web, verify the chosen
archive, and restore its SQLite database and managed storage as one matched pair.
Never combine a pre-Gate-6 database with post-Gate-6 storage or vice versa. To run an
older application image, restore the matched pre-upgrade backup with
`--leave-stopped`, select its matching API/web versions and configuration, then
start it. Do not edit schema migration records or manually remove revision/Trash
tables.
