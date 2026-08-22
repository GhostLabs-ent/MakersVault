# Gate 6B Immutable Revision Workflow Results

**Gate:** 6B — Immutable revision creation, restore, and export

**Status:** Accepted

**Date:** 2026-08-22

**Entry commit:** `45bbc22`

**Implementation commit:** `c6ddcfe`

**Accepted:** 2026-08-22

## Delivered truth

- Replacing a primary file streams into isolated staging, computes SHA-256 during
  the write, then commits a new immutable revision and current projection.
- A replacement identical to the current bytes is a visible no-op. A client may
  supply its expected current revision; stale concurrent writers receive `409`
  rather than silently replacing a newer version.
- Managed history lives at
  `revisions/{artifact-id}/{revision-id}/{filename}`. Artifact rename, folder,
  tags, collection, and storage-template changes do not move or relabel history.
- Restore verifies historical size and digest, then copies the selected primary,
  preview, prepared metadata, and any prepared payload into a new current
  revision with an origin pointer. It never reactivates the historical row.
- Supporting files remain artifact-wide by default. The upload UI offers a
  deliberate current-version-only checkbox. Prepared files remain hidden from
  ordinary supporting-file browsing and are associated with the current revision.
- The model card exposes an on-demand version timeline with change notes, current
  and content-state badges, historical download, restore, add-version, and complete
  history export controls.
- Authenticated history export produces a ZIP64-capable archive with a versioned
  JSON manifest, every available primary, artifact and revision attachment scopes,
  prepared payloads in labelled revision paths, hashes, and unavailable/changed
  states. Temporary archives are reserve-checked and removed after response.
- Compatibility deletion now removes every managed revision primary, historical
  preview, and related file. Recoverable deletion and retention remain isolated to
  Gate 6C.
- Schema 7 is additive. Existing revision/current projections gain only the
  current-thumbnail projection needed to prevent historical preview overwrite.

No separate thumbnail-upload workflow was added. Preview generation remains
automatic or embedded, consistent with the owner decision.

## Focused evidence

`makervault/api/tests/test_revisions.py` proves:

1. replacement success, immutable historical/current downloads, and change notes;
2. identical-current no-op;
3. stale concurrent replacement rejection and clean staging;
4. failed upload-stream compensation with the prior current revision unchanged;
5. changed historical bytes rejected during restore;
6. restore-as-new with origin linkage;
7. prepared-print payload copying and revision ownership on restore;
8. artifact-wide and revision-scoped supporting-file visibility and export layout;
9. history-export manifest and primary/attachment byte inclusion;
10. complete managed revision cleanup during compatibility deletion;
11. artifact rename without historical path or filename mutation; and
12. revision-specific preview regeneration without historical thumbnail overwrite.

Migration and content-identity suites additionally prove schema-5-to-7 expansion,
current-thumbnail backfill, unchanged byte paths, and compatibility of the Gate 6A
hashing job with immutable workflows.

## Verification record

From repository root:

```text
make verify
```

Result: pass.

- API: `95 passed`
- Web: `13 passed`; production build passed
- Slicer bridge: Go tests and build passed
- Compose/security: canonical, deploy, smoke, benchmark, and mount-scan manifests passed
- Container smoke: passed with schema 7
- Release contract: passed; the immutable v5.1 candidate remains unchanged
- `git diff --check`: passed before the implementation commit

Existing non-blocking frontend dependency-age and bundle-size warnings remain the
same class already recorded for the v5.1 candidate.

## Boundaries carried forward

- Gate 6B does not expose prepared G-code as an ordinary browser file. It is
  available only through slicer handoff, its current prepared endpoint, explicit
  restore semantics, and complete-history export.
- Export intentionally uses temporary capacity proportional to one artifact's
  available history; it is an explicit user action rather than background work.
- Revision rows and bytes are not individually erasable. Gate 6C owns artifact
  Trash, retention, restoration, capacity cleanup, and permanent deletion.
- Operational rollback remains a matched database and managed-storage restore;
  schema contraction is not authorized.

## Owner checkpoint

Accept Gate 6B before beginning Gate 6C. Acceptance confirms the immutable
replacement/restore semantics, default artifact-wide attachment scope, optional
current-version scope, prepared-payload invisibility, and explicit complete-history
export.
