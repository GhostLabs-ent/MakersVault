# Gate 7D Project Lifecycle and Export Results

**Gate:** 7D — Project lifecycle and complete-history export

**Status:** Implemented; pending owner evidence acceptance

**Date:** 2026-08-25

**Entry commit:** `47dd233`

**Contract commit:** `76da76e`

**Implementation commit:** `3c2edd2`

**Schema:** 10 unchanged

**Publication state:** Local only. Nothing was pushed, tagged, or published.

## Delivered behavior

- Existing Project delete remains metadata-only. A new authenticated, bounded,
  deterministic Project Trash list reports retained, active, and trashed member
  counts plus stored relationship counts without joining Project lifecycle to the
  model-byte retention timer.
- Restore applies only to a trashed Project, preserves its ID, metadata,
  memberships, and relationships, clears `deleted_at`, and reports a structured
  `project_name_conflict` rather than renaming either Project.
- Permanent Project deletion applies only to a trashed Project and requires the
  exact typed phrase `PERMANENTLY DELETE PROJECT`. One Project-domain transaction
  removes only its relationships, memberships, and Project row. Member artifacts,
  revisions, files, current-revision state, paths, external sources, and bytes are
  unchanged.
- An authenticated active-Project download produces a ZIP64 archive with a
  versioned `makersvault-project-export` format-1 manifest. It includes Project
  metadata, every retained membership including model-Trash members, canonical
  stored relationships, stable artifact-ID namespaces, and per-artifact
  `complete`, `partial`, or `unavailable` status.
- Project export composes the existing artifact-history inventory one artifact at
  a time. Available immutable primaries, artifact attachments, revision-scoped
  attachments, and internal-role prepared payloads are written to distinct paths.
  Revision hashes and content truth are retained; related-file SHA-256 and
  ready/missing state are computed explicitly during export.
- Changed, missing, failed, pending, and external no-copy content is represented in
  the manifest without a false archive entry. Export does not import external
  bytes or present prepared payloads as ordinary attachments.
- Export holds the Project mutation lock for a coherent Project-domain snapshot,
  reads membership and relationship rows in deterministic batches, checks storage
  reserve, uses safe filenames and protected-response headers, and cleans temporary
  `.exports` files after response completion or build failure.
- The Project workspace has an Export action with session-expiry handling. Trash
  now presents Project and Model sections independently, including Project restore,
  exact-confirmation permanent delete, incremental Project loading, and explicit
  language that model retention/Empty Trash does not remove Projects.
- Standalone artifact-history export retains its route and manifest format. Gate
  7C relationships, Gate 7B retrieval/ingestion, folders, standalone library,
  artifact Trash, and legacy behavior remain available. No import/recovery format,
  schema, ACL, nested-Project, public-view, or server-backup claim was added.

## Regression-first evidence

The new backend lifecycle/export suite was first run against the accepted 7C
source and failed collection with:

```text
ModuleNotFoundError: No module named 'project_export'
```

The new web presentation regression likewise failed because
`./projectLifecycle` did not exist. These were the expected missing Gate 7D seams.
During final contract review, an added related-file hashing assertion failed
against the initial exporter with `KeyError: 'sha256'`; it then passed after the
export manifest gained computed related-file SHA-256 and content state.

After implementation, the focused Project lifecycle, revision, Project,
relationship, and Trash gate passed:

```text
python -m pytest -q tests/test_project_lifecycle_export.py tests/test_revisions.py \
  tests/test_projects.py tests/test_project_relationships.py tests/test_trash.py
39 passed
```

The backend regressions prove authentication; bounded Trash paging/counts; active
Project refusal; exact restore identities; structured name conflict; wrong and
correct permanent-delete confirmation; artifact/path/byte isolation; Project
metadata, membership, Trash-state, and relationship manifests; multiple managed
revisions; artifact and revision attachments; internal prepared payloads;
related-file hashes; changed external truth without copied bytes; deterministic ZIP
paths; ZIP64 and reserve use; protected response headers; and response/failure
temporary cleanup.

The web gate includes three Project lifecycle helper regressions for the irreversible
confirmation, explicit Trash counts, and response download filename. The complete
client gate passes with `20 passed`, TypeScript checking, and production build.

## Full verification

The untouched entry baseline at `47dd233` passed `make verify` before changes:

- API: `128 passed`
- Web: `17 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-10 container smoke, and the
  immutable v5.1 release contract passed

After the final implementation change, `make verify` passed on 2026-08-25 while
sleep was inhibited:

- API: `132 passed`
- Web: `20 passed`; TypeScript and production build passed
- Bridge: Go tests and build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose checks
  passed; production Compose still rejects missing authentication secrets
- Container smoke passed for direct and same-origin API access, security headers,
  the 512 MiB file policy, non-root API/web processes, and unchanged schema 10
- The immutable v5.1 release contract passed unchanged
- `git diff --check`, the explicit staged-file review, and credential/debug marker
  checks passed; the unrelated untracked architecture note remained untouched

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking.

## Rollback and residual scope

Gate 7D has no migration and no Project-owned byte layout. Code rollback leaves
ordinary schema-10 Project, membership, relationship, artifact, revision, and file
data valid. A deliberately permanently deleted Project cannot be reconstructed from
live rows; recovery requires a previously verified matched SQLite/storage backup.
Project export is a retrieval/portability archive, not a server backup or an
authorized import format.

Gate 7E still owns schema-aware Project/relationship recovery verification,
compatibility proof, and Gate 7 closeout. This evidence must be owner-accepted
before that work begins. Nothing may be pushed, tagged, or published.
