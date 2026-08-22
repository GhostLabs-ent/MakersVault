# Gate 6A Content-Truth and Revision-Expansion Evidence

**Gate:** 6A — Content truth and revision expansion

**Status:** Evidence review

**Evidence date:** 2026-08-22

**Implementation commit:** `c7e8743`

**Entry schema:** 5

**Resulting schema:** 6

**Publication state:** Local only; no commit, tag, image, binary, or release was pushed

## Objective result

Schema 6 establishes the content-identity and revision foundation without moving
existing bytes. Every existing Asset receives exactly one deterministic revision-1
record and a current-revision pointer. Existing primary, source, prepared, and
preview fields remain as the compatibility projection required by ADR 0007.

New direct uploads, URL imports, selected ZIP entries, mounted copies, and mounted
no-copy indexing calculate SHA-256 in the same bounded streaming pass already used
to write or inspect the file. No ingestion path performs an avoidable second full
read merely to establish identity.

## Migration evidence

Migration 6 is additive. It introduces:

- `artifactrevision` with immutable revision identity, primary/prepared/preview
  projection, SHA-256, observed digest, and explicit content state;
- `asset.current_revision_id` and optional `assetfile.revision_id`;
- durable `contenthashjob` progress and bounded result counts; and
- durable `contenthashjobitem` work items so large libraries resume without loading
  every ID into browser or worker memory.

The representative pre-v5.1 fixture and the focused schema tests prove:

- fresh and upgraded databases reach schema 6 idempotently;
- every prior Asset keeps its ID, filename, storage/source path, metadata, prepared
  pointer, and preview projection;
- exactly one revision is seeded per Asset;
- revision 1 references existing paths without byte relocation; and
- prepared `AssetFile` rows associate with the seeded revision while ordinary
  supporting files remain artifact-wide.

Legacy Asset columns are not contracted.

## Content-state and job evidence

The content worker processes one revision at a time by default. It persists the
queue and per-item terminal result, converts interrupted work back to pending on
restart, and reports aggregate progress plus at most 50 findings through an
authenticated API and Settings view.

The implemented states are:

```text
pending -> ready
        -> unavailable
        -> changed
        -> failed
```

An initial matching read records SHA-256. Later verification records the observed
digest but preserves the original when bytes differ. Existing content is not
subject to the current upload-size limit during hashing; work is bounded by one
active file rather than by an artificial library or historical-file cutoff.

Settings exposes missing-content backfill and deliberate verify-all actions, live
progress, ready/changed/unavailable/failed counts, and bounded findings. Startup
resumes interrupted or pending legacy work. If there is no pending work it does not
create an empty job.

## Duplicate semantics

An authenticated artifact endpoint suggests other current revisions only when
SHA-256, byte size, and ready state match exactly. It does not merge records,
hard-link bytes, delete content, or claim semantic equivalence.

## Automated evidence

The complete repository `make verify` harness passes against the implementation
tree committed as `c7e8743`:

| Area | Result |
|---|---|
| API | 86 tests pass under Python 3.11, including migration, no-relocation, streaming identity, duplicate suggestion, changed-byte preservation, durable resume, mounted import, recovery, security, and prior behavior |
| Web | Type-check, 13 tests, and production Vite build pass; the Settings integrity view compiles into the production image |
| Bridge | Go tests and build pass unchanged |
| Compose/security | Canonical manifests, aliases, security validation, and overlays pass |
| Container | Fresh API/web smoke passes as non-root with schema 6 and same-origin behavior |
| Release contract | The immutable v5.1 release contract still verifies; Gate 6 remains after and excluded from that candidate |

The targeted content/migration suite separately reports 9 tests passed. A repeated
full API run reports 86 tests passed.

## Security, recovery, and failure behavior

- Hashes and filenames remain local; no remote lookup was added.
- External hashing uses the existing contained, symlink-resistant mounted-file open
  boundary rather than reading arbitrary database paths.
- Managed revision paths are resolved beneath the storage root.
- One missing, changed, or malformed file becomes a terminal per-item result and
  does not stop later work.
- The database queue is set-based and the worker claims one item at a time, so the
  browser and worker do not materialize an unbounded list of library IDs.
- Failed primary ingestion removes the initial revision along with the incomplete
  Asset; the current pre-Trash delete compatibility path also removes revision rows.

The matched schema-5 database/storage backup remains the rollback boundary. Backup
format 1 still captures the entire SQLite database and storage tree, so the new
tables are physically captured; revision-aware manifest inventory and clean restore
assertions remain explicit subgate 6D work.

## Deliberate boundaries

Gate 6A does not yet provide primary replacement, multiple revisions, history
restore/export, or immutable historical storage workflows; those are Gate 6B. It
does not change normal deletion into Trash or implement the approved capacity/time
retention settings; those are Gate 6C. It does not contract schema-5 projections or
claim complete revision-aware recovery evidence; those are Gate 6D.

## Acceptance recommendation

Accept subgate 6A. The content/revision expansion is additive, bounded, resumable,
visible, and locally verified without byte relocation or automatic deduplication.
Proceed to 6B immutable revision creation, current/history UI, prepared and
attachment ownership, restore, and history export.
