# Changelog

Notable MakersVault changes are recorded here. The project uses `vMAJOR.MINOR.PATCH`
for versioned release artifacts beginning with v5.1.0.

## [5.1.0] - Unreleased

This working inventory includes later local roadmap work through Gate 11E. The
qualified Gate 5 candidate remains frozen at `f6ff55b` (schema 5); schema-17
development and passkey changes still require their own final release qualification
and owner ship decision.

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
- Ordered schema migrations through version 17 with mismatch/unknown-version refusal.
- Matched stopped backup, independent verification, clean restore, exact rollback,
  and a representative upgrade/recovery drill.
- Versioned API/web image identity, six bridge platform binaries, SPDX SBOMs,
  SHA-256 inventories, and tag-gated artifact attestations.
- Descriptive Machine profiles, explicit neutral Artifact associations, and exact
  revision-scoped prepared targets through additive schema 12, without device
  discovery, dispatch, telemetry, or control authority.
- Machine management, lazy Artifact context editing, and bounded current-state
  retrieval by associated or exact prepared Machine.
- Persistent local shared-vault accounts with fixed Administrator, Member, and Viewer
  roles; forced temporary-password replacement; recent-password confirmation;
  session administration; and last-enabled-Administrator protection.
- Durable, bounded, secret-free security audit with Administrator-only pagination.
- Interactive stopped-instance Administrator recovery backed by a mandatory exact
  pre-change backup, full session revocation, and startup audit markers.
- Optional password-plus-passkey MFA with origin-bound WebAuthn registration,
  password-first sign-in, passkey-aware five-minute identity confirmation, and
  self-service credential management.
- Administrator-selectable Optional, Require Administrators, and Require Everyone
  passkey policy with enrollment blockers, required-factor safety, explicit
  other-account MFA reset, and stopped-instance last-Administrator recovery.

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
- New matched backups use recovery contract 6 with deterministic schema-17 identity,
  session, audit, recovery, passkey-foundation, and Machine integrity reporting while
  compatibly re-auditing historical recovery contracts 2–5.
- Raw restore revokes copied browser sessions and pending passkey ceremonies before
  service exposure and records a durable recovery event at startup.
- High-impact operations by an MFA-enabled account require recent password and
  UV-required passkey proof bound to the same session, RP ID, and exact origin.

### Security

- Removed published production credential defaults and made API validation an
  independent fail-closed boundary.
- Bounded ZIP expansion/traversal, uploads, imports, previews, images, temp files,
  free-space reserve, mounted paths, redirect count, and bridge downloads.
- Added checksummed safe-extraction recovery archives and release SBOM/provenance.
- Added bounded digest-only WebAuthn ceremonies, generic login failures, replay and
  origin/RP checks, current-strength policy changes, and secret-free passkey audit.

### Known limitations

See [Known Limitations](makervault/docs/KNOWN_LIMITATIONS.md). Major deferrals include
passwordless login, TOTP, recovery codes, API keys/OIDC/SSO, private per-model ACLs,
automatic STEP card previews, hosted object storage, and server-wide “select every
match.”

## [5] - Historical beta

- Initial public self-hosted MakersVault beta with browser library management,
  folders/tags, model previews, link import, mounted import, and slicer bridge.

[5.1.0]: https://github.com/VincentCinque/MakersVault/compare/v5...v5.1.0
[5]: https://github.com/VincentCinque/MakersVault/releases/tag/v5
