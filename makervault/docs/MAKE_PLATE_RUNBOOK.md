# Upload progress and Make Plate — release-scope amendment

**Decision date:** 2026-09-12. **Entry:** `4858147` (schema 17).
**Status:** Owner-authorized scope; UP-1 verified locally, awaiting acceptance.
Make Plate/bridge implementation and qualification are not complete.

The owner requested review of the working ROADMAP notes from line 349, then
approved the proposed bounded direction: “lets defer CNC for a later release …
The other features lets deffinetly do it”. This authorizes local implementation,
not publication, a production deployment, or an automatic Gate 13 closeout.

## Release scope

- Visible 0–100% byte-weighted upload transfer progress, saved/failed counts and
  finalizing state. Existing upload limits, folder placement and Project membership
  remain unchanged. No server upload-job/resume system is implied.
- Extend the existing Go bridge; no second mandatory helper. It runs on the
  **slicer workstation**, which may differ from the Docker host.
- User-initiated discovery/import/refresh of printer presets, starting with Bambu
  Studio against the owner's Windows tablet, followed by OrcaSlicer and separately
  qualified PrusaSlicer support. A parser or cross-build alone is not qualification.
- Versioned, typed printer-preset snapshots linked to the existing MachineProfile
  identity. Include normalized units/origin, bed polygon/exclusions, maximum height,
  nozzle variant, source identity/version and explicit user overrides. Do not treat
  discovered presets as evidence of owned or online physical printers.
- Project Make Plate: exact selected STL revisions and quantities, chosen preset,
  conservative bounding-box packing with 90-degree rotations, configurable spacing,
  manual movement/rotation, boundary/exclusion/height checks and interactive preview.
- Save a plate recipe and export an editable multi-object 3MF; open it through the
  existing exact-file grant and explicitly selected local slicer. Preserve source
  bytes and object scale; never silently shrink parts to fit.
- Plate computation remains possible with a saved preset when the relay is offline
  and MakersVault is available. Local slicer launch requires the workstation bridge.

**Deferred:** CNC/CAM integration and CNC-specific adapters; full 3MF/STEP input
conversion for plate generation; resin workflows; background profile synchronization;
advanced nesting, automatic orientation/supports, multi-plate splitting, material
grouping, direct printer discovery/status/control, queues, USB/serial integration.
Existing file-open adapters and descriptive CNC machine records are not removed.
No server-side slicing, G-code generation, printing or manual-thumbnail requirement.

If a supported slicer needs more work than its gate permits, report the evidence
and ask the owner to trim support rather than silently promising or removing it.

## Architecture boundaries

1. Extend [ADR 0013](adr/0013-descriptive-machine-profiles.md) through explicit typed
   preset/plate schemas, not an unrelated machine registry or arbitrary settings bag.
   Multiple nozzle presets may reference one Machine. Preserve nullable/neutral
   associations, immutable prepared metadata and current lifecycle semantics.
2. Profile reading is allowlisted, read-only and bounded. Resolve inheritance with
   path, size and cycle limits; do not guess missing geometry. Present selection
   before import; never send slicer credentials, access codes, scripts or arbitrary
   local paths to MakersVault. Keep overrides separate from imported values.
3. Profile metadata transfer needs its own narrowly scoped authorization. Current
   download-only handoff grants must not gain write authority. Bind any new import
   authorization to the account, origin, workstation/request and bounded operation;
   require explicit approval, expiry/replay controls and revocation. No remote
   command definitions, general filesystem service or broad LAN listener.
4. Plate recipes retain exact artifact revision IDs/hashes, instance transforms,
   preset snapshot/version and algorithm version. Profile refresh or new model
   revisions never silently rewrite an existing recipe. Define missing-source,
   Trash, archive, export and recovery behavior before schema implementation.
5. Manufacturing geometry must not be derived from flattened preview geometry.
   Keep computation isolated, cancellable and budgeted without lowering library
   upload limits. Preserve original STL bytes; validate units/scale before arranging.
   A packing failure is not mathematical proof that no possible arrangement exists.
6. Generated 3MF contains unsliced geometry and placement, never stale prepared
   G-code or inherited print-time/compatibility claims. A layout check is not print
   safety certification. Slicers retain responsibility for machine-specific processing.
7. Prove object count, dimensions, transforms, individual editability and printer
   selection in actual slicer versions. A valid ZIP/XML file is insufficient.
   Keep all old protocols and role/extension restrictions through the transition.

## Gates and required truth

| Gate | Scope / exit evidence | State |
|---|---|---|
| UP-1 | Shared transfer progress plus accessible UI; truthful finalizing/error states, nested folders/Project membership, mixed file sizes, empty files, unknown progress and session failure. Unit/type/build plus browser transport/workflow checks | VERIFIED locally — [84 tests and three-engine results](evidence/gate-13/UPLOAD_PROGRESS_RESULTS.md); awaiting owner acceptance |
| MP-0 | Final preset/recipe/import contracts, authority and migration/recovery decisions; existing manual-installer parity/macOS pairing repairs with failing-old-source regressions; fixture inventories for named slicer versions | READY after UP-1 review |
| MP-1 | Bambu preset discovery/import/explicit refresh, inheritance/geometry/secret filtering and authorization negative controls; saved snapshots usable without relay. Then Orca and Prusa conformance recorded independently | NOT STARTED |
| MP-2 | STL instances, saved recipe lifecycle, deterministic conservative packing/manual editing, source preservation, boundary/height checks, cancellation and memory/time limits, tablet interaction | NOT STARTED |
| MP-3 | Editable unsliced 3MF, scoped generated-artifact handoff and actual Bambu/Orca/Prusa round trips; no stale prepared data, silent scale changes or shell/default-opener fallback | NOT STARTED |
| MP-4 | Migration/export/backup/restore/rollback, auth/audit/abuse checks, matched web/API/bridge evidence and updated release limitations; rejoin Gate 13C | NOT STARTED |

Each completed slice records exact source/build, commands, expected/actual results,
failed attempts and remaining owner input, then returns to the governing runbook's
re-cock protocol. New gate numbers do not reset or falsely close Gates 0–13.

## Verification and release posture

The prior exact-image E4/R57/F26/H0 security event remains historical evidence for
its named images only, under unchanged C1–C7/deadline. Source/transport/bridge changes
require fresh relevant checks; new images/candidates do not inherit waivers.
The old platform/security checkers intentionally enforce unchanged inputs and may
no longer qualify a changed worktree. Do not weaken them or rewrite old pass records.

Keep API/schema unchanged during UP-1. Before later additive migrations, document
the complete portable/raw-recovery behavior and review the contract. No live-vault
experiments or desktop-handler changes without scoped device permission. Physical
YubiKey and Windows/Bambu checks remain unperformed; macOS/Linux runtime evidence
or explicit owner support decisions remain necessary. Gate 12's desktop deferral
and G13-01's performance deferral are unchanged. The frozen Gate 5 candidate stays
at `f6ff55b`; all commits remain local and publication requires separate approval.

## References and known format constraints

- [Existing local adapter contract](adr/0012-versioned-local-application-adapters.md).
- [Platform findings and Windows prerequisites](evidence/gate-13/PLATFORM_OPERATOR_RESULTS.md).
- [Orca profile documentation](https://github.com/OrcaSlicer/OrcaSlicer/wiki/how_to_create_profiles)
  describes inherited printer variants; qualification must pin actual fixture versions.
- [3MF core specification](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md)
  defines object/build transforms and permits consumers to rearrange build items;
  actual slicer placement preservation remains an explicit gate.
