# MP-0 — contracts and bridge compatibility

**2026-09-12. Status: bridge repairs verified locally; architecture package ready
for owner acceptance.** Entry `b059789`; bridge implementation `d11699767867f9bf05d7652f0eaafe9450e1e7df`.
The owner directed continuation after UP-1 and reports tablet Bambu Studio `v2.8.0.6`.
This does not qualify a device, close Gate 13C or authorize publication.

## Delivered

- [ADR 0020](../../adr/0020-printer-presets-and-plate-recipes.md) proposes the exact
  preset/snapshot/recipe ownership, normalized geometry, explicit import authority,
  lifecycle, portable-format and raw-recovery contracts. No API/migration is implemented.
- [Fixture inventory](MAKE_PLATE_FIXTURES.md) records public Bambu/Orca/Prusa versions
  and immutable source targets, plus the separately owner-reported tablet version.
  Source inspection is not a parser pass, captured installed profile or runtime pass.
- Linux and Windows manual scripts now include `makersvault-open` alongside both
  legacy schemes. The Linux descriptor advertises all three.
- Pairing command selection now has an explicit macOS `/usr/bin/open` branch.
  Windows/Linux command selection, consent listener, timeout, grant/role checks and
  model-file direct adapter launching remain unchanged. The Windows **browser**
  command retains its pre-existing `cmd /c start` dispatch; no shell is newly added
  to model-file handling.
- Bridge README now describes local development/matched binaries, production HTTPS,
  loopback consent, manual installer parity and remaining native qualification.

## Tests and exact source

| Check | Actual | Scope |
|---|---|---|
| Red regression | Expected exit 1: both scripts lack general-scheme registration; macOS reports unsupported OS | At `b059789` with new tests and behavior-preserving command-construction extraction; dirty instrumented source, **not** an unmodified historical tree |
| Full bridge race suite | **29 top-level tests / 43 inclusive pass events**, zero failed/skipped | Go 1.26.6, Linux/amd64, clean `d116997`; four additional top-level tests |
| Platform command contract | Windows/Linux/macOS exact argument arrays; Unix target remains one literal argument; unsupported platform fails closed | Command construction only, no native browser process launched |
| Cross-build | Linux/Windows/macOS × amd64/arm64 all compile | Six builds, not six native execution results |
| Linux manual installer | Copied executable matches generated source binary; three-scheme descriptor and installed `doctor` pass | Disposable container home; not desktop association/dispatch proof |
| Formatting | `gofmt -d` on changed Go files produces no differences | Read-only formatting check |

Go image: `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
No network, image pull, host home/handler changes or real slicer execution. Generated
executables and installed test copy were discarded with the disposable container;
no device artifact is supplied by this run. Source is mounted read-only.

The red checks ran before adding the macOS branch or changing either script.
The behavior-preserving extraction only made command construction inspectable on
Linux; the observed defects match the previous source review. The initial attempt
to invoke the capture with Docker `-e` arguments was blocked by the command wrapper
before execution; a file-based container driver was used, not inline interpreter code.

Durable private captures under `/home/vinnyc/.local/state/makersvault/verification/`:

- `containment-mp0-bridge-red`: expected failure and exact instrumented-source status.
- `containment-mp0-bridge-green`: clean source before/after, full JSON test events,
  six cross-build records, manual install/CLI observations; exit 0.

Each contains `result.json` and SHA-256-bound stdout/stderr. The
[evidence index](make-plate-verification.json) records both outcomes without replacing
the prior platform or UP-1 records. The [new driver](make-plate-bridge-check.sh) is
container-only; do not run it in a user's home. Reproduction of the green run:

```sh
docker run --rm --pull never --network none \
  -v /absolute/repo/makervault/slicer-bridge:/src:ro \
  -v /absolute/repo/makervault/docs/evidence/gate-13/make-plate-bridge-check.sh:/check.sh:ro \
  -w /src sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6 \
  sh /check.sh d11699767867f9bf05d7652f0eaafe9450e1e7df
```

Use the actual named source, not merely its build label. Running the `red` mode on
fixed source is expected to pass; the historical failed capture remains separate.

## Re-cock / next decision

Accept ADR 0020 and this bounded repair package before **MP-1** implementation.
Then start with Bambu reader fixtures, allowlist/inheritance/geometry negative
controls and the owner's exact application/profile identity. Persistent import
must include its scoped consent, additive migration and portable/recovery counterpart;
do not postpone that safety work until after users have saved presets. MP-2/MP-3
and the final MP-4 joined qualification remain undelivered.

The known manual-script omission and macOS branch defect are fixed **in source**;
real Windows registry dispatch, macOS consent/browser launch, signing/notarization,
Linux desktop dispatch, YubiKey and Bambu application behavior remain untested.
The tablet's reported `v2.8.0.6` is recorded verbatim, not inferred to be the public
2.8.2.61 fixture version. CPU, Windows/browser builds and actual preset identity
remain prerequisites for the [device checkpoint](WINDOWS_TABLET_CHECKLIST.md).

## Security and release boundary

C6/source-change re-review applies: this is a new bridge revision, not inherited
qualification. Fresh focused bridge contracts/race/cross-build evidence covers the
changed paths; native launch/support remains open. Preset import will add authority
and needs the separate MP-1 threat/negative-control qualification in ADR 0020.

No API/web/schema/dependency/build-image change, fresh vulnerability scan, full
API/web/lifecycle rerun, or change to historical exact-image E4/R57/F26/H0 conditions
occurred. The prior source-bound checkers are intentionally not weakened or rewritten
to accept this new tree. C1–C7/deadline remains unchanged; no candidate waiver transfer,
security/Gate 13C/13D closeout, push, tag, live deployment or publication.
CNC/CAM, Gate 12 desktop work and additional G13-01 performance tuning remain deferred.
