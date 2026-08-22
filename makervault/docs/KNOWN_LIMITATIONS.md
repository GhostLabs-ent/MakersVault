# MakersVault v5.1 Known Limitations

These are intentional v5.1 boundaries, not hidden promises.

## Identity and access

- v5.1 is a single-administrator application. It has no user accounts, roles, MFA,
  OIDC/SSO, API keys, durable token revocation, or per-model permissions.
- Browser file/preview compatibility still uses protected tokenized requests. Use
  HTTPS remotely, do not share authenticated URLs, and close shared-browser sessions.
- Login throttling is bounded and process-local for the supported single API process.

## Files, previews, and workshop actions

- Users do not upload thumbnails. MakersVault reuses embedded/generated thumbnails
  and shows a stable fallback when bounded preview work is unsafe or unsuccessful.
- STEP/STP files are stored and handed off, but automatic card-preview parsing is
  skipped. Open the source in a capable CAD/slicer application.
- Complex/malformed 3MF and mesh files may remain paused or unavailable under the
  configured resource policy; an individual retry still has a finite budget.
- Prepared G-code is hidden behind the prepared summary/handoff contract. MakersVault
  does not slice, validate machine safety, send printer jobs, or control printers.
- Supporting files are grouped with a model, but v5.1 is not a general document or
  arbitrary relationship graph system.

## Organization and history

- Permanent multi-model deletion remains constrained until recoverable Trash exists.
- “Select every server match” is deferred; bulk actions operate on explicitly loaded
  and selected IDs.
- There are no artifact revisions, rollback history, Projects, relationships, or
  duplicate/content-identity engine in v5.1.
- Model-name uniqueness is folder-scoped. External no-copy files cannot be renamed
  because MakersVault does not own their bytes.

## Mounted and imported content

- Mounted scanning is deliberate/restartable, not a continuous NAS watcher. It has
  no live per-file event stream or sophisticated exclusion language.
- Index-in-place bytes are outside MakersVault backups. Restore/remount them at the
  same container-visible paths; absent sources remain unavailable without blocking
  managed files.
- v5.1 records exact source paths but does not hash them or detect changed content.
  Hashing, provenance, changed-source state, and duplicate suggestions are deferred.
- Remote import supports public HTTP(S) destinations only. Private-network URLs,
  outbound proxy routing, and arbitrary credential forwarding are unsupported.

## Backup and deployment

- The v5.1 recovery archive is an operator backup for the canonical Compose layout,
  not the future portable `.mvault` export/storage-provider format.
- Archives contain `.env` secrets and are not encrypted. Mode `600`, off-host access
  controls, and encryption-at-rest are operator responsibilities.
- SHA-256 inventories detect corruption but are not signatures. Published release
  artifacts use separate GitHub/Sigstore attestations.
- Server backup excludes browser sessions/preferences/cookies and workstation bridge
  configuration/cache.
- Direct public exposure of the API or web port is unsupported. MakersVault does not
  provision TLS certificates or emit HSTS for mixed LAN/proxy deployments.

## Platform scope

- Release bridge binaries target Linux, Windows, and macOS on amd64/arm64, but actual
  slicer/engraver discovery and protocol registration vary by installed application
  and operating-system policy.
- The bridge is workstation-local and must be upgraded with the server/web release.
- Mobile/touch and assistive-technology checks are part of the release matrix, but
  the primary workshop experience remains a modern desktop-class browser.

See [Upgrade to v5.1](UPGRADE_V5.1.md) and
[Backup and Recovery](BACKUP_AND_RECOVERY.md) before deployment changes.
