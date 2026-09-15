# MP-1b-9b-4a — Native UI qualification package preparation

**2026-09-15 America/New_York.** Owner directed continuation into MP-1b-9b-4.
Entry `e4d121bbe5ec0014817ca43cbd472f66cc43f987`; implementation
`01594bd3e8f024e15a195690d82a8cbe72b02e63`.
**Package locally verified and ready for operator review; zero native UI/device or
real-profile qualification. MP-1b-9b-4 and production activation remain open.**

## Delivered boundary

- A separately built [qualification runner](../../../slicer-bridge/qualification/preset-native/README.md)
  and synthetic consent backend require the explicit `makersvault_native_qualification`
  build tag. Ordinary builds exclude all four new Go files. Existing runtime files,
  production main/pairing/protocols/installers, API/web/schema 17, Go dependencies,
  native helpers and file/hint/worker providers are unchanged.
- Exact early UI-helper self-dispatch exists only in this test executable. **No
  file-worker dispatch** is added. No remote URL/root/account/command arguments,
  protocol handler registration, app install, real-profile read or vault endpoint.
- `--inspect` prints build/runtime identifiers without native UI or desktop probing.
  `--ui-fixture` requires console-style input/output, a successfully displayed scope
  notice and exact local confirmation. It uses the existing bounded owner/launcher,
  90s picker and five-minute session, with Ctrl+C cancellation. No URL fallback,
  timeout increase or browser-tab-close detection. Character-device checks are a
  usability guard, not authentication against another same-user process.
- Native browser/dialog actions in a future approved run will be real. All metadata
  is generated from one fixed in-memory synthetic preset. Selected roots are never
  passed to a reader; normalized preview cannot include them. Hints/account choices
  are synthetic, not observations of installations or account folders. Native
  OS/provider browsing can still perform filesystem/network I/O or retain state.
- Exact local approval consumes only the synthetic preview, records its digest and
  closes the owner. Console receipts exclude paths, nonce URLs, account labels,
  preview bytes and raw errors. `gate_qualified` is always false; exit zero is a
  completed observation, not a device pass. No automatic evidence/result upload.

The [operator packet](../../MAKE_PLATE_NATIVE_QUALIFICATION.md) specifies required
device facts, hash/inspection checks, explicit UI permission, safe scenarios,
sanitized reporting and stop conditions. OS execution controls must not be bypassed.
Native acceptance is not page readiness; helper exit is not proof of provider UI,
shared-browser or parent-crash cleanup. No desktop handler or installed package was
changed and no remote workstation was accessed during preparation.

## Verification

| Capture | Exit / duration | Observed outcome |
|---|---|---|
| `go-preflight` | 0 / 46.157s | 206 ordinary + 9 qualification units/race, vet/format, default exclusion, Linux inspection/refusal checks |
| `go-final` | 1 / 146.135s | Ordinary tests/36 builds passed; sixth existing fuzz target reported a context deadline; no failing corpus |
| `go-final2` | 0 / 249.748s | Unchanged implementation: all 215 units, 48 builds and 14 fuzz runs passed |
| `browser-final` | 0 / 40.302s | All 55 real-HTTP synthetic browser scenarios against the completed final-source fixture |

Four fresh private captures use prefix `containment-mp1b9b4a-` and suffix `-20260915`.
**One failed capture is retained; no incomplete capture.** No runtime/check-driver
editing during captures. Final captures retain identical start/end revision and clean
runtime status. Browser capture began after successful `go-final2` completed, never
against a pending fixture build or the failed capture. Preflight was dirty source at
entry; final adds refusal when the scope notice cannot be written, tested in the
existing consent test. All completed captures preserve their original logs/metadata.

The failed run reported `context deadline exceeded` during `FuzzBambuLocations`
after 143,064 executions at the requested 5s boundary (reported elapsed 6s). No
assertion counterexample, minimized input or failure corpus was emitted. That
unchanged fuzz target calls the pure bounded location planner, not a context-aware
filesystem operation. The exact timeout cause was not established; this is not a
proven application defect or a proven harmless infrastructure event. The entire
driver was rerun without source changes, omitted targets or enlarged budgets and
passed. The initial failure remains visible, not rewritten or treated as a pass.

**215 unit tests with race detection**: 206 ordinary plus nine tagged qualification
tests. Fourteen seeded fuzz targets give **229 top-level / 481 inclusive pass events**
in successful Go captures, zero failures/skips. New tests exercise exact/bounded
confirmation, broken notice output, redirected input, extra arguments, inspect-only
semantics, redacted failures, owner closure, synthetic normalized review and
filesystem-authority independence. Tests never dispatch the real native UI helper.

Formatting and vet pass. Ordinary Linux/Windows/macOS × amd64/arm64 bridge and five
package-test binaries retain **36 builds**. Tagged Windows/Linux × amd64/arm64 runner
plus two test binaries add **12 builds**, total **48**. Four candidate executables
are retained and hashed; only Linux amd64 `--inspect` and refusal modes were executed
inside the offline container. No native desktop UI, Windows execution or macOS
qualification artifact. Cross-compilation is not device qualification.

The reused 13 fuzz targets and new `FuzzQualificationConsent` each request 5s with
two workers. Exact reported counts are indexed; the successful run produced no
failing corpus. The new target checks arbitrary bounded input against exact consent
recognition without launching any UI. Short fuzzing is not exhaustive verification.

The unchanged browser driver passes **25 existing HTTP regressions + 30 asynchronous
picker cases / 156 picker-stage checks** across Chromium, Firefox and WebKit at
desktop/narrow viewports. These use the ordinary synthetic fixture, not the new
native runner or an installed browser handler. No new UI layout or device claim
follows from this regression pass. The prior referrer-harness failure remains in its
own historical checkpoint; application privacy headers are unchanged.

[Driver](make-plate-native-qualification-check.sh),
[index](make-plate-native-qualification-verification.json) and
[read-only checker](make-plate-native-qualification-verify.cjs) bind source, default
exclusion, candidate binaries, safe inspection/refusal outputs, exact commands/mounts,
test counts, browser fixture and **58 artifact hashes**, including the failed run.
Pinned Go 1.26.6 and Playwright 1.62.1 noble images/locked dependencies are unchanged.
All test containers run offline as UID/GID 1000 with read-only source/fixtures and
no published ports. Durable capture scripts ran directly, avoiding the previous
compression runner's 120s cutoff. Release contract passes for v5.1.0.

## Re-cock — MP-1b-9b-4b

Next is **approved hands-on native UI execution**, beginning with target identity,
matching executable hash and non-UI inspection. The owner was asked for Dell Windows
version/build and System type, plus Linux graphical-workstation availability; those
facts and explicit UI-test/device-transfer permission remain pending at closeout.
Do not guess x64/ARM64 or transfer/run a candidate on a device without scoped approval.
The full scenario matrix is in the operator packet; all native result rows remain
unrun. Package preparation does not close MP-1b-9b-4 or qualify a supported platform.

Matched native hint/reader boundaries, independently observed installed-app/bundle
versions and explicitly allowed real-profile checks remain required after UI review.
Owner-reported Bambu Studio `v2.8.0.6` is not independently verified. Physical YubiKey
checks remain separate/open. No Mac connection; Mac-local preset import, CNC/CAM,
Gate 12 desktop and extra performance tuning remain deferred. Existing Mac file-open
and browser scope is unchanged.

MP-1c retains authenticated claim/review/commit plus coherent storage/migration and
portable/raw recovery; MP-1d retains independent Bambu/Orca/Prusa conformance. MP-2–4
remain unstarted. No activation, live-vault mutation, full security scan, waiver
transfer, gate closeout, push or publication. E4/R57/F26/H0 remains exact-image
historical evidence. Owner ROADMAP and desktop architecture notes remain untouched.
