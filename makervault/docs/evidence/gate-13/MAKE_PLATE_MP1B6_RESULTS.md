# MP-1b-6 — Bambu saved-user machine format

**2026-09-14 America/New_York.** Owner directed the next slice after MP-1b-5.
Entry `0de87559e0a02d1ae2ec381002a5b86bae50be51`; implementation
`ff310d77a71803fb93af709462332bc06aa01f8b`.
**Bounded saved-user format locally verified. MP-1b/MP-1 remain open and inactive.**

## Delivered and not implied

- A dedicated `AddLocalUserMachine` path consumes only direct JSON from the held,
  explicitly selected Bambu `user/<account>/machine` directory. Missing system-style
  type/instantiation headers can be interpreted in that context, not via filename
  guessing, a document marker, arbitrary root or new private-wire mode.
- Actual names and user/version headers are required. Explicit non-machine type,
  wrong/missing source kind, malformed instantiation or unknown schema fails.
  Explicit false stays hidden; absent instantiation becomes selectable only on
  the dedicated saved-user path. No missing raw header is invented in the catalog.
- Generic/system `Add`, manifest binding, explicit-file `LoadBambu` and worker
  `project` stay strict. The existing `discover`/`select` operations gain the format
  support without gaining new request fields, APIs, filesystem roots or activation.
- File version accepts three/four bounded decimal components, then is discarded.
  It cannot fill app/bundle version, inherit into children or leak as raw metadata.
  Unsupported version shapes get a redacted code; current app version stays unknown.
- Inherited layout fields retain provenance; user overrides remain source values.
  Standalone/missing geometry is incomplete, never filled with slicer defaults.
  Exact-name missing/cyclic/ambiguous parent failures, limits, script exclusion,
  source-change checks and parent worker lifecycle constraints remain unchanged.
- Sidecars, other accounts, general config and nested custom base profiles are not
  read. Required parents only in a nested `machine/base` folder remain a missing-
  parent failure. Prerelease/build version suffixes need separate conformance.
  This is bounded format support, not a mirror of every profile a slicer can load.
- Parser version advances to `bambu-projection-3`; normalization code and request
  schemas stay unchanged. No stored snapshots exist or are rewritten by this slice.

The [source contract and primary references](../../../slicer-bridge/internal/presetfiles/SAVED_USER.md)
pin Bambu `926a7192574bcb9b3a732e1ec59a46d79cb45466` writer, loader and folder dispatch.
Tests use authored synthetic profiles, not copied vendor or private user files.
Neither source review nor a sample file-version string qualifies an installation,
the owner's reported Windows Bambu Studio v2.8.0.6, or native Windows behavior.

## Verification and retained attempts

- **Old-source control:** the new `TestSavedUserDirectoryProjection` is copied
  into an offline archive of old `535a0a1`. It fails with the exact missing-machine-
  identity rejection. The control driver requires that failure, then exits 0;
  7.017 seconds. This is one intentional regression-test failure, not a passing
  old implementation or an unexpected failed test attempt.
- **Preflight:** 136 unit/race tests plus eight seeded fuzz targets, **144 top-level
  / 294 inclusive pass events**, zero failure/skip, formatting and vet; exit 0 in
  29.821 seconds. Predates source-contract documentation, not runtime/test changes.
- **Final:** same 136 unit/race tests, 144 top-level / 294 inclusive passes, zero
  failure/skip; formatting, vet, six OS/architecture targets (**24 bridge/package
  test builds**) and eight mutation fuzz smokes pass. Exit 0 in 146.938 seconds,
  clean matching implementation before/after. Each smoke requests five seconds
  with two workers; [exact counts/timings](make-plate-saved-user-verification.json)
  are retained, not treated as exhaustive proof. Windows/macOS are compiled only.
- Release contract passes. API/web/schema 17, dependency declarations, production
  main/file-open protocols and geometry implementation are unchanged. No fresh
  full-application gate, image rebuild/advisory scan or historical-waiver transfer.

Durable private captures under `/home/vinnyc/.local/state/makersvault/verification/`:
`containment-mp1b6-saved-user-{red,preflight,final}-20260914`. Exact invocation,
source states, timing, exit status and stdout/stderr hashes are retained. Verification
uses read-only source/fixture mounts, network disabled, UID/GID 1000 and Go 1.26.6
image `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
The red driver extracts old source only inside its disposable container; it does
not change the worktree. Formatting alone used a writable source mount. The final
durable wrapper bypasses the known 120-second compression-wrapper limit; heavy
logs stay private. Earlier source-bound checkers/evidence remain unchanged.
The [read-only checker](make-plate-saved-user-verify.cjs) joins six log hashes,
source/command identity, fixture mounts, intentional red failure, green counts and
unchanged production surfaces. The [main driver](make-plate-saved-user-check.sh)
retains a failing fuzz corpus if needed; none occurred. All three driver invocations
exited 0; no unexpected failed or interrupted run occurred.

## Re-cock

Next MP-1b-7: bounded local account-choice enumeration and native location hints.
Keep directory/account names local, no automatic/default account selection, and
no browser/server-supplied path or production main dispatch. Picker/consent,
independent installed-version/real-profile evidence and native Windows/lifecycle
qualification remain required. Any supported-format expansion needs its own bounded
proof; a partial scanner must not be advertised as full slicer compatibility.

MP-1c still joins scoped import authority, immutable storage, additive migration
and portable/raw recovery. MP-1d still requires real Bambu/Orca/Prusa conformance.
Mac-local import, CNC/CAM, desktop Gate 12 and performance-tuning deferrals stay;
existing Mac file-open/browser scope remains. Windows/YubiKey tests remain unrun.
No workstation scan, Mac connection, live-vault/handler change, gate closeout, push
or publication. The owner's separate roadmap/desktop notes are untouched.
