# Gate 0 Baseline Record

**Gate status:** Accepted 2026-08-14

**Captured:** 2026-08-13; immutable baseline established 2026-08-14

**Branch:** `main`

**Starting anchor:** `80ddc5bb8849c0532ecf4de91010e450df28b940`

**Immutable source baseline:** `1231565642b8541a7ad36ba4ffdeb2da9527ef89`

**Verified closeout:** `63ade54cad7b1681cf2a33f62c0512d6d80bc45c`

## Qualification

The working tree was not clean when Gate 0 began. It contained the authorized
v5.1 sidebar, metadata, storage-template, preview, supporting-file, and prepared-
print work, plus the strategy documents. That work is the functional baseline and
was not reset, stashed, or overwritten.

The starting anchor alone therefore does not reproduce the working application.
Commit `1231565642b8541a7ad36ba4ffdeb2da9527ef89` now preserves the v5.1 work and
Gate 0 foundation as the clean source baseline.

## Initial source changes

At capture time, modified source included the API asset, database, route, model,
mount, schema, settings, and ZIP modules; the source Compose manifest; the web
Dockerfile, HTML, styles, API/settings libraries, and main UI components; and the
root README. New source included asset-file/prepared-print API modules, Nginx
runtime configuration, and the strategy documentation.

The exact pre-Gate-0 source delta remains recoverable through Git because Gate 0
does not reset or clean the working tree.

## Repository ownership finding

The initial index tracked 8,311 generated or runtime paths under:

- `makervault/api/__pycache__/`
- `makervault/api/app.db`
- `makervault/web/node_modules/`
- `makervault/web/dist/`
- `makervault/slicer-bridge/slicer-bridge.exe`

Gate 0 removed those paths from Git tracking while preserving every local file on
disk. Root ignore policy now treats source, dependency manifests, lockfiles, and
build definitions as authority. Built frontend files and bridge binaries belong
to CI/release artifacts.

## Local verification environment

| Tool | Observed state |
|---|---|
| Python | 3.12.3 installed; project API packages absent on host |
| Node | 20.20.2 |
| npm | 10.8.2 |
| Go | Not installed on host |
| Docker | 29.5.3 |
| Docker Compose | 5.1.4 |
| Git | 2.43.0 |

Containerized verification is therefore the reproducible local path for API and
bridge work. The web can also be verified through its Node test image.

## Initial migration evidence

- Fresh sanitized database: migrated to schema version 3.
- Programmatic pre-v5.1 fixture: migrated twice idempotently to version 3.
- Deliberately failed migration: not recorded as applied.
- Recorded version/name mismatch: startup stopped.
- Read-only-mounted copy of the existing local `api/app.db`: migrated to version 3
  in `/tmp`; the source database was not modified.
- API and migration suite: 8 tests passed under Python 3.11, including fresh,
  legacy, idempotency, failure, name-mismatch, newer-schema, dependency-lock, and
  authenticated route smoke coverage.

This record is updated, rather than replaced, when Gate 0 reaches evidence review.

## Immutable baseline verification

The complete `make verify` target passed against
`1231565642b8541a7ad36ba4ffdeb2da9527ef89` after it was committed. The working
tree was clean after verification, no smoke-test containers remained, and
`git ls-files -ci --exclude-standard` reported zero tracked ignored paths.

This hash is the Gate 0 source anchor even though evidence-only documentation was
committed afterward. GitHub Actions run 31802094344 passed all four jobs against
closeout commit `63ade54cad7b1681cf2a33f62c0512d6d80bc45c`, satisfying the final
Gate 0 exit item.
