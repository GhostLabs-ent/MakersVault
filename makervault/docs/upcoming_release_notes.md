# MakersVault v5.1 — Draft Release Notes

> **Status:** In development. v5.1 has not been published yet. Gates 0–11 are
> owner-accepted, and Gate 11E-1d was accepted for closeout on 2026-09-05. Gate 12
> is deferred to the desktop version; Gate 13 is active with 13A in evidence review.
> This draft tracks later local development; the qualified Gate 5 candidate remains
> frozen at `f6ff55b`. Qualification of a later release revision remains gated.

MakersVault v5.1 is a confidence release focused on a faster library, clearer
organization, safer self-hosting, and model entries that carry useful workshop
context. It improves the existing product without turning MakersVault into a slicer,
printer controller, or multi-user cloud service.

## Highlights

### Faster, resilient model previews

- Library cards no longer render every full model on the main browser thread.
- Preview work runs through a bounded worker queue with file, geometry, archive,
  memory, concurrency, and time limits.
- Generated and embedded thumbnails are persisted so repeat visits primarily load
  static images instead of reparsing source models.
- Malformed or expensive files show a durable **Preview unavailable** or **Preview
  paused** state instead of freezing the library.
- Users can explicitly retry a preview or open an individual model under a larger,
  still-bounded detail budget.
- Automatic, on-demand, and disabled preview modes are available in Settings.
- LightBurn preview generation follows the same bounded and persistent workflow.
- No manual thumbnail-upload chore was added.

The frozen Gate 5 candidate's preview benchmark recorded zero navigation-blocking
long tasks and zero warm original-model requests. Gate 13 has not yet requalified
those timings on the later schema-17 build.

### Modern organization for larger libraries

- Nested folders, folder-path search, active-folder highlighting, and breadcrumbs
  make the current location clear.
- Empty parent folders link directly to their child folders.
- Incremental loading keeps large libraries usable without loading every model at
  once.
- Selecting models opens a visible toolbar with the selected count and actions for:
  - selecting loaded models;
  - clearing the selection;
  - moving models;
  - adding or removing tags without replacing unrelated tags;
  - downloading the selected models; and
  - conservative deletion guidance.
- Bulk work reports progress and preserves exact failed items for review after a
  partial result.
- Model-name conflicts within a folder return an understandable result and do not
  overwrite either model.

The frozen candidate's organization benchmark exercised 600 models and 104 nested
folders with zero measured interaction long tasks; this is historical Gate 5
evidence, not a new current-build measurement.

### Better model identity and context

- Models use human-readable names that are unique within their MakersVault folder.
- Renaming a managed model also renames its primary file while preserving the file
  extension.
- Creator, collection, tags, and notes are available as model metadata.
- Managed storage can use configurable folder/model/metadata path templates.
- Assembly PDFs, notes, and other supporting files stay grouped visibly with the
  model entry.
- Prepared 3MF or attached prepared-print payloads can show a summary such as:

  `Prepared for Bambu Lab P1S · PLA · 0.4 mm · 0.2 mm layer · 3h 12m`

- Prepared G-code remains hidden as implementation data behind that summary and can
  be handed to the configured slicer; it is not exposed as a normal browsable file.
- MakersVault does not slice files or send jobs to a printer.

### Observable mounted-library imports

- A mounted server library can be rescanned deliberately from **Settings → Imports**.
- The last scan records its trigger, copy/index mode, status, start and finish time,
  and imported, unchanged, and failed counts.
- Bounded relative-path failure details are visible in the web interface without
  reading container logs.
- Repeating a scan skips unchanged exact source paths instead of creating duplicate
  entries.
- One rejected file or unreadable directory does not abort later files.
- Interrupted scans are marked clearly and can be safely run again.
- Overlapping scans are prevented, failure history is bounded, and ordinary mounted
  file sets retain per-file safety limits without a hidden batch-size cap.

Before scanning, the interface explains the ownership choice:

- **Copy into MakersVault:** MakersVault owns a managed copy that remains usable if
  the mount disappears. The mounted source remains read-only and is never modified
  or deleted.
- **Index in place:** no primary bytes are copied. The mount remains authoritative
  and must stay available. Rename is disabled, and deleting the MakersVault entry
  does not delete the source file.

### Safer self-hosting and imports

- Production deployments fail closed when administrator credentials or the signing
  secret are absent, unsafe, reused, or still set to published defaults.
- Login and passkey abuse are throttled for the supported single API process.
- Security, host, CORS, and protected-file response headers are generated and tested.
- Remote imports validate redirects, DNS resolution, and the connected peer to
  prevent requests from escaping into private or otherwise blocked network targets.
- Direct uploads, remote imports, ZIP extraction, images, previews, mounted sources,
  temporary storage, and free-space reserve use explicit resource limits.
- ZIP traversal, extreme expansion, symlink escape, malformed image, and partial-file
  cleanup cases have regression tests.
- Supported remote access remains an operator-managed HTTPS reverse proxy or private
  VPN. Exposing the application ports directly to the public Internet is unsupported.

### Shared-vault accounts and passkey MFA

- Persistent local accounts use Argon2id passwords, revocable protected-cookie
  sessions, and fixed Administrator, Member, and Viewer permissions enforced by a
  deny-by-default route inventory.
- Administrators create accounts with temporary-password replacement, manage
  authority, and review mandatory secret-free security audit outcomes.
- Optional password-plus-passkey MFA uses origin-bound, UV-required WebAuthn
  ceremonies. No passwordless or username-less login is added.
- Users manage their own passkeys and are encouraged to keep two. Administrators may
  stage Require Administrators or Require Everyone only after targeted accounts
  enroll.
- Explicit live MFA reset applies to another eligible account, leaves its password
  unchanged, and revokes its browser sessions. Backup-first stopped-instance
  recovery remains the last-Administrator path.
- Passkeys require one stable HTTPS hostname/RP configuration. Invalidating that
  configuration while MFA is in use fails closed instead of bypassing the factor.

### Safer desktop handoff

- Slicer and engraving handoff uses a short-lived grant for one exact file rather
  than sharing the browser session token.
- Each workstation confirms the exact MakersVault origin locally.
- The bridge validates file role, extension, redirect behavior, size, and origin
  before launching the configured application.
- The final release gate will reverify the matching v5.1 bridge installers and
  recorded artifact provenance.

## Upgrade-impact summary

- The current development database schema is version 17; the frozen Gate 5
  candidate remains schema 5.
- Migrations are ordered, additive, idempotent, and fail closed on unknown or
  mismatched versions. Schemas 6–17 add content identity/history, Trash, Projects,
  Machines, persistent identity/sessions/audit, and passkey state without rewriting
  existing model bytes merely because migration runs.
- Production instances may need new deployment-specific authentication environment
  values before the v5.1 containers will start.
- API, web, and bridge components must be upgraded as a matched release.

Use the tested [upgrade procedure](UPGRADE_V5.1.md) and
[backup/recovery guide](BACKUP_AND_RECOVERY.md), not this draft summary, for operator
commands.

## Intentional limits and deferrals

- No manual thumbnail uploads.
- No visible G-code browser or ordinary prepared G-code download workflow.
- No slicing, printer control, telemetry, or print-farm scheduling.
- No public registration, custom roles, private libraries, or per-object ACLs.
- No passwordless login, TOTP, recovery codes, API keys, or OIDC/SSO.
- **Select every server match** remains deferred until a server-side bulk contract
  can avoid loading thousands of IDs into the browser.
- STEP/STP files remain storable and usable in supported handoff workflows, but
  automatic card-preview parsing is intentionally skipped by the v5.1 preview policy.
- Continuous NAS watching, live per-file scan events, and sophisticated mounted
  exclusions are future work.
- Duplicate matching remains advisory and never silently merges or deletes models;
  externally mounted changed-source behavior remains explicit and bounded.

## Verification completed so far

- Gates 0–11 and Gate 11E-1 have accepted source-owned evidence and local rollback
  points; the owner accepted 11E-1d closeout on 2026-09-05.
- Current API suite: 313 tests passing in bounded container partitions.
- Current web suite: 32 tests across 11 files, plus type checking and production build.
- Go bridge tests and executable build pass.
- Development, production, compatibility, benchmark, security, and smoke Compose
  configurations pass validation.
- Fresh container smoke passes with non-root processes and schema 17.
- Preview, 600-model organization, and mounted-scan browser workflows passed on the
  frozen Gate 5 candidate. Gate 13 found their JWT-based harnesses need updating
  before they can requalify the current cookie-session build.
- A Chromium virtual-authenticator drill passes passkey registration, current-strength
  confirmation, Administrator policy enablement, logout, and fresh
  password-plus-passkey login.

All v5.1 feature-development commits remain local until the coordinated rollout.

## What remains before later development can ship

Gate 11E-1 is accepted. Gate 12 sustainable optional services is deferred to the
desktop version; its free-core and non-lock-in commitments remain binding.

Gate 13A re-ran the complete current repository gate (313 API tests, 32 web tests,
builds, bridge, Compose/security, fresh schema-17 smoke and Chromium passkeys) and
the 1,200-Artifact portable round trip. All passed. Its
[audit results](evidence/gate-13/SUBGATE_13A_RESULTS.md) explicitly leave current
operator lifecycle, browser performance, fresh advisory and exact-image release
qualification open.

1. Complete Gate 13B–13D: current verification-harness repairs, joined upgrade/raw
   restore/portable-startup proof, browser/security/platform qualification, and owner
   acceptance of the end state and next roadmap.
2. Record Gate 12 as outstanding desktop follow-up in the final roadmap audit.
3. Explicit owner ship/no-ship approval before any push, tag, image publication, or
   release.

## Ideas after v5.1 — not committed release scope

The original idea notes are preserved here for later validation:

- A desktop application where it materially improves local file/application
  integration.
- Optional AI-assisted print knowledge, only after the data and verification model
  is designed:
  - record failed-print observations;
  - record settings associated with verified good prints;
  - train or evaluate models against user-controlled, auditable data; and
  - require evidence that recommendations are useful and safe before presenting them
    as product guidance.
- Provider-backed storage only after the accepted local-first capability contract
  can be preserved without application-owned lock-in.
- API keys and OIDC/SSO only through their own identity, audit, revocation, recovery,
  and threat-model checkpoints.

These ideas begin with product and data-boundary design; they are not promises for
v5.1 and do not grant MakersVault machine-control authority.
