# MakersVault v5.1 — Draft Release Notes

> **Status:** In development. v5.1 has not been published yet. Gates 0–4 are
> complete in the local release candidate; upgrade, recovery, packaging, and final
> release approval remain Gate 5 work.

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

The accepted preview benchmark recorded zero navigation-blocking long tasks in the
candidate workflow and zero original model requests on its warm library pass.

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

The accepted organization benchmark exercised 600 models and 104 nested folders
with zero measured interaction long tasks.

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
- Login abuse is throttled for the supported single-administrator deployment model.
- Security, host, CORS, and protected-file response headers are generated and tested.
- Remote imports validate redirects, DNS resolution, and the connected peer to
  prevent requests from escaping into private or otherwise blocked network targets.
- Direct uploads, remote imports, ZIP extraction, images, previews, mounted sources,
  temporary storage, and free-space reserve use explicit resource limits.
- ZIP traversal, extreme expansion, symlink escape, malformed image, and partial-file
  cleanup cases have regression tests.
- Supported remote access remains an operator-managed HTTPS reverse proxy or private
  VPN. Exposing the application ports directly to the public Internet is unsupported.

### Safer desktop handoff

- Slicer and engraving handoff uses a short-lived grant for one exact file rather
  than sharing the browser session token.
- Each workstation confirms the exact MakersVault origin locally.
- The bridge validates file role, extension, redirect behavior, size, and origin
  before launching the configured application.
- Gate 5 will package and verify the matching v5.1 bridge installers.

## Upgrade-impact summary

- The candidate database schema is version 5.
- Migrations are ordered, additive, idempotent, and fail closed on unknown or
  mismatched versions.
- Schema 4 adds persistent preview outcomes.
- Schema 5 adds bounded mounted-scan records.
- Existing model bytes are not rewritten merely by applying these migrations.
- Production instances may need new deployment-specific authentication environment
  values before the v5.1 containers will start.
- API, web, and bridge components must be upgraded as a matched release.

Do not use this draft as the final upgrade procedure. Gate 5 will publish the tested
stop, matched database/storage backup, upgrade, verification, rollback, and clean-
machine recovery commands.

## Intentional limits and deferrals

- No manual thumbnail uploads.
- No visible G-code browser or ordinary prepared G-code download workflow.
- No slicing, printer control, telemetry, or print-farm scheduling.
- Fixed shared-vault roles and deny-by-default permissions are present, but account
  administration, MFA, API keys, OIDC, private libraries, and per-object ACLs remain
  gated.
- Permanent multi-model deletion remains constrained until Trash and restore exist.
- **Select every server match** remains deferred until a server-side bulk contract
  can avoid loading thousands of IDs into the browser.
- STEP/STP files remain storable and usable in supported handoff workflows, but
  automatic card-preview parsing is intentionally skipped by the v5.1 preview policy.
- Continuous NAS watching, live per-file scan events, and sophisticated mounted
  exclusions are future work.
- Content hashing, provenance, changed-source detection, and duplicate suggestions
  were deliberately deferred from v5.1 Gate 4B. They require bounded backfill and
  recovery proof and must never silently merge or delete models.
- The full Project → Artifact → Revision architecture is not part of v5.1.

## Verification completed so far

- Gates 0–4 have accepted source-owned evidence and local rollback points.
- Current API suite: 75 tests passing twice consecutively.
- Current web suite: 13 tests across 5 files, plus type checking and production build.
- Go bridge tests and executable build pass.
- Development, production, compatibility, benchmark, security, and smoke Compose
  configurations pass validation.
- Fresh container smoke passes with non-root processes and schema 5.
- Preview, 600-model organization, and real-browser mounted-scan workflows pass their
  deterministic acceptance checks.

All v5.1 feature-development commits remain local until the coordinated rollout.

## What remains before v5.1 ships

Gate 5 is the release gate. It must:

1. Classify essential data, rebuildable data, and externally owned no-copy data.
2. Write and execute stop, snapshot, upgrade, verify, rollback/restore, and clean-
   machine recovery procedures.
3. Upgrade representative pre-v5.1 libraries containing nested folders, legacy
   thumbnails, supporting files, prepared metadata, renamed models, missing mounted
   sources, and interrupted background work.
4. Restore a documented backup into a clean installation and prove the matched
   database/storage rollback path.
5. Run the performance, security, import, organization, bridge, and container
   matrices against a versioned release candidate.
6. Finish the changelog, security policy, contribution guide, issue templates,
   upgrade guide, known limitations, and final release notes.
7. Build versioned Docker and bridge artifacts from the release revision, then record
   their checksums, SBOM/provenance, and source revision.
8. Present the release candidate, limitations, and P1 deferrals for the owner’s final
   ship/no-ship approval.

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
- SHA-256 identity, duplicate suggestions, integrity checks, mounted changed-source
  detection, and provenance.
- Artifact revisions and recoverable Trash.
- Projects containing artifacts, revision history, supporting documentation, and a
  small useful relationship vocabulary.

These ideas begin with product and data-boundary design; they are not promises for
v5.1 and do not grant MakersVault machine-control authority.
