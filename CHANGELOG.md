# Changelog

Notable MakersVault changes are recorded here. The project uses `vMAJOR.MINOR.PATCH`
for versioned release artifacts beginning with v5.1.0.

## [5.1.0] - Unreleased

### Added

- Human-readable model names unique within a folder, creator/collection metadata,
  configurable managed-storage templates, supporting files, and prepared-print
  summaries with hidden slicer payloads.
- Bounded persistent card previews with static thumbnail reuse, explicit policy
  fallback/retry states, detail-view budgets, and LightBurn coverage.
- Nested folder navigation, breadcrumbs, incremental library loading, and visible
  bulk move/tag/download workflows with partial-failure reporting.
- Observable restartable mounted-library scans with copy/index ownership language,
  bounded failure details, and no ordinary file-count ceiling.
- Fail-closed production authentication, login throttling, protected response/host
  policy, pinned remote-import connections, bounded ingest/archive/image resources,
  and short-lived workstation handoff grants.
- Ordered schema migrations through version 5 with mismatch/unknown-version refusal.
- Matched stopped backup, independent verification, clean restore, exact rollback,
  and a representative upgrade/recovery drill.
- Versioned API/web image identity, six bridge platform binaries, SPDX SBOMs,
  SHA-256 inventories, and tag-gated artifact attestations.
- Descriptive Machine profiles, explicit neutral Artifact associations, and exact
  revision-scoped prepared targets through additive schema 12, without device
  discovery, dispatch, telemetry, or control authority.
- Machine management, lazy Artifact context editing, and bounded current-state
  retrieval by associated or exact prepared Machine.

### Changed

- Production web delivery uses built static assets from unprivileged Nginx.
- Library cards avoid full interactive model parsing on the main browser thread.
- Renaming a managed model preserves its extension and updates its primary filename.
- Production Compose defaults to the exact `v5.1.0` API/web image pair rather than
  the moving `latest` tag.
- The bridge requires local origin confirmation and no longer receives the browser
  administrator token.
- Artifact-history and Project exports use format 2 with deterministic Machine
  snapshots, stable references, and explicit unresolved-identity reporting.
- New matched backups use recovery contract 4 with deterministic schema-12
  Machine integrity reporting while preserving verified historical backup shapes.

### Security

- Removed published production credential defaults and made API validation an
  independent fail-closed boundary.
- Bounded ZIP expansion/traversal, uploads, imports, previews, images, temp files,
  free-space reserve, mounted paths, redirect count, and bridge downloads.
- Added checksummed safe-extraction recovery archives and release SBOM/provenance.

### Known limitations

See [Known Limitations](makervault/docs/KNOWN_LIMITATIONS.md). Major deferrals include
multi-user identity, Trash/revisions/projects, source-content hashing/provenance,
automatic STEP card previews, and server-wide “select every match.”

## [5] - Historical beta

- Initial public self-hosted MakersVault beta with browser library management,
  folders/tags, model previews, link import, mounted import, and slicer bridge.

[5.1.0]: https://github.com/VincentCinque/MakersVault/compare/v5...v5.1.0
[5]: https://github.com/VincentCinque/MakersVault/releases/tag/v5
