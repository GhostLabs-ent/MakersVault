# Upgrade to MakersVault v5.1

This procedure upgrades a production Compose installation. Read
[Backup and Recovery](BACKUP_AND_RECOVERY.md) first. v5.1 migrations are additive,
but rollback is a matched snapshot restore—not a reverse database migration.

## Before the maintenance window

- Confirm the installation uses `docker-compose.deploy.yml` (the historical
  `docker-deploy.yml` remains a tested compatibility alias).
- Record the exact Compose project name and currently deployed API/web image tags.
- Confirm enough free disk space for the live database/storage plus a complete
  local backup and an off-host copy.
- Update the repository or copy the v5.1 scripts without starting new images.
- Read the v5.1 release notes and known limitations.
- Have the previous API/web tags available locally or in the registry.

## 1. Validate configuration

From `makervault/`, validate without creating containers:

```bash
docker compose \
  --project-name makersvault \
  --env-file .env \
  -f docker-compose.deploy.yml \
  config -q
```

The existing `.env` must provide a unique administrator password of at least 12
characters and a distinct random signing secret of at least 32 bytes. Keep the
current file; do not run `setup-env.sh` over an existing installation. See
[Secure Deployment](SECURE_DEPLOYMENT.md) for the complete security contract.

## 2. Create the rollback point

Create a stopped matched backup while the old images are still selected:

```bash
./scripts/backup.sh \
  --project-name makersvault \
  --output backups/pre-v5.1.tar.gz \
  --release <current-version> \
  --source-revision <current-tag-digest-or-revision>

./scripts/verify-backup.sh backups/pre-v5.1.tar.gz
```

Copy the verified archive off the Docker host. Do not continue if verification
fails or if the manifest reports missing managed/related files or prepared
pointers that you have not investigated.

## 3. Select the v5.1 artifacts

Use the exact release tags from the final v5.1 release—not `latest`—in `.env`:

```dotenv
API_IMAGE=shotgunwilly555/makersvault-api:v5.1.0
WEB_IMAGE=shotgunwilly555/makersvault-web:v5.1.0
```

Pull and start the matched pair:

```bash
docker compose \
  --project-name makersvault \
  --env-file .env \
  -f docker-compose.deploy.yml \
  pull

docker compose \
  --project-name makersvault \
  --env-file .env \
  -f docker-compose.deploy.yml \
  up -d
```

API startup applies each missing schema migration once. Unknown future migrations,
recorded-name mismatches, and failed migrations stop startup rather than guessing.

## 4. Verify before returning service

```bash
docker compose \
  --project-name makersvault \
  --env-file .env \
  -f docker-compose.deploy.yml \
  ps

docker compose \
  --project-name makersvault \
  --env-file .env \
  -f docker-compose.deploy.yml \
  logs --tail 100 api web
```

Then sign in and verify:

- nested folders and model counts;
- renamed models, creator/collection/tags/notes;
- representative STL, STEP, 3MF, image, and document downloads;
- supporting-document lists and prepared-print summary/handoff;
- preview fallback/retry on a complex model;
- mounted-import state and one available no-copy source;
- the v5.1 bridge from each workstation that uses local handoff.

Changing `AUTH_SECRET` intentionally invalidates old browser sessions. Sign in
again; do not interpret that as lost vault data.

Create a second verified backup after acceptance and label it as post-upgrade.

## Roll back

Stop user activity. Keep the failed/new installation intact until its logs are
captured. Restore only the pre-upgrade matched archive:

```bash
./scripts/restore.sh \
  --project-name makersvault \
  --archive backups/pre-v5.1.tar.gz \
  --replace \
  --leave-stopped
```

Set `API_IMAGE` and `WEB_IMAGE` back to the recorded previous tags, validate the
Compose configuration, and start the stack. Do not start an older image against a
database that the v5.1 image has migrated; the snapshot restore is the downgrade.

## What the upgrade does not restore

External index-in-place bytes, browser cookie values, import-site cookies, and
workstation bridge configuration are not server-backup content. Schema-14 raw
backup includes keyed server-side session records, but not the browser's cookie
value; follow the isolated restore and revoke-all procedure. Remount external
libraries at the same paths and reinstall the matching v5.1 bridge where needed.
See [Backup and Recovery](BACKUP_AND_RECOVERY.md) for details.
