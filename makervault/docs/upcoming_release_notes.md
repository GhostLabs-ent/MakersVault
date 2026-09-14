# MakersVault v5.1 — Draft Release Notes

> **Status:** In development. v5.1 has not been published yet. Gates 0–11 are
> owner-accepted, and Gate 11E-1d was accepted for closeout on 2026-09-05. Gate 12
> is deferred to the desktop version; Gates 13A–13B are accepted and 13C is in progress.
> This draft tracks later local development; the qualified Gate 5 candidate remains
> frozen at `f6ff55b`. Qualification of a later release revision remains gated.

MakersVault v5.1 is a confidence release focused on a faster library, clearer
organization, safer self-hosting, and model entries that carry useful workshop
context. It improves the existing product without turning MakersVault into a slicer,
printer controller, or multi-user cloud service.

## Highlights

### Upload progress and approved Make Plate scope

- UP-1 adds byte-weighted transfer progress with saved/failed file counts and a
  separate server-finalizing state to the shared browser upload path. Folder,
  drag-and-drop and confirmed ZIP-selection batches use the same reporting.
  Existing limits, folder placement and Project membership are unchanged.
- Local verification passes **84 web tests** and Chromium/Firefox/WebKit upload
  workflow checks; see [UP-1 results](evidence/gate-13/UPLOAD_PROGRESS_RESULTS.md).
  “100% transferred” does not mean the server has saved the last file. Summaries
  are dismissible, and logout/session failure clears old-account progress/queues.
- The owner also approved [Make Plate and workstation preset import](MAKE_PLATE_RUNBOOK.md).
  These are **planned, not delivered**: STL-based planning, saved recipes and editable
  3MF slicer handoff have separate implementation/qualification gates. CNC/CAM
  integration is explicitly deferred to a later release. No printing/control or
  manual-thumbnail workflow is added.
- New macOS workstation preset discovery/import/refresh is also deferred from v5.1
  by [owner decision](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md). Existing Mac
  file opening is unchanged; planned browser-based Make Plate and Windows/Linux
  preset import remain in scope, not yet delivered or release-qualified.

### Bridge compatibility repairs (MP-0)

- Manual Windows/Linux installers now register the general `makersvault-open`
  protocol as well as both legacy schemes. macOS first-use pairing now selects
  `/usr/bin/open` for its local browser consent page; model files still use the
  explicitly selected adapter.
- 29 bridge tests pass with race detection; six platform/architecture builds and
  an isolated Linux manual-install check pass. Native Windows/macOS launch remains
  unqualified. See [MP-0 results](evidence/gate-13/MAKE_PLATE_MP0_RESULTS.md).
- Preset/recipe/import and recovery contracts are accepted, not delivered APIs.
  No printer discovery, slicing, printing or background profile sync is added yet.

### Bambu preset parsing foundation (MP-1a)

- Internal bounded reader core now projects inherited printer geometry and nozzle
  metadata into review candidates, filtering credential/script fields and reporting
  incomplete or unsupported inputs. It is **not enabled in the bridge UI/CLI yet**.
- 47 bridge/parser unit tests, a short fuzz run, vet and six-target cross-builds pass;
  see [results and limits](evidence/gate-13/MAKE_PLATE_MP1A_RESULTS.md). Workstation
  discovery, scoped import, persisted presets and actual Bambu version qualification
  remain separate pending work. Upload limits and existing workflows are unchanged.

### Local preset file-reader foundation (MP-1b-1)

- Internal Linux reader now limits access to explicitly selected local documents,
  rejecting symlinks, hard links, special files and nested mounts. It never returns
  a partial catalog after a read failure. This is **not enabled in the UI/CLI**.
- 68 bridge/parser/reader unit tests pass with race detection in an unprivileged
  container, including permissions and same-device bind-mount controls. Static
  checks, six-target builds and two short fuzz runs pass; see
  [evidence and limits](evidence/gate-13/MAKE_PLATE_MP1B1_RESULTS.md).
- The subsequent Windows/worker slice is described below. MP-1b remains open;
  no workstation was scanned and existing uploads/file-open behavior are unchanged.

### Windows preset reader and scan-worker foundation (MP-1b-2)

- Internal Windows NTFS reading and a single-use scan supervisor are implemented.
  The supervisor bounds input/output, cancels stalled work, suppresses diagnostics
  and prevents partial results. It is **not enabled in the production bridge**.
- 80 unit tests with race detection, six-target builds and four short fuzz runs pass
  on Linux; see [results and limits](evidence/gate-13/MAKE_PLATE_MP1B2_RESULTS.md).
  Windows native tests compile but have not run. Windows/Linux profile discovery,
  local consent/matched worker integration and native lifecycle checks remain open;
  new Mac-local preset import is separately deferred from v5.1.

### Native Mac worker verification

- [34 targeted tests now pass on an Intel Mac](evidence/gate-13/MAKE_PLATE_MAC_NATIVE_RESULTS.md)
  running macOS 15.7.9, including ordinary worker timeout/cancellation and safe
  refusal while macOS file reading is unimplemented. This is not yet macOS preset
  import or slicer-launch support; no app/toolchain installation was needed.

### Mac preset import — deferred from v5.1

- [Native synthetic reads and worker round trips now work](evidence/gate-13/MAKE_PLATE_MAC_READER_RESULTS.md)
  in an explicitly tagged experiment: 34 default and 42 ordinary experimental checks
  pass. Two additional counterexamples demonstrate unresolved file-opening safety
  gaps, so normal builds still refuse Mac preset reads. This is not delivered preset
  import or release qualification; existing Mac file-open behavior is unchanged.
- Following the MS-1 NO-GO assessment, the owner deferred new Mac-local preset
  discovery/import/refresh. The experiment remains disabled; no manual file/image
  upload workaround or broader removal of Mac support is introduced. Existing Mac
  real-app/signing checks still need qualification.

### Bambu manifest-index foundation (MP-1b-3)

- The inactive private worker now reads Bambu's manifest and retains only bundle
  version and machine identity/file pairs, without following URLs or referenced
  files. Explicit selection is exact and all-or-nothing; templates are not assumed
  to be selectable printers and bundle version is not installed-app detection.
- [90 unit tests/race, six-target builds and five fuzz smokes pass](evidence/gate-13/MAKE_PLATE_MP1B3_RESULTS.md).
  Root/account selection, actual profile binding/discovery, app-version observations,
  native Windows qualification and consented import remain open. No production
  scanning, new UI, upload restriction or change to the Mac-import deferral.

### Bambu location-inspection foundation (MP-1b-4)

- Known-location planning and bounded inspection of one explicitly chosen data
  folder/account now work internally. Child directories stay anchored beneath the
  chosen root; manifest/user indexes share a deadline and entry budget. No account,
  application version or selectable printer is guessed.
- [104 unit tests/race, six-target builds and six fuzz smokes pass](evidence/gate-13/MAKE_PLATE_MP1B4_RESULTS.md).
  Native Windows remains untested. Workstation profile binding, local selector UI,
  app-version observations and consented activation still remain; production
  scanning is disabled and the Mac-import deferral is unchanged.

### Lower-overhead folder listing (Gate 13C)

- Folder lists read plain database values instead of constructing tracked objects
  for every folder. Response fields, permissions and immediate updates are unchanged;
  no cache or folder/upload limit is added.
- All 354 API tests pass at `c42614e`. This is a bounded improvement, not a complete
  fix for intermittent stalls or API tail latency. Further tuning is deferred at
  the owner's request; see [results](evidence/gate-13/BOUNDED_PERFORMANCE_RESULTS.md).

### Lighter folder-tree action menus (Gate 13C)

- Folder action contents are created only when opened and removed when closed.
  Existing folder expansion, paths, actions and permissions remain unchanged;
  no new folder or upload limit is introduced.
- Native disclosure keys, Escape/focus, duplicate-name action ownership, folder
  refresh/deletion and Viewer restrictions have real-browser regression checks.
  WebKit's synthetic filesystem-drag limitation is explicitly recorded, not hidden.
- Full verification passes at `82cb2cc`: 351 API / 58 web tests and current HTTPS
  lifecycle. A separately identified benchmark-locator correction preserves timing
  boundaries and budgets. See [current results](evidence/gate-13/SIDEBAR_MENU_RESULTS.md);
  this is not a blanket performance, platform or release qualification.

### Searchable folder moves without per-card destination lists (Gate 13C)

- Each card keeps its current folder path visible. **Move to folder…** opens one
  searchable dialog with full paths, Unassigned and explicit confirmation.
- Keyboard focus/cancel, conflict retry, permission checks and stale-request safety
  pass in Chromium, Firefox and WebKit. The existing bulk workflow remains intact.
- The 104-folder fixture drops from 4,200 closed-card destination options to zero
  at 40 cards. Three fresh baseline Chromium organization runs pass unchanged
  enforced budgets; this is not an isolated speedup estimate or an upload limit.
- Full-gate inputs match `76b526d`: 351 API / 56 web tests and current HTTPS
  lifecycle, with the source-timing note preserved. Larger-folder stress and a
  separate 1,074 ms detail-preview long task remain unqualified; no general
  performance or release clearance. See [all results](evidence/gate-13/FOLDER_PICKER_RESULTS.md).

### Library request ordering and browser verification (Gate 13C)

- Fixed older asset/tag responses replacing newer search results, including after
  Trash restore. Stale pagination or departed-view errors cannot overwrite the
  current view; paging retains the applied query until new text is submitted.
- Added deterministic browser regressions, including a failing old-build control
  and preserved current sign-in enforcement. Firefox now completes the trusted
  disposable-HTTPS workflow without certificate bypasses or host trust changes.
- First-card visibility is measured in the browser, with the old wait duration
  retained separately. This is a measurement correction, not a claimed speedup.
- Full verification passes at `1255933`: 351 API / 51 web tests and current HTTPS
  recovery lifecycle. Chromium startup/interaction budget misses remain open;
  no release/performance clearance is claimed. See
  [browser correction evidence](evidence/gate-13/BROWSER_FIX_RESULTS.md).
- Follow-up [profiling](evidence/gate-13/CHROMIUM_PROFILE_RESULTS.md) identified
  repeated folder-option DOM and test-driver query costs. The approved picker
  implementation above follows that proposal; historical failures remain intact.

### Local dependency/runtime maintenance (Gate 13C)

- Patched the reviewed ZIP64 dependency issue with bounded regression coverage;
  refreshed compatible build dependencies, hash-locked Python installers and
  digest-pinned Python/Nginx runtime bases. Python remains on the 3.11 line.
- The complete gate passes at clean `ddf8cf4`: 351 API / 45 web tests and current
  production-HTTPS lifecycle verification. Refreshed application/tool locks report
  no advisories for the recorded scan date; whole-image findings remain open.
- Added the approved Stored/Deflate-only archive parsing guard with actionable
  recompression guidance. ZIP64, existing upload budgets and original prepared
  3MF bytes remain supported; unavailable settings do not require manual thumbnails.
  This mitigates the reviewed application read paths, not the interpreter advisory
  inventory. Current browser testing found an initial-load budget failure. No claim
  of release clearance or qualified performance is made; see
  [archive guard evidence](evidence/gate-13/ARCHIVE_GUARD_RESULTS.md).

### Current lifecycle verification (Gate 13B)

- Current harnesses use protected cookie sessions and CSRF, with no legacy JWT bypass.
- Local production-HTTPS verification covers schema-17 upgrade, matched raw
  restore, pre-start session/challenge invalidation, exact stopped rollback and
  portable clean-import startup with a new Administrator.
- Docker portable-import guidance now specifies private staging before populating
  empty volumes. No manual thumbnail requirement or application policy changed.
- The complete gate passes at `2c68d70`; current browser/performance, advisory,
  platform and selected-release qualification remain separate 13C work. See
  [13B evidence](evidence/gate-13/SUBGATE_13B_RESULTS.md).

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
