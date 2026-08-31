# Gate 10 Owner Checkpoint

**Status:** Awaiting owner decision

**Prepared:** 2026-08-31

Gate 10 introduces a durable public archive contract and a storage seam that later
providers may depend on. These choices must be accepted before implementation.

## Recommended decision package

1. **Keep two different recovery products**
   - Format-1 server backup remains the stopped, exact operator rollback containing
     raw SQLite, managed storage, and sensitive `.env` configuration.
   - `.mvault` v1 becomes the documented, logical, secret-free whole-vault archive
     for independent verification and clean-instance restoration.
   - Neither contract is renamed or silently converted into the other.

2. **Use a streaming standard container**
   - `.mvault` v1 is a gzip-compressed POSIX PAX tar.
   - A small header is first; canonical JSONL catalogs and content stream in bounded
     order; the manifest and SHA-256 inventory close the archive.
   - Stable IDs determine archive paths. User-controlled filenames remain metadata.
   - An independent standard-library verifier owns safe-path, regular-file-only,
     duplicate, count, size, checksum, reference, required-feature, and version
     validation.

3. **Define portable truth explicitly**
   - Include active and Trash metadata; every managed Revision and attachment;
     hidden prepared payloads without making them ordinary files; Projects,
     relationships, Machines, references, and a small settings allowlist.
   - Label thumbnails derived and optional.
   - Exclude secrets, sessions, credentials, host activation/mount configuration,
     operational job histories, purge journals/quarantine, and temporary files.

4. **Handle external no-copy content honestly**
   - Default to reference-only with explicit source path, size, digest/state, and an
     archive summary of missing bytes.
   - Do not fail an otherwise valid export solely because an external source is
     offline.
   - A later explicit include-external option may copy available bytes into the
     archive; clean restore then makes those bytes managed and retains original
     source provenance.

5. **Restore only into an empty instance in v1**
   - No merge, overwrite, ID remap, or conflict-resolution mode enters Gate 10.
   - Import stages a new database and content root, validates the entire logical
     graph and all bytes, then publishes storage first and SQLite last.
   - Stable IDs, timestamps, Revision history, Trash, Project relationships, and
     Machine snapshots are preserved. Provider-specific managed paths may be safely
     reassigned.

6. **Make export/import operationally explicit**
   - The first supported workflow is a source-owned CLI with API/web stopped or in
     proven maintenance mode. It reports progress and never relies on a browser
     connection surviving a large export.
   - UI orchestration follows only after durable job/cancellation behavior is proven.
   - Export is read-only; import requires an empty target and a pre-publish rollback
     boundary.

7. **Keep encryption keys with the user**
   - Core `.mvault` v1 is unencrypted, mode-restricted, and contains no deployment
     secrets, but it remains sensitive.
   - Document wrapping the complete archive in the standard streaming `age` v1
     envelope. MakersVault does not invent cryptography, escrow a key, or store the
     only recovery identity.
   - Initial import accepts a decrypted `.mvault`; decryption failure occurs before
     staging/publish.

8. **Do not ship S3 in Gate 10**
   - Gate 10 defines a capability-explicit content-store contract and moves current
     behavior behind a filesystem adapter with conformance tests.
   - The contract separates authoritative immutable content, derived/cache data,
     staging/materialization, capacity, and reversible deletion semantics.
   - An S3-compatible provider requires a later owner checkpoint after multipart
     checksum/abort, conditional publish, read-after-write, pagination, versioned
     deletion/quarantine, cache/materialization, quota, credential, and compatible-
     provider tests. No real bucket or credentials enter Gate 10.

9. **Compatibility promise**
   - Unknown major versions or required features fail closed.
   - V1 semantics and golden fixtures freeze when released.
   - A released reader remains available for v1 for at least two stable releases
     after a successor, with a source-owned verifier/migrator.
   - `.mvault` never becomes a prerequisite for retrieving original files without a
     paid service.

## Why this package

It gives users a provider-neutral archive without embedding deployment secrets or
raw schema internals, makes restore safe before adding merge complexity, and allows
the existing filesystem implementation to prove the exact behavior a future object
store must replace. Deferring S3 prevents local atomic-rename, capacity, quarantine,
and direct-open assumptions from being papered over by an incomplete adapter.

## What approval authorizes

Approval accepts ADRs 0014–0017 and authorizes subgate 10A only: the normative
format, malicious/golden fixtures, independent verifier, and focused evidence. It
does not authorize export/import mutation yet, connection to object storage, S3
credentials, built-in key custody, merge restore, publication, deployment, or push.

## Material alternatives

- Make `.mvault` a raw database/storage backup rather than a logical format.
- Use ZIP64 instead of streaming PAX tar.
- Include `.env` and deployment credentials.
- Make external-byte copying automatic.
- Support merge/import into populated vaults in v1.
- Add built-in passphrase/key storage.
- Ship an S3-compatible provider in Gate 10.

Any alternative changes security, compatibility, scale, or recovery behavior and
must amend the ADRs before 10A implementation.
