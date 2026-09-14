# Make Plate fixture inventory — MP-0

**2026-09-12.** Inventory/design input, not parser or slicer-runtime qualification.
No vendor configuration has been copied into the repository or read from the
owner's workstation. Use these immutable source revisions when preparing MP-1
fixtures; record raw file hashes/licensing with any later retained vendor copy.
Author minimal synthetic fixtures separately and label them synthetic.

**MP-1a update:** [Authored fixtures](../../../slicer-bridge/internal/printerpreset/testdata/README.md)
and pure projection tests now exist; see [results](MAKE_PLATE_MP1A_RESULTS.md).
The original public-source inventory below remains separate from this synthetic
test evidence. No real workstation/vendor file is represented as tested input.

**MP-1b-1 update:** [Linux file-boundary results](MAKE_PLATE_MP1B1_RESULTS.md)
add generated temporary filesystem fixtures and a same-device container bind
fixture. Windows/macOS readers, hard-timeout supervision and actual known-root/
manifest discovery remain unimplemented. This does not qualify native profiles.

**MP-1b-2 update:** [Windows implementation/worker evidence](MAKE_PLATE_MP1B2_RESULTS.md)
adds pure Windows syntax/fold checks and Linux subprocess timeout, cancellation,
framing, redaction and partial-failure fixtures. Five authored Windows native tests
compile but have not run. macOS, actual discovery and native lifecycle checks remain
pending; no owner Bambu version is qualified by these synthetic cases.

**Native Mac update:** [Scoped execution at `79ac9a0`](MAKE_PLATE_MAC_NATIVE_RESULTS.md)
passes 34 unit tests and four seeded fuzz targets on the owner's Intel macOS
15.7.9 / 24G830 asset. This adds ordinary worker/pipe timeout/cancel/reaping evidence
and an explicit unsupported-reader regression, not a macOS filesystem pass.
Two successful-reader tests were deliberately unrun; no real profiles were read,
applications installed or OpenClaw changed. Disposable fixtures were removed.

**Mac reader experiment update:** [Native results at `907cddd`](MAKE_PLATE_MAC_READER_RESULTS.md)
add authored APFS fixture reads, held-root/source-preservation, permissions,
symlink replacement, and successful experimental worker round trips. 34 default
and 42 ordinary experimental unit checks plus eight seeded fuzz targets pass.
Two additional FIFO counterexamples reproduce **failed pre-open safety properties**;
they are not security passes. Normal builds still refuse Mac preset reads.
No device/mount/recall, real profile, Apple Silicon or native race qualification.
Four owned remote fixture directories were removed; retained local evidence includes
three failed native attempts. MP-1b remains open for a safe macOS boundary and discovery.

**Subsequent owner decision:** [New Mac-local preset discovery/import/refresh is
deferred from v5.1](MAKE_PLATE_MACOS_DEFERRAL.md). Retain the failed Mac safety
properties as future re-entry requirements, not current release qualification.
Windows/Linux discovery and native Windows/lifecycle checks remain required;
existing Mac file-open and planned browser Make Plate scope are unchanged.

## Named public source targets reviewed

**MP-1b-3 update:** [Manifest-index results](MAKE_PLATE_MP1B3_RESULTS.md) add synthetic
vendor manifests, strict projection/selection, bounded private-worker round trips
and link/special-file failures. 90 unit tests/race and five fuzz smokes pass on Linux;
Windows manifest tests compile only. Manifest entries can be templates, so this does
not yet qualify selectable-machine discovery, root/account selection, application
version detection or real profiles. Bundle and installed-app versions stay separate.

**MP-1b-4 update:** [Location results](MAKE_PLATE_MP1B4_RESULTS.md) add synthetic
data-root layouts, explicit-account/no-fallback checks, shared entry accounting and
a same-device directory-bind negative control. 104 unit tests/race and six fuzz
smokes pass on Linux; native Windows remains untested. Actual profile identity/
inheritance discovery, local selector UI and installed versions are still pending.

**MP-1b-5 update:** [Content results](MAKE_PLATE_MP1B5_RESULTS.md) add authored
manifest/document name mismatch, exact parent closure, script/FIFO non-read,
case-aliased header, shared aggregate/index budget and worker selection fixtures.
123 unit tests/race and seven fuzz smokes pass. Explicit-machine user fixtures
prove namespaces only: ordinary saved-user JSON lacking system headers remains
unsupported and has a negative control. See the [pinned writer/source distinction](../../../slicer-bridge/internal/presetfiles/DISCOVERY.md).
No real vendor bundle or installed-device fixture is qualified by these tests.

| Target | Pinned public source | Required fixture coverage / observed shape |
|---|---|---|
| Bambu Studio 2.8.2.61 | [Release](https://github.com/bambulab/BambuStudio/releases/tag/v02.08.02.61), commit `926a7192574bcb9b3a732e1ec59a46d79cb45466` | P1S 0.4 child → `fdm_bbl_3dp_001_common` → `fdm_machine_common`; string-valued scalar/array numbers, inherited geometry and child exclusion override; G-code `include` references must not be followed |
| OrcaSlicer 2.4.2 | [Release](https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2), commit `8500fcdccaa10b5099ac20d252af3a7c560046f1` | Independently resolve its P1S 0.4 child/common/root chain; do not reuse Bambu normalized output as proof |
| PrusaSlicer 2.9.6 | [Release](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6), commit `b028299c770b8380ee81c921a2867d522f288123` | Bundled `PrusaResearch.ini`, observed config version 2.4.14; sections, hidden parent presets and semicolon-separated multiple inheritance; separate user preset handling |
| Owner's Windows Dell tablet | **Owner-reported `v2.8.0.6`** on 2026-09-12 | Exact full build/profile-bundle identity and CPU/OS/browser remain unobserved. Do not map this automatically to 2.8.2.61 or guess that it is a beta |

Bambu's [P1S child](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/Bambu%20Lab%20P1S%200.4%20nozzle.json)
selects a 0.4 mm nozzle and exclusion rectangle from (0,0) to (18,28).
Its [common parent](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/fdm_bbl_3dp_001_common.json)
supplies the 256×256 XY bed; the
[root](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/fdm_machine_common.json)
supplies 250 mm height. These are source-derived fixture expectations, **not** a
claim about the owner's selected printer or the hardware's advertised envelope.

Orca's corresponding
[child](https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/8500fcdccaa10b5099ac20d252af3a7c560046f1/resources/profiles/BBL/machine/Bambu%20Lab%20P1S%200.4%20nozzle.json),
[common](https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/8500fcdccaa10b5099ac20d252af3a7c560046f1/resources/profiles/BBL/machine/fdm_bbl_3dp_001_common.json)
and [root](https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/8500fcdccaa10b5099ac20d252af3a7c560046f1/resources/profiles/BBL/machine/fdm_machine_common.json)
provide the separate chain to test. Never treat unmodeled extrusion/process
settings in either vendor's raw file as part of the normalized payload.

Prusa's [bundled profile source](https://raw.githubusercontent.com/prusa3d/PrusaSlicer/b028299c770b8380ee81c921a2867d522f288123/resources/profiles/PrusaResearch.ini)
contains `bed_shape`, `max_print_height`, nozzle variants and multiple-parent MK4S
presets. Full precedence/resolution is **not tested**; no final normalized MK4S
snapshot is asserted here. Mutable profile updates can differ from bundled files,
so an installed slicer version alone will not identify its actual preset data.

The public pages/raw tag sources above were inspected with browsing; commit identities
were resolved from each release's commit link. GitHub API tag-ref URLs were unavailable
through the browser tool and were not retried. These are source-review citations,
not a durable byte-hashed capture or proof of an installed binary's contents.

## Required authored fixtures before MP-1 closes

| ID | Cases | Required result | Current state |
|---|---|---|---|
| PF01 | Bambu child/inherited bed/height, variant nozzle, user override | Exact allowed normalized fields and field provenance, no raw settings | MP-1a synthetic projection passes; persisted user overrides and installed profiles pending |
| PF02 | Orca equivalents, changed/missing/renamed parent | Independent expected values or explicit unsupported state | PLANNED |
| PF03 | Prusa INI/multiple parents/hidden sections/user preset | Prove actual precedence; do not select hidden template as a user printer | PLANNED |
| PF04 | Centered/circular/concave beds, holes/exclusions, degenerate polygon | Preserve coordinate transform; no rectangle substitution or guessed geometry | MP-1a simple polygon/rectangle projections pass; solver/other adapter cases pending |
| PF05 | NaN/infinity/overflow, missing nozzle/height, unsupported multi-tool/belt/resin | Reject or mark incomplete; never silently choose a different machine | MP-1a synthetic rejection/completeness cases pass |
| PF06 | Cycles, ambiguous IDs, deep/large input, traversal, symlink/reparse escape, include URL | Bounded error/cancellation without external read or network request | Pure/Linux file controls plus self-worker timeout/cancel/overflow checks pass. Windows implemented/compiled, not native-tested; Windows/Linux discovery and lifecycle/startup pending. Mac-local preset import owner-deferred from v5.1, not qualified |
| PF07 | Fake credentials, private paths, scripts, unknown wire fields | Local reader drops nonallowlisted settings; server rejects extra fields; logs stay redacted | Projection and private worker filtering/framing/redacted errors pass; private IPC is not consent or the pending server wire/auth validator |
| PF08 | Claim/replay/race/expiry/revocation/wrong principal, idempotent retry | No unauthorized staging or persistent mutation | PLANNED |
| PF09 | Refresh while recipe pinned, override conflict, concurrent commit | Old snapshot unchanged; review/version conflict explicit | PLANNED |
| PF10 | Portable v1/v2 and raw upgrade/restore/rollback, corrupt snapshot/FK/tombstone | Whole logical graph preserved or fail closed; pending authority invalidated | PLANNED |

MP-2/MP-3 add original STL fixtures, golden instance transforms, invalid/missing
source controls, separate object/dimension/placement checks in each named slicer,
and the owner's actual Bambu version. No slicing or physical printing is required.
Use [ADR 0020](../../adr/0020-printer-presets-and-plate-recipes.md) for the accepted
contracts and the [tablet checklist](WINDOWS_TABLET_CHECKLIST.md) for device consent.
