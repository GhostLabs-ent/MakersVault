# ADR 0015: Staged clean-vault import

**Status:** Proposed

**Proposed:** 2026-08-31

## Context

A verified portable archive is not safe to apply directly to a live SQLite database
and storage tree. IDs, names, graph references, archive members, declared sizes, and
content are untrusted input. Merge semantics would add collisions, ID remapping,
history/provenance rewriting, and partial-failure behavior before clean restoration
is proven.

## Proposed decision

V1 imports only into an empty compatible MakersVault instance while API and web are
stopped or under a proven maintenance boundary. The importer:

1. creates an isolated staging root and current empty schema;
2. streams and verifies the archive under independent member/catalog limits;
3. validates every ID, uniqueness rule, relationship, current Revision, prepared
   pointer, Project/Machine reference, Trash state, content size, and SHA-256;
4. writes managed content through the approved `ContentStore` using provider-safe
   keys and builds a new staged SQLite database from logical catalogs;
5. runs current database/storage consistency audit against the staged pair;
6. publishes managed storage first and SQLite last only after full success; and
7. retains a clear stopped-state recovery path if publication begins but fails.

The importer preserves stable logical IDs, timestamps, history, Trash, and graph
meaning. It may assign new provider-specific managed paths. Default reference-only
external records remain unavailable until the operator remounts the same paths.
Explicitly included external snapshots restore as managed bytes while retaining
original-source provenance.

Operational jobs and purge journals are not recreated. Required background work is
re-derived safely after startup. Host mount activation and secrets are never applied
from the archive.

## Alternatives considered

- **Merge into populated vault:** useful eventually but requires conflict policies
  for every identity and relationship and cannot be Gate 10's safety baseline.
- **Replace a populated vault:** duplicates the existing destructive restore path;
  operators must create/verify a backup and use an explicitly empty target instead.
- **Import raw SQLite:** bypasses logical validation and provider-safe path mapping.
- **Publish rows while streaming:** leaves partial visible state after late checksum
  or graph failure.

## Consequences

Clean restore is less convenient than merge but gives deterministic identity and
failure behavior. It also yields the golden semantic comparison needed before any
future migration/merge mode. Operational rollback still uses a matched format-1
server backup; `.mvault` import is never an in-place upgrade mechanism.
