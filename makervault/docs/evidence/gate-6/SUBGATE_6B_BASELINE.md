# Gate 6B Immutable Revision Workflow Contract

**Gate:** 6B — Immutable revision creation, restore, and export

**Status:** Implemented; awaiting owner acceptance

**Opened:** 2026-08-22

**Entry commit:** `45bbc22`

**Implementation commit:** `c6ddcfe`

**Dependency:** Gate 6A owner-accepted

## Objective

Turn the one-revision content foundation into a trustworthy user workflow without
rewriting historical bytes or introducing Projects.

## Implementation contract

1. Primary replacement streams into an operation-specific staging path, calculates
   size and SHA-256 during that write, and does not change the current pointer until
   the final immutable path and database row are ready.
2. New managed primary revisions use
   `revisions/{artifact-id}/{revision-id}/{filename}`. Historical revision paths do
   not change when artifact name, folder, tags, collection, or storage template
   changes.
3. Uploading bytes identical to the current revision returns a visible no-op. It
   does not create a revision or rewrite the current file.
4. The current Asset projection changes in the same database transaction as the
   current-revision pointer. A failed transaction removes staged/final new files and
   leaves the prior revision current.
5. Existing current thumbnails are preserved under a revision-specific path before
   the first replacement. New revision previews use revision-specific paths; a
   current preview cannot overwrite historical preview bytes.
6. Restoring history verifies the selected bytes against the recorded size and
   SHA-256, then creates a new managed current revision whose origin points to the
   historical revision. It never reactivates or mutates the old row.
7. An unavailable or changed external revision cannot be restored. The user must
   make the matching bytes available or upload a deliberate new revision.
8. Visible supporting files remain artifact-wide by default. Upload may optionally
   scope a supporting file to the current revision. Prepared files always belong to
   the current revision and stay excluded from ordinary supporting-file browsing.
9. Normal artifact download and handoff use the current revision projection. An
   authenticated revision download retrieves a specific historical primary.
10. Complete-history export contains a versioned manifest, every available primary
    revision, artifact-wide and revision-scoped attachments, internal prepared
    payloads in an explicitly labelled path, hashes, and missing/changed external
    states.

## Failure and rollback contract

- Stage and final paths are validated beneath managed storage and never derive
  authority from a client-supplied path.
- Revision creation is serialized per API process and protected by the database
  uniqueness rule on artifact/revision number.
- Any filesystem work before a failed database commit is compensated. A later
  reconciliation test covers process interruption between file finalization and
  database commit.
- Schema expansion remains additive. Schema-5 Asset projections stay readable and
  are not contracted.
- Operational rollback restores the matched pre-Gate-6 database/storage backup.

## Required evidence

- replacement success, identical no-op, conflicting/concurrent creation, and
  interrupted/failed write;
- unchanged historical bytes and revision-specific thumbnails;
- revision download, current download, prepared ownership, artifact/revision
  attachment scope, and hidden prepared browsing;
- restore creates a new revision and rejects changed/missing history;
- complete-history export manifest and bytes round-trip;
- schema-5 upgrade remains no-relocation and the full repository harness passes.
