# Gate 10B — local ContentStore and streaming export results

**Date:** 2026-08-31

**Status:** Implemented and verified; owner acceptance pending

**Scope:** Local storage seam and stopped/maintenance-mode export only

## Outcome

Gate 10B introduces a capability-explicit `ContentStore`, proves its local
filesystem adapter, migrates every production module that directly consumed the raw
storage root, and implements a source-owned streaming `.mvault` v1 exporter. It does
not import archives, mutate source records/content, connect to object storage,
handle encryption keys, or export a live vault.

Local implementation commits:

- `8db40a5` — local ContentStore seam and service migration;
- `87c8e5d` — streaming portable exporter and atomic publication.

## ContentStore proof

`api/content_store.py` separates the capabilities required by current ownership and
lifecycle behavior: streaming read, staged write, atomic publish,
create-if-absent, controlled local materialization, capacity reporting, bounded
enumeration, and reversible deletion. `LocalContentStore` implements all eight
without relocating, renaming, or rehashing existing bytes during initialization.

Production modules no longer import `STORAGE` directly. Local-only workflows ask
for `LOCAL_CONTENT_STORE` explicitly; the old `STORAGE` path remains as a
compatibility alias for tests and callers that genuinely require a local path. The
adapter rejects absolute/traversal/noncanonical keys and both leaf and intermediate
symlinks. Its conformance suite proves streamed reads, atomic create/overwrite,
create-if-absent conflict safety, bounded enumeration, capacity, materialization,
and reversible delete commit/rollback.

## Export safety and boundedness

`api/mvault_export.py` and `scripts/export-mvault.sh` require explicit
`--confirm-stopped` and an exclusive SQLite transaction. The source transaction is
query-only after the lock is acquired and the exporter requires schema 12 plus a
successful SQLite `quick_check`.

The exporter:

- reads every logical catalog with `fetchmany(batch_size)`;
- stores payload plans and computed identities in disposable SQLite, not RAM;
- streams managed File, Revision, and optional derived-thumbnail bytes through the
  adapter, with size/mtime checks before and after each read;
- recomputes managed digests and fails on a stored digest or size mismatch;
- writes catalog and checksum spools to a mode-700 destination-side work directory;
- represents missing external no-copy content as unavailable without including its
  bytes;
- closes and fsyncs a mode-600 temporary archive, runs the independent v1 verifier,
  then publishes with an atomic create-if-absent hard link; and
- removes temporary work on ordinary failure and `KeyboardInterrupt` without
  creating the requested output.

An output that already exists—or appears while a long export is running—is never
overwritten. The raw format-1 backup and recovery implementation was not changed.

## Focused evidence

```text
docker build --target test -t makersvault-api-gate10b-test makervault/api
docker run --rm makersvault-api-gate10b-test python -m pytest -q \
  tests/test_content_store.py tests/test_mvault_verify.py tests/test_mvault_export.py
43 passed
```

The mixed schema-12 exporter fixture covers managed and missing external Revisions,
prepared G-code, Machine targeting, a derived thumbnail, Folders/tags/collection,
Projects, and portable settings. It proves:

- byte/digest/metadata validity through the independent verifier;
- source SQLite remains byte-identical;
- missing content, changed digest, busy DB, unknown schema, and verifier rejection
  fail without publication;
- interruption removes partial work;
- existing and racing outputs remain untouched;
- 251 Folder records export correctly with a batch size of three; and
- a guarded 6 MiB payload rejects any read larger than 1 MiB.

## Full repository evidence

```text
make verify
API: 219 passed
Web: production build/verification passed
Slicer bridge: tests and build passed
Compose/security: canonical manifests and production-secret rejection passed
Container smoke: direct/same-origin API, headers, upload policy, non-root UIDs, schema 12 passed
Release contract: v5.1.0 verified
```

## Gate boundary and next decision

Gate 10B is ready for owner acceptance. Acceptance keeps `.mvault` v1 and the local
ContentStore contract as inputs to 10C; it does not authorize import automatically.
The next proposed subgate is clean-instance, isolated staged restore. S3,
encryption/key custody, merge restore, and live-vault export remain unopened.
