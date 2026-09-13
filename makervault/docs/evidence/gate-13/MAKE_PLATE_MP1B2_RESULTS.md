# MP-1b-2 — Windows file boundary and single-use scan supervisor

**2026-09-12 America/New_York (captures September 13 UTC).** Owner directed
continuation after MP-1b-1. Entry `42af7d1`; implementation
`60bd90c7ae58522b7b6c975c8ff2a5419f4810c3`. **Linux supervisor locally verified;
Windows implementation compiled, not natively verified. MP-1b and MP-1 remain open.**

## Delivered boundary

The [Windows reader](../../../slicer-bridge/internal/presetfiles/README.md) now has
an amd64/arm64 implementation rather than an unsupported stub. It accepts bounded
drive-absolute paths on fixed NTFS volumes, opens components relative to held
parents, rejects reparse/remote/placeholder/special-file conditions, and grants
data access only after metadata validation. A held file is reopened by handle,
not by re-resolving its pathname. Conflicting writes/deletes can require an explicit
retry while read-sharing handles are held. No permissions or privileges are changed.

Pure Windows-path tests run on Linux. Native tests are authored for ABI layout,
list/load/source preservation, hard links/directories, held-file write/delete
exclusion and symlink roots. **None has run on Windows.** ACL, junction/mount,
cloud-placeholder, file-filter and process-lifecycle cases still require native
qualification; a skipped symlink fixture must not count as a pass. NTFS-only policy
does not imply that ReFS/FAT/removable storage has been qualified or promised.

The new [worker package](../../../slicer-bridge/internal/presetworker/README.md)
reexecutes only the current binary with a constant argument. Locally constructed
root/file selections travel through private stdin, not argv or a server request.
It performs one direct listing or one selected Bambu projection. Parent environment
secrets are not forwarded; stderr is discarded and makes the operation fail.
Failed reads/picks, malformed responses, overflow or abnormal exit never publish
partial candidates. Fixed error codes replace raw diagnostics.

The parent applies its 15-second context budget (or earlier caller deadline),
kills a timed-out/cancelled worker and closes owned pipes without synchronously
waiting for stalled child work. One worker slot stays occupied until actual reap
and pipe cleanup, preventing repeated hidden workers behind a delayed cleanup.
This is per parent process, not a system-wide lock or an OS sandbox.

**No activation:** only the test executable dispatches the worker argument. The
production bridge main, protocols, configuration, download/launch paths and API/web
remain unchanged. No installer, background service, source discovery, local consent
UI, network import, persistent preset or plate-generation feature is added.

## Exact-source checks

| Check | Actual result | Limit |
|---|---|---|
| Full Go race suite | **80 unit tests**: 68 previous + 2 pure Windows policy + 10 worker; four seeded fuzz targets. 84 top-level / 166 inclusive pass events, zero fail/skip | Linux/amd64 unprivileged container, UID/GID 1000 |
| Subprocess success | Real self-exec list/project round trips pass; selected geometry preserved, raw fields/local namespace/environment marker absent from response | Synthetic documents, not actual installed Bambu profiles |
| Cancellation and abuse | Hung-child/blocked-stdin deadlines, cancellation, busy-slot rejection, stdout/stderr overflow, nonzero exit and malformed response controls pass | Ordinary fixture workers reaped; no actual uninterruptible kernel-I/O task created |
| Framing/privacy | Duplicate/case/Unicode-key aliases, unknown fields, oversized/deep input, mismatched response identity, partial failure and unknown error-code checks pass | Private pipe schema, not future server geometry validation or consent |
| Existing file controls | Prior Linux permission, symlink/hardlink/special-file, same-device bind and replacement-race tests pass | No native Windows/macOS filesystem execution |
| Static/cross-build | `go vet ./...`; six OS/architecture targets, bridge plus three package test binaries each | Twenty-four artifacts; Windows native reader tests compiled only, macOS reader still a fail-closed stub |
| Fuzz smoke | Projection 56,686; portable filename 260,648; Windows-root syntax 154,461; worker framing 53,671 executions | Two workers, requested five seconds each; reported six/five/six/six seconds, not exhaustive proof |
| Source/release guard | Verification source clean before/after `60bd90c`; release contract script passes | API/web/schema 17/dependencies/original projection package and production bridge entry points unchanged |

Windows naming syntax now has separate pure validation, and the shared filename
collision key uses Unicode simple-fold equivalence rather than lowercase alone.
That closes the tested sigma/Kelvin-name collision gap without claiming every NTFS
case behavior is represented by Go's Unicode rules.

## Resource and assurance limits

The private worker request is capped at 4 MiB, response at 2 MiB, stderr drain at
64 KiB, and selected presets at 100. Existing reader limits remain 10,000 files/
entries, 8 MiB/file, 128 MiB aggregate and a cooperative scan budget. JSON is one
strict frame with ASCII schema keys, depth 16, 250,000 value tokens and 64 keys per
object. No model-upload limit is changed.

Process creation, process termination and pipe-close system calls themselves still
depend on the host OS; this is not a hard real-time guarantee. A truly uninterruptible
task may retain the worker slot until reaped. Parent-crash job/process cleanup,
Windows pipe semantics and native startup remain unqualified. The supported child
does not spawn descendants; there is no general command runner, CPU/memory sandbox,
cross-process lock or local-privileged-tampering attestation. Native qualification
and matched main integration must address/report those boundaries before activation.

Direct file-reader APIs remain cooperative if used without the supervisor; the
eventual workflow must not silently fall back to them. Typed worker responses are
review data, not independent digest/geometry authentication or print-ready claims.
MP-1c still needs its strict server validator, canonical fixtures and scoped consent.
Source mutation checks remain non-atomic across multiple files.

## Durable captures and reproduction

Private root `/home/vinnyc/.local/state/makersvault/verification/`:

- `containment-mp1b2-worker-preflight`: exit 0, dirty source at entry, 80 tests and
  Windows/amd64 reader-test compilation. Predates the final ASCII-key alias and
  null-handle guards and source README updates.
- `containment-mp1b2-worker-final`: exit 0 on clean `60bd90c`, 117.657 seconds for the
  complete race/vet/build/fuzz driver. Exact command, source state, timestamps and
  log lengths/SHA-256 retained in `result.json` and the
  [evidence index](make-plate-worker-verification.json).

No executed verification attempt failed. The initial repository search found no
AGENTS.md (normal no-match exit); it was not a verification failure or missing pass.
All tests use pinned Go 1.26.6 image
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`,
network disabled, source read-only except the explicit formatting step, and the
previous slice's read-only synthetic same-device bind fixture. The
[driver](make-plate-worker-check.sh) reproduces the exact final capture command;
use a fresh private `/evidence` mount. Fuzzing uses a generated container-only copy,
retaining a failure corpus if needed; none was produced. Generated test files,
binaries and child processes are disposable, not installed on a host or tablet.

The [read-only checker](make-plate-worker-verify.cjs) recomputes four log hashes,
joins pass/build/fuzz observations and rejects changed API/web/bridge/driver source.
Old source-bound checkers/records stay unchanged and historical; do not weaken
them to bless this new implementation. Native Windows facts are limited to primary
Microsoft contracts and the local Go Windows source inspection linked in the reader
README; those are not device observations.

## Re-cock

Continue MP-1b with the **macOS reader and Bambu-owned known-root/manifest discovery,
local selection and independently observed versions**. Prepare the remaining native
Windows fixture/lifecycle matrix and matched, consented worker integration before
activation; the owner's Dell/Bambu `v2.8.0.6` and YubiKey remain untested. Do not install
or run a tablet bundle without scoped device direction, and do not drop any support
target silently. No arbitrary directory JSON listing can stand in for Bambu's active
manifest/preset discovery.

MP-1c still couples import authority, additive storage migration and portable/raw
recovery. MP-1d qualifies the complete workflow and named slicer versions. No API/web/
lifecycle suite or advisory scan was rerun and no runtime image rebuilt. Historical
image-specific dispositions, conditions and deadline do not transfer. Gate 13C/13D
and release acceptance remain open; CNC/CAM, Gate 12 and G13-01 tuning remain deferred.
All commits are local; no push, publication or live/device installation.
