# Gate 10C — staged clean-instance restore results

**Date:** 2026-08-31

**Status:** Accepted

**Accepted:** 2026-08-31

**Scope:** Offline `.mvault` v1 import into an absent or compatible empty schema-12
database/storage pair only

## Outcome

Gate 10C implements ADR 0015 as `api/mvault_import.py` and
`scripts/import-mvault.sh`. The importer makes a private archive copy, runs the
independent v1 verifier, reconstructs the current schema and managed store in
isolated destination-side staging, audits the complete pair, and publishes storage
first and SQLite last. It does not merge, replace a populated vault, start or stop
services, apply secrets or mounts, recreate operational jobs, connect to S3, or
handle encryption keys.

Local implementation commit:

- `dc9d566` — staged portable-vault restore, provider-safe re-keying, publication
  recovery, CLI wrapper, and regressions.

## Restore truth

The reader preserves portable stable IDs, timestamps, revision history, Artifact
current projection, Trash state, Folder hierarchy, prepared File/Machine context,
Projects, memberships, relationships, Artifact-machine associations, and the two
portable settings. Managed Revision, File, and derived-thumbnail bytes are streamed
through `LocalContentStore` and assigned SHA-256-derived keys that do not embed
portable IDs or user-controlled filenames.

External no-copy Revisions retain their recorded source path but restore with
`content_state=unavailable` and `content_reason=external_remount_required`; no host
mount is activated. Scan, content-hash, purge-operation, quarantine, session,
credential, and deployment records are absent by format contract and are not
invented during restore.

## Staging and publication safety

The importer requires explicit `--confirm-stopped-empty`, rejects busy/non-empty,
wrong-schema, overlapping, and symbolic-link targets, and does not expose staged
state to the application. Catalog and payload indexes live in disposable SQLite;
archive and content reads use bounded chunks and the independent verifier's member,
record, metadata-line, PAX, and expanded-byte ceilings.

Before publication, the importer proves SQLite integrity/foreign keys, graph
acyclicity, current Artifact/Revision projection equality, payload size/SHA-256,
complete inventory, and absence of storage orphans and operational rows. It records
a private fsynced publication journal, renames the staged storage root first, and
renames SQLite last. Caught failure or cancellation restores the original empty
pair. A later invocation validates journal identity and recovery paths before
rolling back a process interruption; hostile journal paths fail closed.

## Focused evidence

```text
docker build --target test -t makersvault-api-gate10c-test makervault/api
docker run --rm makersvault-api-gate10c-test python -m pytest -q \
  tests/test_content_store.py tests/test_mvault_verify.py \
  tests/test_mvault_export.py tests/test_mvault_import.py
56 passed
```

The restore suite proves clean absent and initialized-empty targets, portable
catalog equality after restore/re-export, exact managed bytes, provider-safe keys,
missing external truth, operational exclusion, storage-first observation, target
mode, non-empty rejection without mutation, invalid/limited archive rejection,
current-projection rejection, ordinary and keyboard-interrupt rollback, simulated
process-death recovery, CLI confirmation, overlap/symlink rejection, and hostile
journal-path containment.

## Full repository evidence

```text
make verify
API: 232 passed
Web: production build/verification passed
Slicer bridge: tests and build passed
Compose/security: canonical manifests and production-secret rejection passed
Container smoke: direct/same-origin API, headers, 512 MiB policy, non-root UIDs, schema 12 passed
Release contract: v5.1.0 verified
```

The full repository gate completed successfully on 2026-08-31 from the local
Gate 10C tree. It did not push, tag, publish, deploy, or contact an external storage
provider.

## Gate boundary and next decision

Gate 10C was accepted by the owner on 2026-08-31, freezing clean-instance-only
staged restore as the Gate 10D input. The owner separately authorized Gate 10D on
the same date. Merge/replacement or live import, S3, application key custody, push,
tag, release, deployment, and publication remain unauthorized.
