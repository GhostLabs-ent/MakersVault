# Gate 9C Export, Retrieval, and Interface Baseline

**Gate:** 9C — Portable machine references, retrieval, and descriptive interface

**Status:** Owner-approved; implementation authorized

**Date:** 2026-08-28

**Approved:** 2026-08-28

**Entry commit:** `d375cd2`

**Accepted relationship implementation:** `a9b09aa`

**Entry schema:** 12

**Entry export contracts:** artifact-history format 1, Project format 1

**Publication state:** Local only. Nothing is authorized for push, tag, release,
deployment, device connection, or publication.

## Verified entry state

Gate 9B was accepted on 2026-08-28 after its complete repository gate passed at
`a9b09aa`: 159 API tests, the verified web typecheck/21-test/build layer, bridge
tests/build, Compose/security validation, schema-12 container smoke, and the
immutable v5.1 release contract. Schema 12 now provides explicit neutral
Artifact-machine associations and exact nullable prepared targets on current
Assets and immutable Revisions. Supplied printer text remains source metadata and
is never converted into an identity without an explicit authenticated request.

The unrelated untracked desktop architecture note remains outside Gate 9 and is
not modified.

## Current 9C gaps

- Artifact-history format 1 exports prepared metadata and payloads but omits
  machine profiles, neutral associations, and exact prepared-machine IDs.
- Project format 1 composes those artifact histories and therefore also loses the
  new descriptive context outside the live database.
- `/assets` can filter by text, tags, folders, and Project scope but cannot retrieve
  artifacts by associated or current prepared Machine.
- The web has no Machine profile management or Artifact machine-context workflow.
  Gate 9B APIs exist, but the browser does not expose them.
- The web API types do not yet represent `prepared_machine_id` or the Gate 9B
  profile/context responses.

## Recommended export contract

1. Advance both `makersvault-artifact-history` and
   `makersvault-project-export` manifests to version 2. Keep ZIP filenames,
   existing entry paths, primary/revision bytes, attachment placement, and
   complete/partial/unavailable status rules unchanged.
2. Artifact-history format 2 adds a deterministic `machines` catalog containing
   one bounded snapshot for every referenced profile: ID, name, category,
   manufacturer, model, location, notes, created/updated timestamps, and archive
   timestamp. It also adds ordered neutral `machine_associations`, the current
   Asset `prepared_machine_id`, and each Revision's exact
   `prepared_machine_id`. Existing `prepared_metadata` remains unchanged and
   separate from trusted identity.
3. Every reference retains its stable profile ID. If corrupt legacy state contains
   a missing profile, export must preserve the unresolved ID and report it
   explicitly rather than silently dropping the reference, guessing a snapshot,
   or rewriting source metadata. Normal schema-12 state should have no such
   finding.
4. Project format 2 retains its existing membership/relationship truth and embeds
   independently usable format-2 Artifact histories. Its top-level manifest adds
   a deterministic de-duplicated Machine catalog and per-Artifact referenced
   Machine IDs so Project context is understandable without opening every nested
   manifest.
5. Exports remain read-only snapshots. Gate 9C adds no import, profile merge,
   identity matching, schema migration, stored-byte rewrite, or recovery-contract
   change.

## Recommended retrieval contract

1. Extend authenticated `/assets` retrieval with `machine_id` and a bounded
   `machine_scope` of `any`, `associated`, or `prepared`; `any` is the default when
   a Machine is selected. `associated` means an explicit `artifactmachine` row;
   `prepared` means the current Asset's exact target; neither inspects supplied
   printer text or historical Revisions.
2. Validate that the requested profile exists, including an archived profile, so
   retained context remains retrievable. Reject `machine_scope` without
   `machine_id` and preserve existing Project/folder/tag/text composition,
   deterministic ordering, pagination, and active-Artifact visibility.
3. Apply the same Machine filter to the authenticated tag-facet query so tag
   results describe the visible retrieval set. Use `EXISTS` predicates rather
   than joins so one Artifact appears once regardless of association count.
4. Keep historical prepared targets in the existing bounded Revision/context
   detail paths. A library query is current-state retrieval and must not imply that
   a historical target is still current.

## Recommended interface contract

1. Add a **Machines** section under Settings using the accepted profile fields and
   categories. It supports bounded list/search/filter, create/edit, archive,
   restore, and archive-first confirmed permanent deletion, with actionable name
   conflicts and cleanup counts. It adds no custom fields, address, credential,
   discovery, status, telemetry, or command control.
2. Add a lazily loaded Machine-context section to Artifact detail rather than
   issuing one context request per library card. It displays supplied printer text
   separately, manages explicit neutral associations, and sets/clears an exact
   prepared target only when prepared context exists.
3. The exact-target selector offers active FDM/resin profiles only. Existing
   archived references remain visible but cannot be newly selected. No likely-match
   suggestion or automatic/fuzzy linking is added in 9C.
4. Every context editor and prepared-target display includes the accepted wording
   **Descriptive context only. No job was sent.** Neutral associations use
   **Associated Machine**; the exact identity uses **Prepared for Machine**. The
   interface never says compatible, fabricated on, queued, sent, online, or ready.
5. Add a bounded Machine filter to library/Project retrieval with the explicit
   `Any relationship`, `Associated`, and `Prepared for` scopes. Filtering changes
   retrieval only; it never creates or changes a relationship.
6. Refresh affected Asset/context state after mutations without disturbing current
   folder, Project, selection, preview, handoff, prepared-payload, or Revision
   workflows. Machine management remains server data and is not stored in local
   browser settings.

## Regression and rollback requirements

- Prove format-1-to-format-2 changes through exact manifest assertions for active,
  archived, deleted, missing, neutral-only, current-target, and historical-target
  states. Existing archive paths and file hashes must remain identical.
- Prove Project exports de-duplicate profile snapshots, include trashed members'
  retained context, and remain deterministic across repeated exports.
- Prove retrieval scopes compose with Project/folder/tag/text filters, pagination,
  archived profiles, and multiple associations without duplicates or printer-text
  inference.
- Prove Settings lifecycle and Artifact context in the web through behavior tests,
  including destructive confirmation, category/archive constraints, explicit
  wording, and no per-card context-request fan-out.
- Re-run export, Project, Machine, Revision, prepared-print, Trash, API, web,
  bridge, Compose/security, schema-12 smoke, and complete repository verification.
- Gate 9C has no database or filesystem migration. Code rollback restores the
  format-1/UI behavior; already-created format-2 ZIPs remain immutable external
  artifacts and are not rewritten.

## Recommended owner decisions

1. Approve the exact format-2 fields and deterministic Machine catalogs above.
2. Approve current-state retrieval by Machine with the three explicit scopes.
3. Approve Settings Machine management plus lazy Artifact-detail context editing.
4. Defer likely-match suggestions; require direct explicit selection in 9C.
5. Keep schema 12 and recovery contract 3 unchanged until Gate 9D.
6. Authorize only 9C implementation and regression evidence. Do not authorize
   Gate 9D, import, device control, push, tag, release, deployment, or publication.

Recommendation: approve all six decisions without amendment. They make the
accepted descriptive context portable and usable while preserving the boundary
between metadata and machine authority.

The owner approved all six recommendations without amendment on 2026-08-28.
Implementation is authorized only for Gate 9C. Gate 9D, import, device control,
push, tag, release, deployment, and publication remain unauthorized.
