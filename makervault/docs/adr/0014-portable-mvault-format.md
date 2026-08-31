# ADR 0014: Portable `.mvault` format

**Status:** Accepted

**Proposed:** 2026-08-31

**Accepted:** 2026-08-31

## Context

The server backup is an exact stopped deployment snapshot containing raw SQLite,
managed paths, and `.env` secrets. Artifact and Project ZIP exports are logical and
portable but cover only selected records and have no importer. Renaming either one
to `.mvault` would preserve the wrong boundaries.

Whole-vault export must handle large bytes and catalogs without unbounded memory,
remain independently inspectable, represent missing external ownership honestly,
and evolve without silently changing old archives.

## Proposed decision

Define `.mvault` v1 as a gzip-compressed POSIX PAX tar with:

- first-member `mvault/header.json` containing format name, integer major version,
  required/optional features, creation metadata, and catalog declarations;
- stable-ID content entries for managed Revision primaries and AssetFiles;
- optional derived thumbnail entries clearly separated from authoritative content;
- canonical, deterministic JSONL catalogs for the complete logical graph;
- a small final manifest containing counts, byte totals, content classifications,
  and external availability summary; and
- final `checksums.sha256` covering every prior regular member, including the
  manifest.

Only regular files are permitted. Names are normalized POSIX paths with strict
prefixes; user filenames never form member paths. Payloads and catalogs stream.
Large working inventories use a disposable disk-backed index rather than process
memory.

### Included logical records

Folders, active/trashed Artifacts, all Revisions, AssetFiles and roles, Projects,
memberships, relationships, Machine profiles/associations/exact targets, stable
timestamps/IDs, and an allowlist of portable settings are included. Managed bytes
are rehashed during export. Prepared payloads retain an internal role.

Thumbnails are optional derived content. Operational scans, hash jobs/items, purge
journals/quarantine, temporary files, `.env`, credentials, sessions, cookies, and
workstation bridge state are excluded.

External no-copy records include their exact source path, size, digest/state, and
ownership but not bytes by default. Missing external bytes are a declared partial-
content condition, not archive corruption.

## Versioning and verification

Format v1 semantics freeze on release. Unknown major versions and unknown required
features fail closed. Optional features are declared and ignorable only where the
specification says they do not affect authoritative restore. Writers emit the
current approved version; readers keep v1 support for at least two stable releases
after a successor and retain a source-owned verifier/migration path.

A dependency-free verifier streams the archive, validates type/path/order/count and
resource declarations, computes checksums, validates canonical JSONL schemas and all
cross-record references, and produces a stable report without starting the app.

## Alternatives considered

- **Raw SQLite/storage archive:** exact for rollback but provider/schema coupled and
  carries deployment configuration risk.
- **Nested Artifact/Project ZIP exports:** re-encodes shared content and metadata,
  duplicates Machines, and scales poorly.
- **ZIP64:** broadly familiar but central-directory/member inventories and current
  implementation APIs encourage whole-entry lists; sequential PAX tar makes the
  bounded streaming contract explicit.
- **Custom binary container:** unnecessary and hostile to independent inspection.

## Consequences

The manifest is written near the end because it describes bytes already streamed;
import always stages before trust or publication. Ordinary tar tools can inspect the
container, but only the `.mvault` verifier establishes semantic validity. The raw
server-backup format remains supported separately.
