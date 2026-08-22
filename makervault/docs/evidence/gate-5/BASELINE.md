# Gate 5 Baseline and Entry Record

**Gate:** 5 — Prove upgrade, recovery, and the v5.1 release

**Status:** In progress — release/recovery truth captured; no release artifact published

**Opened:** 2026-08-21

**Entry commit:** `48e9aeb`

**Publication state:** Local only; owner deferred pushes until the coordinated v5.1 rollout

## Entry truth

Gate 5 begins with required Gates 0–4A accepted and optional Gate 4B explicitly
deferred. The current candidate passes the source-owned API, web, bridge, Compose,
container, preview, organization, and mounted-scan checks, but it is not yet a
releasable upgrade.

The canonical production manifest preserves the v5.0 volume names and container
paths:

| State | Canonical production location | v5.0 compatibility |
|---|---|---|
| SQLite metadata | `makersvault_db` at `/app/data/app.db` | Same volume and path |
| Managed files | `makersvault_storage` at `/app/storage` | Same volume and path |
| Mounted no-copy source | Operator bind mount at `/imports` by convention | New explicit mount contract; source remains external |
| Deployment configuration | Operator-owned `.env` beside the Compose manifest | Existing values require security migration |

Local source development has one path migration: the v5.0 database at
`makervault/api/app.db` moved to `makervault/data/db/app.db`; managed development
storage remains under `makervault/data/storage`. A safe development upgrade must
copy, never move or delete, the old database into the new location before startup.

## Data classification

### Essential MakersVault server data

The following must be recoverable as one versioned backup:

| Data | Why it is essential | Backup rule |
|---|---|---|
| Complete SQLite database directory | Holds folders, assets, names, metadata, source paths, supporting/prepared indexes, application settings, preview state, scan history, and migration ledger | Stop the application and capture the whole database volume/directory, including any SQLite journal sidecars |
| Managed primary files | MakersVault is the authoritative owner for direct uploads, remote imports, ZIP extraction, and mounted copy-mode imports | Capture the complete storage volume/directory |
| Supporting files | PDFs, notes, source material, and other user attachments live below `storage/bundles` | Capture with the storage volume; never reconstruct from database rows alone |
| Prepared payloads | Hidden G-code/3MF payloads may be the only copy of user-prepared work | Capture with supporting files even though the UI does not expose them as normal files |
| Deployment `.env` | Contains authentication, URL, host, limit, UID/GID, image, and mounted-import configuration needed to reproduce instance behavior | Treat as sensitive; include only in a permission-restricted backup and never print secrets in evidence/logs |
| Backup manifest | Records release/source revision, schema, Compose project/manifest, paths/volumes, file inventory, and checksums | Generate with every backup and verify before restore |

The database and storage snapshot are a matched set. Restoring only one can create
missing files, orphaned bytes, stale prepared-file pointers, or metadata/files from
different points in time. The supported procedure therefore stops both application
services before snapshot and restores both together.

### Derived or rebuildable data

| Data | Recovery behavior |
|---|---|
| `storage/thumbs` | Derived from embedded images, primary images, or bounded preview generation. It may be included by the whole-volume snapshot for speed, but its loss must not imply loss of the original model. |
| Preview outcome fields | Cached operational state inside the essential database. It may be reset/recomputed by a future repair tool, but the backup captures it with the database. |
| Mounted scan history | Operational evidence rather than source content. It is captured with the database and may be abandoned without altering mounted sources. |
| Web `dist`, Python bytecode, Node modules, bridge binaries, container layers | Rebuilt from the exact release source/artifacts; never treated as user data. |
| Temporary downloads, partial uploads, logs, benchmark corpora/results | Excluded from recovery; interrupted work must clean up or be safely repeatable. |

### External and client-local data

| Data | Ownership and limitation |
|---|---|
| Mounted index-in-place primaries | Externally owned and not present in a MakersVault server backup. Recovery preserves their database records and exact source paths, but usefulness requires the operator to restore/remount the external library at the same container-visible path. |
| Source-site originals | Not a backup dependency for files already copied into managed storage. Gate 4B source provenance is deferred. |
| Browser settings and source-site cookies | Per-browser local/session storage, outside the server backup. Cookies must be re-entered as needed. |
| Browser authentication token | Ephemeral session state; intentionally not restored. |
| Bridge configuration, paired origins, and local download cache | Workstation-local state outside the server backup. The bridge must be reinstalled or backed up separately according to its platform documentation. |

No backup or restore command may imply that externally owned no-copy bytes were
captured. The backup manifest and restore verification must report external source
records separately from managed files.

## Current release gaps

| Area | Current truth | Gate 5 requirement |
|---|---|---|
| Backup/restore tooling | No source-owned backup, manifest, integrity-check, restore, or rollback script exists | Add stopped matched-snapshot tooling with explicit targets, checksums, safe extraction, and refusal to overwrite non-empty restore targets without an intentional flag |
| Upgrade proof | Migration tests cover fresh and small programmatic legacy schemas | Add a representative pre-v5.1 library with nested folders, legacy paths/thumbnails, bundles, prepared metadata, renamed files, missing external files, and interrupted work |
| Clean recovery | Container smoke proves fresh startup only | Restore a real backup into empty volumes on a clean project and verify database/file consistency through supported APIs |
| Rollback | ADRs require a matched pre-upgrade snapshot but no executable drill exists | Upgrade a copied fixture, then restore its pre-upgrade database/storage pair and prove the older state |
| Consistency audit | No command reconciles database rows with managed and external files | Add a read-only verifier that reports schema, integrity, managed missing/orphaned files, bundle pointers, external availability, and checksums without mutating content |
| Release identity | Only historical tag `v5`; web package says `0.0.1`; manifests default to `latest` | Establish `v5.1.0` as the release identity and make artifacts/source revision traceable without breaking local development |
| Release automation | CI verifies source but does not build release artifacts, SBOMs, provenance, or checksums | Add a reproducible local/CI release command and a tag-gated publication workflow with least-privilege permissions |
| Operator documentation | No changelog, upgrade guide, backup guide, known-limitations document, security policy, contribution guide, or issue templates | Finish and cross-link every release-facing document before ship approval |
| Current README | Mixes historical instructions and pre-release material | Replace deployment/upgrade claims with the canonical manifests and tested Gate 5 procedure |

## Gate 5 execution contract

1. Feature scope is frozen. Only release-critical correctness, recovery, packaging,
   documentation, and evidence changes enter the v5.1 candidate.
2. Every destructive-looking recovery action resolves exact project, volume,
   directory, and archive targets first. Backup is non-destructive; restore defaults
   to empty targets and requires an explicit override for non-empty targets.
3. Canonical production named volumes are the primary supported drill. Development
   bind paths receive a documented compatibility procedure.
4. The application is stopped before snapshot or restore. SQLite metadata and
   managed storage are always backed up and restored as one set.
5. Archives use normalized relative paths, reject traversal/symlinks on restore, and
   carry a versioned manifest plus SHA-256 inventory. Verification occurs before any
   restore write.
6. Backup creation does not read or package mounted no-copy source bytes. It reports
   source records and availability separately.
7. Representative upgrade and rollback tests operate only on generated fixtures and
   disposable project-scoped volumes. Real local databases are read-only inputs at
   most and are never migrated in place for evidence.
8. Release images and bridge binaries are built from one immutable candidate revision.
   Checksums, SBOMs, and provenance name that revision; `latest` is not evidence.
9. No artifact is pushed, tagged, or published until the owner approves the final
   release candidate, known limitations, and P1 deferrals.

## Entry verification and evidence required

Gate 4 closeout established the entry harness at schema 5 with 75 API tests, 13 web
tests, bridge tests/build, Compose/security validation, fresh container smoke, and
the three deterministic browser/benchmark workflows passing.

Gate 5 must add executable evidence for:

- stopped backup creation and checksum verification;
- clean-project restore with original IDs, metadata, managed bytes, supporting files,
  prepared summaries, and mounted-source limitations intact;
- representative v5.0-to-v5.1 migration and API behavior;
- matched rollback to the pre-upgrade fixture;
- missing external no-copy content reported without blocking managed content;
- artifact rebuild reproducibility and source-revision identity; and
- the complete v5.1 P0 acceptance matrix.
