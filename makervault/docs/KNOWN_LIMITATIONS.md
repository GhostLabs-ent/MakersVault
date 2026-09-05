# MakersVault Known Limitations — Current Development

These describe the current local roadmap build through Gate 11E. The frozen Gate 5
candidate at `f6ff55b` has the narrower [v5.1 scope](V5.1_SCOPE.md); local feature
completion is not release qualification.

## Identity and access

- Administrators can create and manage persistent local accounts with three fixed
  shared-vault roles, temporary-password reset, and last-Administrator protection.
  Public registration, invitations/email reset, username rename, account deletion,
  custom roles, passwordless login, TOTP, recovery codes, OIDC/SSO, API keys,
  private models, and per-model ACLs remain unavailable. Password-plus-passkey MFA
  is optional by default and requires one stable HTTPS RP/origin configuration. The
  environment credential is one-time bootstrap input, not an online password-change
  or recovery mechanism.
- Required passkey policy is deliberately staged. Every enabled targeted account
  must enroll first; Require Everyone must be lowered to Optional while a new enabled
  account is onboarded. Live Administrator MFA reset applies only to another
  non-required account, revokes its sessions, and does not change its password.
- Browser authentication uses revocable HttpOnly cookies and no tokenized file URLs.
  Production requires HTTPS; non-Secure cookies exist only in explicit development
  and test modes.
- Raw restore and stopped-instance Administrator recovery revoke every browser
  session; raw restore also consumes pending passkey ceremonies. There is no
  online/email/code recovery: emergency recovery requires a stopped instance, an
  exact verified pre-change backup, and an existing account.
- Durable audit is mandatory and Administrator-readable, but this slice has no
  audit deletion or retention setting. Events remain in SQLite and raw backups
  indefinitely; portable `.mvault` archives deliberately exclude them.
- Login/passkey throttling is bounded and process-local for the supported single API
  process.

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

- Ordinary deletion moves Artifacts to recoverable Trash; permanent deletion remains
  an explicit Administrator action and historical revisions cannot be erased one by
  one.
- “Select every server match” is deferred; bulk actions operate on explicitly loaded
  and selected IDs.
- Artifact history is linear and immutable: restoring an old revision creates a new
  current revision rather than rewriting history. Project relationships use the
  bounded accepted vocabulary and same-active-Project rules, not an arbitrary graph.
- SHA-256 matches are suggestions and integrity evidence; MakersVault never silently
  merges or deletes duplicate content.
- Model-name uniqueness is folder-scoped. External no-copy files cannot be renamed
  because MakersVault does not own their bytes.

## Mounted and imported content

- Mounted scanning is deliberate/restartable, not a continuous NAS watcher. It has
  no live per-file event stream or sophisticated exclusion language.
- Index-in-place bytes are outside MakersVault backups. Restore/remount them at the
  same container-visible paths; absent sources remain unavailable without blocking
  managed files.
- Index-in-place content can be hashed and report available, missing, or changed
  state, but MakersVault does not repair, overwrite, or relocate the external source.
- Remote import supports public HTTP(S) destinations only. Private-network URLs,
  outbound proxy routing, and arbitrary credential forwarding are unsupported.

## Backup and deployment

- The raw recovery archive is an operator backup for the canonical Compose layout;
  portable `.mvault` v1 is a separate secret-free logical export/clean-import format,
  not an in-place disaster-recovery replacement.
- Archives contain `.env` secrets and are not encrypted. Mode `600`, off-host access
  controls, and encryption-at-rest are operator responsibilities.
- SHA-256 inventories detect corruption but are not signatures. Published release
  artifacts use separate GitHub/Sigstore attestations.
- Server backup includes keyed session rows and public passkey state but excludes the
  browser's cookie value, preferences, and workstation bridge configuration/cache.
  Restore revokes copied sessions and consumes pending ceremonies before exposure.
- Direct public exposure of the API or web port is unsupported. MakersVault does not
  provision TLS certificates or emit HSTS for mixed LAN/proxy deployments.

## Platform scope

- Release bridge binaries target Linux, Windows, and macOS on amd64/arm64, but actual
  slicer/engraver discovery and protocol registration vary by installed application
  and operating-system policy.
- The bridge is workstation-local and must be upgraded with the server/web release.
- Automated desktop workflows cover Chromium, Firefox, and WebKit at a 1440 × 900
  viewport. v5.1 does not claim dedicated mobile/touch optimization or formal
  assistive-technology certification; the primary workshop experience remains a
  modern desktop-class browser.

See [Upgrade to v5.1](UPGRADE_V5.1.md) and
[Backup and Recovery](BACKUP_AND_RECOVERY.md) before deployment changes.
