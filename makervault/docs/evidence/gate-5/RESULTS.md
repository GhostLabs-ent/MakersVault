# Gate 5 Release-Candidate Evidence

**Gate:** 5 — Prove upgrade, recovery, and the v5.1 release

**Status:** Ready for owner ship/no-ship checkpoint; nothing published

**Evidence date:** 2026-08-22

**Release identity:** `v5.1.0`, schema 5

**Publication state:** Local only. No tag, image, binary, release, or commit has been
pushed; publication remains deferred until the coordinated v5.1 rollout.

## Objective result

The v5.1 confidence-release promise now works as an upgrade and recovery path, not
only as a fresh demonstration. A representative schema-4 library upgrades to schema
5 without losing nested organization, renamed models, legacy thumbnails, managed
and supporting bytes, hidden prepared-print metadata, or unavailable external
records. The matched pre-upgrade database/storage set restores exactly, and a real
backup restores into a separate clean Compose project.

The source tree also produces matched versioned API/web images, six bridge binaries,
SPDX SBOMs, a checksummed release manifest, and digest-normalized reproducibility
evidence. Publication automation is tag-only, action-pinned, environment-gated, and
does not publish `latest`.

## Upgrade, backup, restore, and rollback proof

`scripts/gate5-recovery-drill.sh` creates only disposable project-scoped volumes and
generated fixture data. The completed drill proved this sequence:

1. Build a schema-4 fixture with nested folders, a renamed managed model, legacy
   thumbnail, supporting PDF, hidden prepared payload and Bambu summary, available
   and missing no-copy records, and interrupted preview state.
2. Stop the application and create/verify a matched pre-upgrade archive.
3. Upgrade to the current API, run ordered migration 5, and verify authenticated API
   behavior plus database/file reconciliation.
4. Create/verify a post-upgrade archive and restore it into independent empty
   database/storage volumes; external no-copy absence is reported without blocking
   managed content.
5. Restore the pre-upgrade archive with `--leave-stopped` and prove exact rollback.

The archive verifier checks outer SHA-256, a versioned manifest, every archived file,
SQLite `quick_check`, schema/counts, managed/supporting/prepared pointers, orphans,
thumbnail state, and post-restore byte identity. Extraction rejects absolute paths,
traversal, symlinks, hard links, devices, and unsafe replacement. Restore refuses a
non-empty destination without explicit `--replace`. Sensitive configuration is
archived with restrictive permissions but is never printed or automatically applied.

The documented operational commands are in [Backup and Recovery](../../BACKUP_AND_RECOVERY.md)
and [Upgrade to v5.1](../../UPGRADE_V5.1.md). Database and managed storage remain a
matched set; no-copy source bytes are intentionally outside the archive.

## Versioned release artifacts

`scripts/build-release.sh` requires a clean checkout by default and produces:

- matched local `makersvault-api:v5.1.0-<revision>` and
  `makersvault-web:v5.1.0-<revision>` images;
- Linux, Windows, and macOS bridge binaries for amd64 and arm64;
- SPDX JSON SBOMs for both images and all six binaries;
- `release-manifest.json` with version, source revision/tree, OCI labels, raw image
  IDs, and normalized config/filesystem/runtime digests; and
- `SHA256SUMS` covering the portable release files.

Two independent image rebuilds passed normalized config/filesystem comparison.
Bridge sample hashes were byte-identical across clean rebuilds. Raw image IDs can
differ because OCI layer tar packing order is not semantically stable, so the
reproducibility verifier compares normalized configuration and exported runtime
filesystem content while the release manifest still records the exact distributable
image IDs.

`scripts/release-candidate-smoke.sh` then runs the exact requested images through the
canonical production Compose manifest in unique volumes. It verifies OCI identity,
API version/revision, required authentication, same-origin Nginx proxying, upload and
download checksum, restart persistence, schema 5, and non-root API/web processes.

No artifact has been pushed. The ignored local candidate directory is operator
evidence only; the eventual tag workflow must rebuild from the approved immutable
revision and generate its own attestations.

## Performance and browser evidence

The deterministic preview corpus contains 20 small, medium, large, multipart,
multiplate, image-heavy, malformed, STL, OBJ, 3MF, and STEP fixtures totaling
66,037,534 bytes. The release-image run recorded:

| Measure | Cold | Warm |
|---|---:|---:|
| Cards ready | 361 ms | 135 ms |
| Preview pass settled | 5.16 s | 4.61 s |
| Original-file requests | 16 | 0 |
| Static thumbnail requests | 14 | 14 |
| Generated thumbnail uploads | 12 | 0 |
| Maximum active original requests | 1 | 0 |
| Long tasks | 0 | 0 |
| Peak JavaScript heap | 10.0 MB | 12.3 MB |

Fourteen previews persisted, three unsafe cases paused, and three malformed cases
failed visibly. Detail rendering completed in 269 ms with one original request and
no long task. The LightBurn probe made one cold source request and one thumbnail
upload, then zero warm source requests. Application console errors were empty.

The organization matrix ran the exact OCI-labeled candidate images with 600 assets,
104 folders, depth three, 20-card pagination, and the complete bulk/metadata/folder
workflow. Chromium is the deterministic timing-budget engine; Firefox and WebKit are
functional compatibility smokes in the Playwright runtime pinned to the lockfile.

| Engine | First cards | Load more | Exact search | Folder open | Functional result |
|---|---:|---:|---:|---:|---|
| Chromium 151 | 347 ms | 139 ms | 99 ms | 102 ms | Pass; timing budgets enforced |
| Firefox 153 | 1.24 s | 243 ms | 91 ms | 120 ms | Pass |
| WebKit 26.5 | 2.08 s | 211 ms | 53 ms | 110 ms | Pass |

Every engine proved pagination/selection scope, visible bulk toolbar, partial move
failure retention, tag preservation, ZIP download, conservative deletion,
supporting-document visibility, hidden prepared payloads, folder-path search,
child-folder empty state, and breadcrumb navigation. Headless software/container
timings are evidence, not end-user hardware guarantees.

The mounted-scan release-image workflow imported two regular files, isolated one
symlink failure, then skipped both unchanged files on repeat. Copy/index ownership
language and failure details were visible in the browser.

## P0 acceptance matrix

| v5.1 P0 promise | Status | Named evidence |
|---|---|---|
| Problematic models cannot freeze the library | Pass | Versioned preview corpus; one-active/eight-queued worker policy; cold/warm/detail/LightBurn run with zero long tasks |
| Repeat visits predominantly use static thumbnails | Pass | Fourteen warm thumbnails and zero warm original-file requests |
| Bulk actions are discoverable, scoped, and conservative | Pass | Three-engine 600-asset organization workflow; toolbar, selection clearing, partial failures, ZIP, and delete assertions |
| Folder location and navigation are explicit | Pass | Folder-path search, current path, breadcrumb ancestor navigation, and child-folder empty state in all three engines |
| Mounted scans are deliberate and observable | Pass | First/repeat scan counts, isolated failure detail, immutable copy/index ownership language |
| Production authentication cannot retain known defaults | Pass | Required Compose secrets, deployment-specific secret validation, authenticated exact-image smoke, Gate 1 regression suite |
| Upgrade and recovery preserve essential content | Pass | Representative schema-4 upgrade, clean-project restore, missing-external report, exact matched rollback |
| Release/repository hygiene is complete | Pass | Changelog, release notes, security/contribution policies, issue templates, upgrade/backup/limitations docs, release contract verifier |
| Artifacts identify and reproduce their source | Pass | OCI labels, release manifest, checksums, SPDX SBOMs, normalized rebuild comparison, exact-image smoke |

## Automated regression matrix

| Area | Result |
|---|---|
| API | 82 tests passed twice under Python 3.11, including migrations, recovery, bundles, prepared metadata, preview policy, resource/security boundaries, and mounted scans |
| Web | 13 tests across 5 files plus production type-check/build |
| Bridge | Protocol/security tests pass; six Linux/Windows/macOS amd64/arm64 binaries build and report the matched version/revision |
| Compose/security | Development, canonical production, aliases, benchmark overlays, required-secret rejection, and non-root container smoke pass |
| Release contract | Version alignment, digest-pinned bases/browser runtime, commit-pinned actions, tag-only/no-`latest` publication, and required files/scripts pass |
| Full repository | `make verify` passes; exact-image smoke and the three browser/import matrices run separately against versioned candidate images |

## Approved scope boundaries and P1 deferrals

Required Gate 4A is included. Optional Gate 4B remains deferred: content hashing,
bounded backfill, changed-source state, provenance/license search, and duplicate
suggestions are not v5.1 release requirements. Other P1 deferrals are dedicated
mobile/touch and assistive-technology certification, server-wide select-all, advanced
UI density polish, and real workstation launch testing on every bridge OS/CPU pair.

The owner checkpoint must review [Known Limitations](../../KNOWN_LIMITATIONS.md) and
these deferrals. There is no manual thumbnail upload, slicing, printer control,
visible G-code browser, multi-user identity, Trash/revisions, Projects, automatic
STEP preview, continuous NAS watching, or portable `.mvault` export in v5.1.

## Local commit record

Major Gate 5 commits include:

- `d358a2c` — Gate 5 release/recovery baseline
- `2db5ee6` through `3ed7077` — matched backup, restore, fixture upgrade, rollback,
  and recovery runbook
- `7632d00` through `af6488f` — release assembly, normalized provenance, and
  reproducibility proof
- `380f2ae` — exact release-image smoke
- `8aff259` — pagination-aware preview benchmark
- `b6da140` — exact release-image browser/import matrix mode
- `275b91a` — Chromium/Firefox/WebKit release browser matrix

All commits are local. Gate 5 closes only after the owner explicitly approves the
candidate, known limitations, and P1 deferrals with a ship decision.
