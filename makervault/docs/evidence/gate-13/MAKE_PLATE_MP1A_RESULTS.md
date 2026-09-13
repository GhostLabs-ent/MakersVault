# MP-1a — bounded Bambu projection core

**2026-09-12 America/New_York (capture timestamps use September 13 UTC).**
MP-0/ADR 0020 owner-accepted; MP-1a locally verified. **MP-1 remains open.**
Entry `3ae0199`; implementation `a88de9263b5e1c6c81f4638eb4c307aea1aa77aa`.

## Delivered boundary

New internal Go package [`printerpreset`](../../../slicer-bridge/internal/printerpreset/README.md)
consumes already-supplied Bambu-shaped JSON documents and produces bounded typed
review candidates. It does not scan folders, open paths from profiles, connect to
MakersVault, launch commands or save data. The bridge executable does **not** call
this package yet. There is no new CLI/protocol action or end-user import workflow.

The projection handles exact-name inheritance, child overrides, field provenance,
normalized bed coordinates, simple nonrectangular beds, Bambu exclusion rectangles,
height and one nozzle/tool. Unknown exclusions remain null, not an invented empty
list. Incomplete geometry carries fixed reason codes and cannot claim completeness.
Unknown source schema markers, duplicate/ambiguous identities, malformed/deep JSON,
cycles and scan-budget failures fail closed. A failed input invalidates the catalog;
it cannot silently resolve a truncated scan.

Only allowlisted scalar/flat fields survive parsing. Credentials, account data,
scripts, paths, URLs and arbitrary notes are not copied from their vendor settings
fields into the projection. The source namespace stays local. User-authored labels
can contain private text; the future consent screen must still show all shared data.
Recognized G-code-template include names are ignored without any file/URL lookup;
other include shapes fail. Unsupported tool-specific/wrapping geometry is explicit.

The deterministic projection fingerprint excludes discarded fields and changes
when normalized geometry changes. It is not an authenticated server snapshot or a
cross-language wire-validation proof. API decoding/canonical golden fixtures remain
part of the persistence/import slice.

## Verification at exact committed source

| Check | Actual result | Limit |
|---|---|---|
| Full Go race suite | **47 unit tests**: 29 existing bridge + 18 new parser tests; plus seeded fuzz target. 48 top-level test/fuzz pass events / 102 inclusive pass events, no fail/skip | Linux/amd64, Go 1.26.6; not whole-app verification |
| Static checks | `go vet ./...` passes; Go sources formatted | No third-party parser dependency introduced |
| Cross-build | Bridge and parser test binary compile for Linux/Windows/macOS, each amd64/arm64 | Six target combinations, twelve artifacts; no native Windows/macOS execution |
| Bounded fuzz | Pass: 189,429 executions, 2 workers; requested 5-second fuzz budget, final elapsed output 6 seconds | Short smoke, not exhaustive proof or a production performance benchmark |
| Source boundary | Clean verification source before/after at `a88de92` | API/web/schema/dependencies and production bridge entry points unchanged |

Authored fixtures cover child-before-parent ordering, inherited 256×256 XY / 250 mm
height, 0.4 nozzle, child exclusion override, multiple exclusion rectangles, fake
credential filtering and repeated single-tool IDs. Generated cases cover centered,
concave and eight-vertex circular-approximation beds; closing-point handling;
nonfinite/degenerate/self-crossing geometry; malformed exclusions; unsupported
nozzles/tools/technology; user/system namespace isolation; missing/cyclic/deep
parents; JSON/resource boundaries; cancellation and redacted read errors.

File-count/aggregate-byte boundary tests seed counters near the limits; they do not
claim a 10,000-profile stress run. One over-8-MiB input exercises the actual per-file
read bound. Cancellation is cooperative between Reader calls/tokens and cannot
interrupt a blocked arbitrary Reader. No symlink, reparse-point, mount, device-file
or native filesystem protection has been implemented or qualified by this slice.

The [named-source inventory](MAKE_PLATE_FIXTURES.md) remains the provenance reference.
Public Bambu P1S/common/root files were re-inspected at the pinned commit, and the
[same revision's Print.cpp](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Print.cpp)
confirms four-vertex exclusion grouping. Repository fixtures are minimal original
synthetic documents, **not** captured vendor or workstation files. No installed
Bambu version, especially the owner's reported `v2.8.0.6`, is qualified here.

## Durable captures and reproduction

Private root `/home/vinnyc/.local/state/makersvault/verification/`:

- `containment-mp1a-parser-preflight`: exit 0 on dirty new-package source at entry
  `3ae0199`, before the final schema-marker/auxiliary-geometry guards.
- `containment-mp1a-parser-final`: exit 0 on clean `a88de92`; race JSON events,
  cross-build records and fuzz summary. Exact command, source status and SHA-256
  stdout/stderr recorded in `result.json` and the [evidence index](make-plate-parser-verification.json).

No executed test attempt failed. A direct nested command was rejected before
execution by the wrapper interpreting a Go flag as an inline Node flag; the
file-based [container driver](make-plate-parser-check.sh) avoids inline execution.
No restriction was disabled. Public source inspection is cited, not represented
as a durable byte-hashed vendor capture.

All checks use pinned Go image
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`,
network disabled, source mounted read-only except the explicit formatting step.
Fuzzing uses a generated container-only source copy; a failure corpus would be
retained in the fresh private evidence directory. No failure corpus was produced.
Generated binaries/fuzz copy were discarded with the disposable container; no
host or tablet handlers/configuration or live-vault data were changed.

For reproduction, use the capture's exact Docker command and named source. The
driver takes either `preflight` or the exact implementation revision. Full mode
requires `/evidence` to be a **new private output directory** for failure retention;
do not run this driver in a user's home or substitute a source label for actual code.

## Re-cock

Next **MP-1b** supplies a safe workstation reader/selection boundary: approved local
roots, version observations, traversal/symlink/reparse/mount/special-file rejection,
cancellable I/O and native-path fixtures. `os.Root` alone is not that whole contract:
its local Go documentation explicitly permits filesystem-boundary traversal and
special-file access. No local folders were scanned to work around missing device data.

Then MP-1c implements scoped import and persistent presets with the additive
migration and portable/raw recovery counterpart together. MP-1d proves the complete
workflow and named slicer versions; Orca/Prusa remain independently unimplemented.
MP-2/MP-3 plate planning/export is still undelivered. Current upload limits and
the no-manual-thumbnail/no-slicing/no-control boundaries remain unchanged.

No API/web/lifecycle suite or advisory scan was rerun, and no runtime image was
rebuilt. Historical exact-image security dispositions/conditions/deadline remain
unchanged and do not qualify this future integration. Gate 13C/13D, real-device
checks and release acceptance stay open. CNC/CAM, Gate 12 and G13-01 tuning remain
deferred. All commits are local; no push, publication or live/device deployment.
