# Upload progress and Make Plate — release-scope amendment

**Decision date:** 2026-09-12. **Entry:** `4858147` (schema 17).
**Status:** MP-0 and [ADR 0020](adr/0020-printer-presets-and-plate-recipes.md) accepted
2026-09-12. MP-1 is in progress: Bambu projection, Linux file access and the
single-use supervisor, Bambu manifest index, anchored location inspection and
explicit-machine content discovery, bounded saved-user machine projection and
local account choices/native location hints are
locally verified. Native selection/version/profile and Windows qualification remain open.
MP-1b remains open and inactive in production.
An owner-provided Intel Mac passes 34 default and 42 ordinary experimental unit
checks; two additional counterexamples reproduce failed pre-open safety properties.
The macOS reader experiment is explicitly build-tagged and **excluded from normal
builds**, which still refuse preset reads. An OS-enforced boundary remains unresolved.
End-user preset discovery/import and Make Plate are not implemented.
The owner approved [MS-1's bounded feasibility assessment](MAKE_PLATE_MACOS_SAFETY_PROPOSAL.md),
now [completed NO-GO](evidence/gate-13/MAKE_PLATE_MACOS_MS1_RESULTS.md): no supported
pre-open enforcement mapping was established for the candidate. MS-2 did not open.
The owner [approved deferring only new Mac preset import for v5.1](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md).
Existing Mac file-open support stays unchanged. No native packaging or activation
is approved; next MP-1b work is Windows/Linux Bambu discovery and native qualification.

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
  New macOS workstation preset discovery/import/refresh is deferred from v5.1 by
  the owner's September 13 decision; Windows/Linux remain in this release scope.
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

**Deferred:** new macOS workstation preset discovery/import/refresh; CNC/CAM
integration and CNC-specific adapters; full 3MF/STEP input
conversion for plate generation; resin workflows; background profile synchronization;
advanced nesting, automatic orientation/supports, multi-plate splitting, material
grouping, direct printer discovery/status/control, queues, USB/serial integration.
Existing file-open adapters and descriptive CNC machine records are not removed.
No server-side slicing, G-code generation, printing or manual-thumbnail requirement.

If a supported slicer needs more work than its gate permits, report the evidence
and ask the owner to trim support rather than silently promising or removing it.

### Platform scope after the Mac-import deferral

This is the approved feature scope, **not a matrix of completed qualification**.

| Workflow | Windows/Linux | macOS |
|---|---|---|
| New workstation-local preset discovery/import/refresh | In scope; incomplete/inactive pending MP-1 | Deferred from v5.1; default reader refuses requests |
| Existing model-file handoff/protocols | Unchanged; remaining native checks apply | Unchanged; actual app/signing/distribution checks still apply |
| Planned browser use of stored presets, plate editing and recipes | In scope; not delivered | In scope; not delivered; no local profile scan implied |
| Planned editable 3MF export and selected-slicer handoff | In scope; MP-3 proof required | In scope; MP-3/native proof required; import deferral does not qualify it |

The deferral applies to the **bridge workstation**, not the browser or Docker host.
Future capability/error handling must explain the unavailable local import action
without hiding unrelated Mac browser workflows or offering an unsafe fallback.
No new manual preset or image-upload requirement is introduced. Re-entry into Mac
import requires the [accepted decision's safety/qualification checkpoints](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md).

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
| UP-1 | Shared transfer progress plus accessible UI; truthful finalizing/error states, nested folders/Project membership, mixed file sizes, empty files, unknown progress and session failure. Unit/type/build plus browser transport/workflow checks | VERIFIED — [84 tests and three-engine results](evidence/gate-13/UPLOAD_PROGRESS_RESULTS.md); owner directed continuation on 2026-09-12 |
| MP-0 | Final preset/recipe/import contracts, authority and migration/recovery decisions; existing manual-installer parity/macOS pairing repairs with failing-old-source regressions; fixture inventories for named slicer versions | ACCEPTED 2026-09-12 — [contracts/29 bridge tests/six cross-builds](evidence/gate-13/MAKE_PLATE_MP0_RESULTS.md); native device checks remain open |
| MP-1 | Windows/Linux Bambu preset discovery/import/explicit refresh, inheritance/geometry/secret filtering and authorization negative controls; saved snapshots usable without relay. Then Orca and Prusa conformance recorded independently | IN PROGRESS — Mac-local import deferred by owner; Windows/Linux discovery/consent, native Windows/lifecycle and persistence/recovery remain open; browser planning scope unchanged |
| MP-2 | STL instances, saved recipe lifecycle, deterministic conservative packing/manual editing, source preservation, boundary/height checks, cancellation and memory/time limits, tablet interaction | NOT STARTED |
| MP-3 | Editable unsliced 3MF, scoped generated-artifact handoff and actual Bambu/Orca/Prusa round trips; no stale prepared data, silent scale changes or shell/default-opener fallback | NOT STARTED |
| MP-4 | Migration/export/backup/restore/rollback, auth/audit/abuse checks, matched web/API/bridge evidence and updated release limitations; rejoin Gate 13C | NOT STARTED |

Each completed slice records exact source/build, commands, expected/actual results,
failed attempts and remaining owner input, then returns to the governing runbook's
re-cock protocol. New gate numbers do not reset or falsely close Gates 0–13.

### MP-1 execution slices

- **MP-1a:** Pure, bounded Bambu document projection, authored fixtures, normalization,
  redacted failures and parser fuzzing. No filesystem/network/CLI activation or DB
  change. [VERIFIED at `a88de92`](evidence/gate-13/MAKE_PLATE_MP1A_RESULTS.md): 47 bridge/parser
  unit tests, seeded/short fuzz run, vet and six-target cross-builds pass. Source-format
  evidence is separate from actual installed-profile support.
- **MP-1b:** Bounded workstation source discovery and explicit local selection;
  known-root/version observations, symlink/reparse/mount/special-file controls,
  cancellable I/O and native path fixtures. Do not treat download-origin trust as
  consent to share metadata, and do not enable incomplete remote import flows.
  First [MP-1b-1 slice at `8a9b424`](evidence/gate-13/MAKE_PLATE_MP1B1_RESULTS.md)
  verifies Linux held-handle listing/loading, including unprivileged permissions,
  same-device bind rejection and race controls; 68 unit tests/race, vet, six target
  builds and two short fuzz runs pass. Subsequent [MP-1b-2 at `60bd90c`](evidence/gate-13/MAKE_PLATE_MP1B2_RESULTS.md)
  implements the Windows NTFS reader and isolated self-worker. 80 unit tests/race,
  six target builds and four short fuzz runs pass on Linux; Windows native reader
  tests are only compiled. **MP-1b is not complete:** native Windows/lifecycle
  qualification, matched consented Windows/Linux worker integration, known
  locations/manifest discovery, local selection and version observations remain.
  Bambu discovery and native qualification remain pending; no CLI activation.
  Mac-local import is explicitly deferred by the later owner decision below, not
  qualified by its historical experiment. Existing Mac file-open support stays in scope.
  The owner subsequently supplied a Mac for scoped tests. [Native results at
  `79ac9a0`](evidence/gate-13/MAKE_PLATE_MAC_NATIVE_RESULTS.md) record macOS 15.7.9
  (24G830), x86_64: 34 unit tests plus four seeded fuzz targets pass without a
  toolchain/app install. Ordinary worker timeout/cancel/reaping and unsupported
  reader responses are verified; the two successful-file-reader tests are explicitly
  unrun. No native race detector, Apple Silicon, filesystem or slicer qualification.
  Test files were removed and OpenClaw was untouched.
  The subsequent owner-authorized [Mac reader experiment at `907cddd`](evidence/gate-13/MAKE_PLATE_MAC_READER_RESULTS.md)
  passes 34 default and 42 ordinary experimental checks, including both successful
  worker reader tests in the experimental variant, plus eight seeded fuzz targets.
  Two additional counterexamples reproduce failed special-file pre-open properties;
  post-open APFS checks also do not establish mount/recall prevention. The experiment
  is build-tagged, not release-qualified; the default reader remains unsupported.
  Three failed native attempts are retained; four temporary remote fixture directories
  were removed, SSH closed and OpenClaw left untouched. Next review an OS-enforced
  macOS boundary before enabling it; any material contract/support change needs an
  explicit owner decision. This neither closes MP-1b nor changes existing Mac file-open
  support. Native Windows, real profiles and matched consented integration remain open.
  The owner subsequently authorizes preparation of the
  [macOS safety proposal](MAKE_PLATE_MACOS_SAFETY_PROPOSAL.md). It recommends **MS-1
  only**, one supported-API/embedded-reader feasibility pass with explicit stop
  conditions. MS-2 native proof and MS-3 integration require separate checkpoints;
  no custom-SBPL shipping dependency, toolchain installation or automatic deferral.
  The owner subsequently approves MS-1. Its [NO-GO assessment](evidence/gate-13/MAKE_PLATE_MACOS_MS1_RESULTS.md)
  identifies missing supported special-file/mount/recall enforcement and unresolved
  XPC lifecycle equivalence. The approved early-stop rule applies; MS-2 did not open.
  The owner then [accepts the new-Mac-preset-import-only deferral](evidence/gate-13/MAKE_PLATE_MACOS_DEFERRAL.md)
  for v5.1. Existing Mac file-open and planned browser Make Plate workflows remain
  in scope; further Mac reader research needs separate direction. Native code, SDKs
  and the owner's Mac were not changed. The subsequent [MP-1b-3 manifest substep
  at `a9a44ca`](evidence/gate-13/MAKE_PLATE_MP1B3_RESULTS.md) reads only fixed BBL.json,
  returns a bounded local index and maps explicit exact identities to basenames.
  It never follows references or confuses bundle version with application version;
  template entries are not asserted to be selectable printers. 90 unit tests/race,
  vet, six target builds and five fuzz smokes pass on Linux; one interrupted outer
  capture is retained separately. Next: adapter-owned root planning/local root and
  account selection, manifest-to-document identity and parent closure, independent
  app-version observations and native Windows/lifecycle qualification. Keep
  production scans inactive; no installed profiles or user-facing discovery qualified.
  Subsequent [MP-1b-4 at `123e0ba`](evidence/gate-13/MAKE_PLATE_MP1B4_RESULTS.md) adds
  unobserved known-location plans and held-parent inspection of one explicit data
  root/account. Manifest and user filename indexes share a deadline/entry budget;
  no account or app version is guessed. 104 unit tests/race, vet, six target builds
  and six fuzz smokes pass; Windows is compiled only. Next bind actual profile
  identities/parent closure and instantiation. Native hint acquisition, account
  enumeration/local selector, independent versions, native Windows/lifecycle and
  matched consented integration remain open. Production main stays unchanged.
  Subsequent [MP-1b-5 at `535a0a1`](evidence/gate-13/MAKE_PLATE_MP1B5_RESULTS.md)
  binds actual manifest/document identities, validates exact parent chains and
  offers only explicit instantiation under one held root/shared file-byte-time
  budget. Script entries are excluded before open; selected geometry is freshly
  projected or explicitly incomplete. 123 unit tests/race, vet, six target builds
  and seven fuzz smokes pass. **Next MP-1b-6: ordinary saved-user machine JSON**,
  whose writer does not guarantee system-style type/instantiation headers; these
  shapes remain unsupported, not guessed. Local selector/native hints, independent
  versions/real profiles, native Windows/lifecycle and consented activation stay open.
  Subsequent [MP-1b-6 at `ff310d7`](evidence/gate-13/MAKE_PLATE_MP1B6_RESULTS.md)
  adds saved-user machine-folder projection with required user/version headers,
  explicit hidden-state handling and no generic/system schema relaxation. The
  same new public-API test reproduces old `535a0a1` rejection, then passes; 136
  unit tests/race, vet, six target builds and eight fuzz smokes pass. App version
  remains unobserved; nested custom bases/version suffixes and real profiles are
  not qualified. **Next MP-1b-7: bounded account-choice enumeration/native hints**,
  keeping names local and no automatic/default account choice or production dispatch.
  Local picker/consent, independent versions and native Windows/lifecycle stay open.
  Subsequent [MP-1b-7 at `9a72c91`](evidence/gate-13/MAKE_PLATE_MP1B7_RESULTS.md)
  adds bounded metadata-only local account choices and unobserved native hints,
  without account selection or worker environment expansion. 152 unit tests/race,
  vet, six target builds and nine fuzz smokes pass; native Windows is compiled only.
  Hint lookup is not yet hard-deadline isolated. **Next MP-1b-8: local root/account
  picker and consent-session foundation**, including bounded hint lifecycle before
  activation. Native Windows/real profiles, independent versions and matched main
  remain open; no production scan or import is enabled.
- **MP-1c:** Scoped claim/review/commit authority plus immutable preset storage and
  its additive migration, portable v1/v2 and raw-recovery counterparts as one coherent
  persistence slice. Shared strict wire fixtures must prove API/bridge parity.
- **MP-1d:** End-to-end browser/bridge/Bambu import/refresh, offline saved presets,
  privacy/role/revocation controls and actual version-specific application evidence.
  Orca and Prusa coverage remains independently required or explicitly re-scoped
  by the owner; a Bambu parser pass does not silently qualify the other adapters.

These slices sequence the accepted scope; they do not close MP-1 early or defer
its data-recovery requirements to MP-4.

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
- [Accepted preset/recipe/import contract](adr/0020-printer-presets-and-plate-recipes.md).
- [Named-source fixture inventory and owner Bambu version](evidence/gate-13/MAKE_PLATE_FIXTURES.md).
- [Platform findings and Windows prerequisites](evidence/gate-13/PLATFORM_OPERATOR_RESULTS.md).
- [Orca profile documentation](https://github.com/OrcaSlicer/OrcaSlicer/wiki/how_to_create_profiles)
  describes inherited printer variants; qualification must pin actual fixture versions.
- [3MF core specification](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md)
  defines object/build transforms and permits consumers to rearrange build items;
  actual slicer placement preservation remains an explicit gate.
