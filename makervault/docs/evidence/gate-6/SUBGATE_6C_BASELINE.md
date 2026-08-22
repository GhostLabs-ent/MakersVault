# Gate 6C Trash Implementation Contract

**Gate:** 6C — Recoverable Trash, retention, and permanent deletion

**Status:** In progress

**Opened:** 2026-08-22

**Entry commit:** `37400ad`

**Dependencies:** Gate 6B owner-accepted; ADR 0008 accepted with owner amendment

## Objective

Replace normal destructive model deletion with desktop-style recoverable Trash,
then make every irreversible path explicit, complete-artifact scoped, durable, and
auditable.

## Implementation contract

1. The legacy model-delete route becomes metadata-only soft deletion. It records
   deletion time and original folder identity/location without moving or deleting
   primary, revision, attachment, prepared, preview, or external bytes.
2. Normal browse, search, tags, counts, duplicate suggestions, handoff, direct
   download, revision mutation, and related-file routes reject or exclude trashed
   artifacts. Dedicated authenticated Trash routes are the only visibility surface.
3. Restore returns to the surviving original folder. A missing folder requires an
   explicit restore-as-Unassigned choice. A case-insensitive name conflict returns
   `409`; it never renames or overwrites silently.
4. Retention choices are exactly `until_needed` (default), `day`, `week`, `month`,
   and `never`. Time choices purge only artifacts old enough for that policy.
   `never` disables every automatic permanent-deletion path.
5. Capacity cleanup runs before a managed write breaches the configured reserve.
   Under `until_needed`, it selects oldest Trash first with stable ID tie-breaking
   and purges complete artifacts only until the predicted write fits. Time policies
   may reclaim only already-expired Trash. Failure to reclaim enough returns `507`.
6. Explicit permanent deletion and Empty Trash work only on trashed artifacts,
   require a typed confirmation token, return per-artifact outcomes, and never
   delete an external no-copy source.
7. Permanent deletion inventories exact managed paths, moves them into an
   operation-specific same-filesystem quarantine, records the mapping durably,
   deletes database ownership in one transaction, and then removes quarantine.
   Database failure restores moved paths; cleanup failure remains retryable.
8. Startup reconciliation completes or rolls back known operations. Unknown
   quarantine directories are reported and never silently deleted.
9. Trash UI shows deletion time, original location, managed size, external-source
   status, retention policy, Restore, Permanent delete, and Empty Trash consequences.
10. Backup/export compatibility includes trashed database state while content
    exists. Schema expansion is additive and operational rollback remains a matched
    database/storage restore.

## Required evidence

- schema-7 upgrade adds active Trash defaults without moving bytes;
- normal and direct-ID surfaces cannot expose or mutate Trash;
- restore success, missing-folder confirmation, and name-conflict rejection;
- every retention choice and oldest-first stable capacity selection;
- safe `507` when Trash cannot satisfy reserve or policy is Never;
- quarantine success, simulated move/transaction/cleanup failures, reconciliation,
  and unknown-quarantine reporting;
- permanent deletion never touches external no-copy sources and removes all managed
  revision/bundle/preview bytes;
- UI build/tests, container schema smoke, and the full repository harness pass.
