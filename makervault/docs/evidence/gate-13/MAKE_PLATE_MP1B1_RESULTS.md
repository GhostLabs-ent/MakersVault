# MP-1b-1 — confined local file-reader foundation

**2026-09-12 America/New_York (captures September 13 UTC).** Owner directed
continuation after MP-1a. Entry `8f95298`; implementation
`8a9b424f935b03938d9cbb388ce7a843e200924e`. **Locally verified slice; MP-1b and MP-1
remain open.** No new gate acceptance is inferred from a passing test.

## Delivered, and deliberately not enabled

The new internal [`presetfiles`](../../../slicer-bridge/internal/presetfiles/README.md)
package provides direct-child JSON listing and loading of explicitly selected
Bambu documents into the existing pure catalog. At most one system and one user
root share one local namespace. No partial list/catalog escapes on failure.
Roots/basenames stay local and cannot be carried through this input type's JSON.
Errors contain fixed codes, not local paths or source configuration.

Linux amd64/arm64 uses held directory/file descriptors, `openat2` confinement,
regular-file/single-link inspection, filesystem-family checks, and metadata-change
detection. Tests prove rejection of root/ancestor/file symlinks, hard links, FIFOs,
sockets, directories, pseudo-filesystems and a **same-device bind mount**. A held
root does not redirect reads after pathname replacement. Ordinary path-reading
negative controls reach synthetic private markers; the confined reader rejects them.

Listing is nonrecursive and counts **all** entries against 10,000, including ignored
non-JSON files. Loading retains the parser's 10,000-file / 8-MiB-file / 128-MiB-total
limits. These limits do not change model uploads. Cancellation/deadline checks are
cooperative between I/O operations; regular-file kernel I/O can still stall.

**Not delivered:** Windows/macOS backends, hard-deadline process isolation, automatic
known-location/manifest discovery, local selection UI, version observation, remote
import, persistence, plate planning or export. The bridge executable does **not**
call this package. Windows/macOS builds include fail-closed stubs, not qualified
readers. No background scan or new public/hidden CLI action is added.

## Verification at exact implementation source

| Check | Observed result | Boundary |
|---|---|---|
| Full Go race suite | **68 unit tests**: 47 previous + 21 new; two seeded fuzz targets. 70 top-level / 137 inclusive pass events, zero fail/skip | Unprivileged Linux/amd64 container, UID/GID 1000; not API/web/full-gate verification |
| Permission controls | Unreadable file and directory both fail with redacted errors | No root-capability bypass in the final run |
| Filesystem controls | Synthetic escapes/special files and real nested same-device bind fixture rejected; replacement-race test passes | Container-generated files and explicit fixture mounts, not native tablet/macOS behavior |
| Budgets | Actual 10,001-entry directory rejected even though entries are non-JSON; over-8-MiB sparse file rejected; 10,001 selected basenames rejected before I/O | No 128-MiB aggregate stress or hostile stalled-kernel-I/O proof |
| Static/cross-build | `go vet ./...` and six target combinations pass; bridge plus two package test binaries per target | Eighteen compiled artifacts; no Windows/macOS/arm64 execution |
| Short fuzz | Bambu projection: 143,760 executions; portable filename filter: 249,648 | Two workers each, requested five seconds each (reported six/five); smoke coverage, not exhaustive proof |
| Source/release contract | Verification source clean before/after `8a9b424`; release contract script passes | API/web/schema 17, dependencies, original parser and production bridge entry points unchanged |

Other cases cover paired system/user roots, child-before-parent inheritance,
read-only source preservation, portable basename validation, case-collision
rejection, missing/malformed/oversized input after successful reads, cancellation
before I/O, and ctime changes even after mtime is restored. Source mutation checks
do **not** create an atomic multi-file snapshot: an earlier file may change after
it was read. The later workflow still needs explicit review/refresh and digests.

## Captures and reproduction

All three captures are retained under private
`/home/vinnyc/.local/state/makersvault/verification/` and indexed in
[`make-plate-files-verification.json`](make-plate-files-verification.json):

1. `containment-mp1b1-files-preflight`: exit 0, dirty new-package source at entry;
   root container, 64 unit tests. Predates the unprivileged/bind/paired-root cases.
2. `containment-mp1b1-files-unprivileged-preflight`: exit 0, dirty source at entry;
   UID/GID 1000, explicit nested bind fixtures, 67 unit tests. Predates the final
   errno mapping test and explicit ordinary-reader negative controls.
3. `containment-mp1b1-files-final`: exit 0, clean `8a9b424`, 103.044 seconds including
   tests/vet/builds/fuzz, all results above. Source and exact command recorded before
   and after; stdout/stderr lengths and SHA-256 recorded by the capture wrapper.

No executed verification failed. One incidental shell command-availability query
was blocked before execution by the wrapper allowlist; it was not retried and no
restriction was changed. It was not a failed or passing test.

Use the final capture's exact Docker command with the committed
[`make-plate-files-check.sh`](make-plate-files-check.sh) driver. The Go image is
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`
(Go 1.26.6), with no network, source read-only, unprivileged UID/GID 1000, and private
fresh `/evidence` output. Bind the synthetic fixture directory read-only at
`/mount-fixture`, then bind its `base.json` over `/mount-fixture/child.json` read-only
to prove the same-device mount boundary. These are disposable-container mounts;
no repository fixture is overwritten and no privileged test issues a mount syscall.

The driver compiles both otherwise-unused packages explicitly. Fuzzing runs on a
container-only generated copy; a failure corpus would be copied to the fresh private
capture directory. None was generated. Temporary fixtures/builds/copies disappear
with the container. No real workstation profiles, host handlers, live vault,
credentials or tablet configuration were inspected or changed.

The read-only [`make-plate-files-verify.cjs`](make-plate-files-verify.cjs) checker
recomputes six log hashes and joins captured source/exit/test/build/fuzz observations
to the index. It also refuses changed API/web/bridge/driver source; later work must
retain this record as historical evidence rather than weaken its source guard.

Implementation rationale and pinned primary references are in the package README.
Bambu's [pinned preset loader](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp)
loads vendor manifests and separate user folders, while
[its data-root selection](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp)
permits a custom data directory. Direct JSON listing must therefore **not** be
presented as proof of the application's loaded/active printer presets.

## Re-cock: finish MP-1b before import authority

Next implement the **Windows native boundary and process-isolated timeout/cancel
supervisor**, keeping them inactive until tested. Then complete macOS and the
Bambu-owned known-root/manifest/local-selection/version-observation layer. Real
device results remain separately required; the owner's Dell/Bambu `v2.8.0.6` and
YubiKey are still untested. No support target is silently removed. Linux filesystem
families other than those explicitly allowed, FUSE/network paths and unsupported
kernels currently fail closed; qualify or surface these limitations before activation.

MP-1c still couples scoped import authority with the additive storage migration and
portable/raw recovery counterpart. MP-1d qualifies the complete workflow and named
slicer versions. MP-2–MP-4 remain undelivered. No API/web/lifecycle suite or advisory
scan was rerun and no runtime image rebuilt. Historical image-specific security
dispositions/conditions/deadline do not transfer to a future candidate. Gate 13C/13D
and release acceptance stay open; CNC/CAM, Gate 12 and G13-01 tuning stay deferred.
All commits remain local; no push, publication or live/device installation.
