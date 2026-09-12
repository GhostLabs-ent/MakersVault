# Make Plate fixture inventory — MP-0

**2026-09-12.** Inventory/design input, not parser or slicer-runtime qualification.
No vendor configuration has been copied into the repository or read from the
owner's workstation. Use these immutable source revisions when preparing MP-1
fixtures; record raw file hashes/licensing with any later retained vendor copy.
Author minimal synthetic fixtures separately and label them synthetic.

## Named public source targets reviewed

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
| PF01 | Bambu child/inherited bed/height, variant nozzle, user override | Exact allowed normalized fields and field provenance, no raw settings | PLANNED |
| PF02 | Orca equivalents, changed/missing/renamed parent | Independent expected values or explicit unsupported state | PLANNED |
| PF03 | Prusa INI/multiple parents/hidden sections/user preset | Prove actual precedence; do not select hidden template as a user printer | PLANNED |
| PF04 | Centered/circular/concave beds, holes/exclusions, degenerate polygon | Preserve coordinate transform; no rectangle substitution or guessed geometry | PLANNED |
| PF05 | NaN/infinity/overflow, missing nozzle/height, unsupported multi-tool/belt/resin | Reject or mark incomplete; never silently choose a different machine | PLANNED |
| PF06 | Cycles, ambiguous IDs, deep/large input, traversal, symlink/reparse escape, include URL | Bounded error/cancellation without external read or network request | PLANNED |
| PF07 | Fake credentials, private paths, scripts, unknown wire fields | Local reader drops nonallowlisted settings; server rejects extra fields; logs stay redacted | PLANNED |
| PF08 | Claim/replay/race/expiry/revocation/wrong principal, idempotent retry | No unauthorized staging or persistent mutation | PLANNED |
| PF09 | Refresh while recipe pinned, override conflict, concurrent commit | Old snapshot unchanged; review/version conflict explicit | PLANNED |
| PF10 | Portable v1/v2 and raw upgrade/restore/rollback, corrupt snapshot/FK/tombstone | Whole logical graph preserved or fail closed; pending authority invalidated | PLANNED |

MP-2/MP-3 add original STL fixtures, golden instance transforms, invalid/missing
source controls, separate object/dimension/placement checks in each named slicer,
and the owner's actual Bambu version. No slicing or physical printing is required.
Use [ADR 0020](../../adr/0020-printer-presets-and-plate-recipes.md) for the proposed
contracts and the [tablet checklist](WINDOWS_TABLET_CHECKLIST.md) for device consent.
