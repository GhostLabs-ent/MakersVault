# ADR 0020: Workstation printer presets and immutable plate recipes

**Status:** Accepted by owner on 2026-09-12; not an implemented API or schema.
**Date:** 2026-09-12. **Application baseline:** schema 17 / bridge `d116997`.

**2026-09-13 release-scope amendment:** the owner [defers only new macOS workstation
preset discovery/import/refresh from v5.1](../evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md).
Existing Mac file-open and planned browser Make Plate scope remain unchanged.
This does not weaken this ADR's safety, consent, data-model or recovery contracts.

## Context and scope

The owner approved [Make Plate](../MAKE_PLATE_RUNBOOK.md) while deferring CNC/CAM.
Extend ADRs 0012/0013 without turning descriptive Machines into online devices,
giving download grants write access, or treating preview meshes as authoritative.
UP-1 is separate; this ADR adds no upload cap or requirement to upload images.

The existing bridge runs on the **slicer workstation**, not necessarily the Docker
host. Import/refresh is optional and user initiated. The first adapter is Bambu;
Orca and Prusa need independent parser and real-application conformance. A saved
preset permits planning without the bridge online; launching a slicer still needs it.

## 1. Typed presets, not a second machine registry

Introduce these additive entities in MP-1 (names are the contract's logical names):

| Entity | Identity and ownership |
|---|---|
| `PrinterPreset` | Stable UUID, required active FDM `machine_id` at creation, label, current snapshot, timestamps and archive state. Label unique within that Machine's active presets. A Machine may have multiple nozzle variants |
| `PrinterPresetSnapshot` | Immutable UUID and sequential version within the preset; typed imported values, typed overrides, effective geometry, source/adapter versions, field provenance and canonical normalized digest |
| `PresetImportRequest` | Short-lived, account/session-bound operational consent and staging state; not content, a device identity or a portable record |

The browser explicitly chooses an existing FDM Machine or creates a descriptive
one through the ordinary authorized workflow. Discovery never asserts that a
printer is owned, installed, reachable or compatible. Names alone never merge
records. No background scan creates a Machine.

### Snapshot v1 wire shape

Strict versioned objects; reject unknown fields at the bridge/API boundary.
Numbers are finite JSON numbers, dimensions in millimetres, labels bounded to 200
characters without control characters. The payload contains only:

- `schema_version=1`, adapter ID (`bambu`, `orca`, `prusa`), adapter/parser version,
  reported application version and profile-bundle version where observable;
- bounded source preset/model/variant identifiers and display labels, source kind
  (`system` or `user`) and a normalized-field fingerprint, **not** host paths;
- `technology=fdm`, one explicitly selected `nozzle_diameter_mm`;
- `bed_polygon_mm`: a simple outer polygon; `exclusion_polygons_mm`: zero or more
  simple polygons; `max_height_mm`; and a source-coordinate translation;
- typed provenance for required fields (`source`, `inherited`, `user_override`,
  `unknown`), bounded reason codes and capture time assigned by the server.

Canonical coordinates are right-handed XY with Z up, millimetres, origin at the
bed polygon's minimum X/Y. Preserve the source XY offset separately so UI/export
does not confuse a centered bed with a corner-origin bed. Translate bed and
exclusions together; do not rotate, resize or replace a nonrectangular bed with its
bounding rectangle. Rendering may use its bounding rectangle, validation may not.
Reject self-intersections, degenerate geometry and nonfinite coordinates. Initial
limits: 256 vertices per polygon, 16 exclusion polygons, 10,000 mm maximum bed
span/height and 0.05–10 mm nozzle diameter. These are input-safety limits, not
printer compatibility claims; exceptions require a reviewed contract change.

An absent exclusion definition is **unknown**, not necessarily an empty list. A
qualified adapter may map a format-defined absence to no exclusions and record
that basis. Missing bed/height/nozzle or unsupported multiple-tool semantics makes
the candidate incomplete. It can be reviewed and explicitly corrected, but cannot
be used for planning until required geometry is valid. Do not infer geometry from
a marketing name, bed texture, thumbnail or advertised build volume.

Overrides are the same typed geometry fields, stored separately with actor/time.
Actor links are nullable; portable import preserves bounded attribution as content,
not a live account reference or authority in the destination vault.
They never overwrite the imported snapshot or expand into arbitrary slicer settings.
Refresh creates a new immutable snapshot after a visible comparison and confirmation;
existing overrides remain visible and require confirmation against changed source
values. Renamed/missing/ambiguous sources require explicit re-selection. Existing
recipes stay bound to their old snapshots.

### Reader boundaries

Only adapter-owned known profile locations or an explicitly configured local
profile root may be read. The browser/server cannot supply filesystem paths.
Resolve paths beneath the chosen root with symlink/reparse-point and traversal
checks; never follow profile values to arbitrary files, URLs or network shares.
User/account directory names stay local. The bridge reads local copies only; it
never logs into slicer cloud services, fetches presets, or changes slicer files.

Resolve inheritance by exact preset identity in the selected source namespace,
with adapter-specific precedence. Duplicate ambiguous identities, cycles, missing
parents, unknown schemas and unsupported include/merge semantics produce actionable
errors. Never execute templates/macros or import process/filament scripts.
JSON `include` references to G-code templates are not followed. Qualification must
prove all required geometry is obtained without them; otherwise mark unsupported.
Do not guess Prusa's multiple-parent precedence from Bambu's single-parent format.

Initial per-scan limits: 10,000 candidate files, 8 MiB per file, 128 MiB bytes read,
inheritance depth 16, 15-second wall budget and cancellation. Stream/index where
needed; do not retain all raw profile text. Up to 100 selected normalized presets
and 2 MiB total submission per import request. Report limits and incomplete scans;
users may narrow selection/retry without any change to vault upload limits.
Never copy network/account/credential fields, start/end G-code, arbitrary notes,
bed image/model paths or raw configuration into a payload. User-authored preset
labels may themselves contain private text: show exactly what will be shared.

## 2. Explicitly reviewed import, not a writable download token

Use the existing general scheme with a new, strictly versioned `import-presets`
action. Old bridges reject the action; the browser explains the matched-update
requirement. Preserve all three file-open schemes and their existing grants.

Sequence (all server endpoints below are **planned**, not currently reachable):

1. Signed-in Member/Administrator explicitly starts import in MakersVault. A new
   `preset.import` permission is separate from `handoff.create`; Viewer lacks it.
   Session, CSRF, exact origin and current role checks apply. Issue a five-minute
   request plus a random 256-bit, single-claim capability, bound to account, session,
   canonical HTTPS origin/API prefix, selected adapter and contract version.
2. The workstation bridge validates the protocol action and exact endpoint shape,
   refuses redirects/proxies, and obtains local consent before discovery. An origin
   trusted for **file downloads** does not imply permission to share presets.
   A fresh random bridge verifier and SHA-256 challenge claim the request atomically.
   The capability permits only this claim, not account or vault reads/writes.
3. Both browser and local page show a short matching code and adapter/origin; the
   user confirms the claimed workstation request in the authenticated browser.
   The code is a human check, not an authentication secret or hardware attestation.
   A competing claim cancels/restarts the operation; it cannot replace the claimant.
4. Only after approval may the bridge submit the locally selected normalized
   presets using the claim capability **and** verifier. The API validates the exact
   schema/budget, consumes the submission once and stores a short-lived preview.
   Repeating the identical digest returns the same staged receipt; a different
   replay conflicts. No Machine or PrinterPreset is changed yet.
5. The same authenticated account/session reviews the actual staged values, chooses
   target Machines and confirms creation/refresh. A CSRF-protected commit request
   includes the preview digest and expected preset version. Recheck current roles,
   target lifecycle and expiry, then publish the selected records atomically.
   Changed versions, permissions or payloads require a new review, never last-write-wins.

Planned route families: session-owned create/status/approve/commit/cancel under
`/preset-imports`; separately classified scoped claim/status/submit routes. Request
IDs alone give no authority. Add a new access kind; do not reuse `SCOPED_HANDOFF`
or mark these routes public to satisfy the exhaustive authorization inventory.
The bridge only polls its bounded request state; it cannot enumerate other imports.

Store only capability/verifier digests. Redact grants, protocol URLs, matching codes
and local paths in logs/audit; audit request/actor IDs, action, counts and outcomes.
No session cookies or admin tokens are passed to the bridge. No LAN listener,
persistent service, remote executable or browser-supplied callback URL is introduced.
Reuse a short-lived nonce-protected loopback consent page where needed; browser
polling of the normal HTTPS API avoids cross-origin localhost API access.

Cancel, expiry, session revocation/logout, account disable/role loss and recovery
invalidate the operation. Recheck local trust before submission; local revocation
also aborts pending work. Five pending requests per account, 100 instance-wide;
return a bounded error when full and purge expired operational rows. Reject oversized
bodies before JSON parsing. Exact duplicate commit is idempotent by request ID;
network failure must never duplicate profiles.

This binding identifies one approved operation and its ephemeral claimant, **not**
a verified physical computer. Local malware or a user who approves a mismatched
code remains outside that assurance. MP-1 negative tests must cover claim races,
replays, stolen claim without verifier, wrong origin/account/session/adapter,
revocation, stale versions, unknown fields, CSRF and response/log leakage.

## 3. Saved recipes preserve intent and source identity

MP-2 adds a Project-owned `PlateRecipe` and immutable `PlateRecipeVersion` records.
Recipe identity/name/archive state is separate from its current version. Every
save creates a version with optimistic concurrency; updates do not rewrite prior
recipes, source revisions or preset snapshots. No new library Asset is invented
merely because a layout was saved.

A recipe version records:

- Project/recipe identity and version; full effective preset snapshot plus its
  identity/digest and descriptive Machine snapshot;
- deterministic algorithm/version, spacing, boundary clearance and tolerance;
- stable instance IDs, exact Artifact/Revision identities, verified primary SHA-256,
  byte size and STL type, quantity expanded into individual instances;
- explicit source-unit interpretation (`mm` or `inch`) and conversion factor
  (1 or 25.4), XY translation, Z placement and rotation about Z; and
- validation results/reason codes and timestamps, not a print-ready assertion.

STL has no reliable declared unit. Require confirmation of interpreted dimensions
before initial planning. Conversion is explicit and recorded; never silently scale
or shrink to fit. Keep the selected source orientation; automatic placement uses
only 0/90-degree Z rotations and conservative bounding boxes. Manual Z rotation
is allowed; lay-flat, mirroring, arbitrary scaling and automatic supports are not.
Placing the lowest point at Z=0 is an explicit recorded transform, not a byte edit.
Use full primary geometry in an isolated cancellable worker, not thumbnail geometry.

New selections must be active Project members with available verified STL primary
revisions; no substitution of a newer revision when the selected one disappears.
Pin and verify bytes again at export. Initial worker budgets and numerical/packing
tests are an MP-2 entry checkpoint, not a promise of unbounded tablet processing.
Report “not placed by this arrangement” instead of “cannot fit”. Invalid draft
layouts may be saved with warnings, but not exported as a valid arranged plate.

### Lifecycle rules

| Event | Recipe/preset behavior |
|---|---|
| Source renamed, moved or revised | Existing version keeps exact revision, size, digest and transforms |
| Source removed from Project | Keep existing recipe reference; flag detached membership; no implicit re-add or source substitution |
| Source in Trash/missing/changed | Block regeneration/handoff; show reason; restoration must revalidate exact bytes |
| Source permanently deleted | Clear nullable live FK only; retain immutable identity/hash tombstone, never retain/recreate deleted source bytes through a cache |
| Machine/preset archived | No new selection/association; existing recipes retain snapshots and remain inspectable; using them warns that the target is archived |
| Machine/preset permanently deleted | Clear nullable live links, keep recipe snapshots; explicit new target required for a new recipe, never guess a replacement |
| Project trashed/restored | Hide/restore its recipes with it; do not trash member Assets |
| Recipe archived/deleted | Restore supported; permanent deletion requires existing recent-auth Administrator permission and typed confirmation; deletes recipe metadata/derived cache only |
| Project permanently deleted | Delete its recipes and derived cache, never shared source Assets or Machines |

Existing recipes may be edited against their embedded preset snapshot after preset
archival/deletion; they do not create a new association with an archived Machine.
New target selection requires an active FDM Machine/preset. Ordinary recipe writes
use `content.manage`; reads use `vault.read`; export/download and handoff retain
their existing distinct permissions. Viewer cannot import presets or save edits.

## 4. Editable 3MF output, not pre-sliced content

MP-3 generates standard unsliced 3MF with separate object/instance identity, units,
transforms and bounded human labels. No source 3MF/G-code, print-time estimate,
material compatibility, supports or arbitrary slicer settings are inherited. The
UI says **“Layout for … · unsliced · review in slicer”**, not “Prepared for …”.

Use a versioned derived-output identity bound to recipe version, exact source
digests, preset and exporter version. A transient cache is never authoritative;
recheck authorization, Trash/availability and source hashes before serving it,
even on a cache hit. Cache purge follows source/project/recipe permanent deletion.
Do not export this cache as a supporting file or make it an internal prepared payload.

Extend the existing exact-file handoff with a narrowly defined generated-plate
content role and only qualified slicer adapters. Old catalog/bridge combinations
fail closed. Grants still authorize only one exact downloadable file and never
authorize slicing or printing. Actual slicer tests must verify separate editability,
object count, scale, placement and selected printer behavior. If a slicer recenters
objects or ignores printer selection, report it and qualify/fix that adapter; valid
XML or successful process launch does not close the gate.

## 5. Additive schema, portable export and recovery

Current facts: schema 17; `.mvault` major 1 with strict catalogs; clean import stages
schema 12 before normal startup migration; raw backup format 1 / recovery contract 6;
Artifact/Project export format 2. Do not alter released migration checksums.

MP-1 uses the next unused additive migration (anticipated 18) for presets/import
staging. MP-2 uses the next after that for recipes; verify numbers at implementation.
No source bytes move. Enforce FK/uniqueness/version constraints, nullable cleanup
and server-side typed validation. A migration is not qualified until its whole
export/recovery counterpart ships in the same slice.

- Advance portable writer to `.mvault` major **2** when presets persist, retaining
  v1 readers. Required feature `printer-presets-v1` adds logical preset/snapshot
  catalogs. Later `plate-recipes-v1` adds recipe/version/instance catalogs; earlier
  v2 readers reject that unknown required feature instead of dropping records.
  Preserve two-stable-release v1 readability from ADR 0014.
- V2 clean import stages its supported current schema and validates all typed
  geometry, immutable versions, live links/tombstones and hashes before publication.
  V1 import remains supported through its proven schema-12 staging and subsequent
  additive migrations; imported old vaults start with no invented presets/recipes.
- Portable export includes preset/recipe content, not import requests/capabilities,
  sessions, bridge trust, workstation roots or derived output caches. Missing
  external source bytes remain an explicit partial-content condition. Selected
  Project export advances to format 3 when recipes exist, including their exact
  source-revision closure and snapshots, including detached-member references.
  Artifact-history format 2 stays unchanged unless its actual contract changes.
- Raw backup outer format stays 1; advance recovery contract for each newly captured
  schema/graph. Audit all new tables, counts, hashes, references and deletion rules.
  Restore invalidates every pending import/claim alongside existing session/grant
  invalidation; include that mutation in recovery comparisons, not a wildcard skip.
- Older binaries refuse newer schema/required features. Rollback uses the matched
  pre-migration raw database/storage backup, not an in-place downgrade or a v2
  archive fed to a v1 importer. Preserve pre-change backup and failed staging output
  under the existing recovery rules.

## Consequences and acceptance

This is more than a bridge parser: content portability and scoped consent are
required before persistent import. It keeps an optional workflow optional, preserves
source bytes and prevents a layout from becoming an unsupported print-safety claim.
The [fixture inventory](../evidence/gate-13/MAKE_PLATE_FIXTURES.md) distinguishes
reviewed public formats from installed-device evidence. The owner's reported Bambu
`v2.8.0.6` is a separate target, not assumed to match a nearby public tag.

The owner accepted MP-0 and directed continuation on 2026-09-12, approving these
contracts and the separately verified bridge repairs.
MP-1 starts with Bambu parser fixtures/negative tests, then the additive schema,
authorization and portable/recovery path. No current API, data migration, slicer
profile scanning, install on the owner's device, signing service, CNC/CAM, network
printer control, release waiver or publication is authorized by merely writing this ADR.
