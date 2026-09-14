# MP-1b-3 — bounded Bambu manifest index

**2026-09-13 America/New_York (captures September 14 UTC).** Owner directed
continuation after the limited Mac-import deferral. Entry
`f1cbb237b481068f545d70bbb6981761edbd14b3`; implementation
`a9a44cabcb9e68959d03e22dd641d36ff6b1daee`. **Manifest substep locally verified;
MP-1b/MP-1 and native Windows qualification remain open.**

## Delivered and deliberately inactive

The [reader](../../../slicer-bridge/internal/presetfiles/manifest.go) opens only
`BBL.json` beneath an explicitly selected local root, through the existing held-handle
boundary. Its pure parser retains only bundle version and exact machine-list
identity/basename pairs. Model/filament/process lists, URLs and unknown configuration
are discarded. No referenced document, user directory or URL is visited.

Explicit identity-to-file selection is ordered and all-or-nothing, without guessing
filenames, selecting everything or inferring parent closure. This is a **local index,
not a list of selectable printers**. The future adapter must bind actual document
names to the manifest, resolve exact parents without script includes and establish
instantiation before offering presets. Template entries are not printer claims.

The private worker gains `manifest`; its parent validates the index and rejects
mixed-operation data, invalid names/paths, duplicates, partial failures and oversized
output. Only test executables dispatch the worker. No production UI, root discovery,
installed-version probe, consent or import authority is enabled. Default Mac builds
still refuse reads; new Mac-local preset import remains owner-deferred.

### Source review is not installed-device evidence

Bambu's pinned [BBL manifest](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL.json)
declares bundle `02.08.00.05` and separate machine/model/filament/process lists. Its
machine list also contains templates; this [script template](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/machine/Bambu%20Lab%20A1%200.4%20nozzle%20template%20machine_start_gcode.json)
is non-instantiated. Primary sources were reviewed, not copied into fixtures or
represented as byte-hashed vendor qualification. Tests use original synthetic data.
Bundle version is **not** an application version; the owner's reported Bambu Studio
`v2.8.0.6` remains independently untested.

## Exact-source verification

- Linux/amd64 unprivileged race suite: **90 unit tests**, five seeded fuzz targets;
  **95 top-level / 199 inclusive pass events**, zero failure/skip.
- Existing permission, same-device bind, replacement, worker timeout/cancellation
  and redaction checks pass. New cases cover secret filtering, malformed/duplicate/
  case-alias JSON, vendor/schema rejection, unsafe paths, exact selection, resource
  limits, missing/oversized files, symlink/hardlink/FIFO refusal, source preservation,
  mixed responses and the 2-MiB worker output ceiling.
- `go vet ./...` and six platform/architecture combinations pass: bridge plus three
  package test binaries each, **24 builds**. Windows/macOS are compiled, not run;
  the default Mac manifest-refusal regression only compiled here.
- Five mutation-fuzz smokes pass with two workers and five requested seconds each;
  exact executions/timings appear in the [index](make-plate-manifest-verification.json).
- Release-contract check passes. API/web/schema 17, dependencies, original geometry
  parser, production bridge entry points and source model bytes are unchanged.

Manifest limits: 8 MiB, 10,000 entries, depth 16, 250,000 value nodes, 2,048 keys/object,
portable direct JSON basenames and a four-component decimal bundle version.
Unsupported shapes fail closed. The worker's 2-MiB ceiling can reject an index below
the file/entry limits. These limits do not change model uploads. Later discovery
must share aggregate file/byte/time budgets across manifest and profile reads,
not reset them through independently timed calls. No OS sandbox, atomic multi-file
snapshot, parent-crash guarantee or native Windows lifecycle proof is added.

## Durable captures and retained interruption

Private root `/home/vinnyc/.local/state/makersvault/verification/`:

- `containment-mp1b3-manifest-preflight-20260913`: exit 0, dirty entry sources;
  89 unit / 94 top-level / 198 inclusive passes and vet. Predates the final oversized-
  response and default-Mac regressions; not exact-source proof.
- `containment-mp1b3-manifest-final-20260913`: compression wrapper reached its
  120-second limit before `result.json` was saved. All pass/build/fuzz markers are
  in the logs, but this is **incomplete, not an accepted exit-0 run**. Its started
  receipt and both logs remain hash-bound. No worker/container survived.
- `containment-mp1b3-manifest-final2-20260913`: completed source-bound rerun using
  the same capture script directly, without the short outer wrapper. Clean source
  before/after; completed receipt records exact command/times and log hashes.

Two earlier wrapper invocations were rejected before execution by argument filtering;
no test result or capture directory was produced. No test failure is hidden.
Verification uses network-disabled UID/GID 1000 containers and read-only sources;
only formatting had a writable source mount. Pinned Go 1.26.6 image:
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
The [driver](make-plate-manifest-check.sh) uses disposable authored fixtures and
retains failing fuzz corpora; none occurred. The [read-only checker](make-plate-manifest-verify.cjs)
joins seven hashes, source identity, pass/build/fuzz counts and unchanged production
boundaries. Historical checkers are not weakened to accept the changed source.

## Re-cock

Continue Windows/Linux root planning and explicit local root/account selection,
manifest-to-document identity/parent-closure discovery, independently observed app
versions and the native Windows/lifecycle qualification package. An index does not
close discovery. No real workstation profiles were read or device software installed.
Keep scanning inactive until matched consented integration and qualification pass.

MP-1c still couples scoped claim/review/commit, immutable storage, additive migration
and portable/raw recovery. MP-1d and named Bambu/Orca/Prusa evidence remain required.
No app-image rebuild, full API/web gate, fresh security scan, waiver transfer, gate
closure, push or publication. Existing Mac file-open/browser scope and CNC/CAM,
desktop and performance deferrals are unchanged. All commits remain local.
