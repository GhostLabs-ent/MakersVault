# MP-1b-4 — Bambu known-location planning and anchored inspection

**2026-09-13 America/New_York (captures September 14 UTC).** Owner directed
continuation from MP-1b-3. Entry `a29f010e16d62a208ecfcc70ae4c3ce98cce5c10`;
implementation `123e0babd12f061340e386a9fd21c0f7e296d320`.
**Location substep locally verified; full profile discovery, MP-1b and MP-1 remain open.**

## Delivered boundary

- A pure Windows/Linux planner returns known Bambu data-directory candidates from
  caller-supplied local hints, or one explicit custom root. It neither probes nor
  selects an installation. Invalid selected hints fail, without fallback scanning.
- One explicit data-root/account inspection traverses fixed `system/BBL.json`,
  `system/BBL/machine` and optional `user/<account>/machine` paths using held parent
  handles. It returns the system manifest index and selected user's direct JSON
  filenames, not profile contents or selectable-printer claims.
  Selected user files receive metadata-only handle inspection, not body reads.
- Empty account means system-only. No default/first/logged-in account is guessed;
  selected missing/unreadable sources fail the whole operation. No other accounts,
  general configuration, URLs, executable/version commands or profile bodies are read.
- One deadline and shared manifest/user entry allowance apply. Fixed-child traversal
  never promotes a joined child to a newly approved root; Linux nested same-device
  directory mounts remain prohibited. All ancestors remain held through final checks.
- The inactive private worker adds `location`, rejects cross-operation account
  authority and mixed/partial responses, and omits root/account names from results.
  The application-version field is explicitly empty/unobserved, not inferred from
  the manifest or directory label. New Mac location scans remain unsupported even
  with the earlier experimental reader enabled.

See [implementation contracts and pinned primary sources](../../../slicer-bridge/internal/presetfiles/LOCATIONS.md).
The upstream application key, GUI root logic and preset directory/loading constants
were reviewed at `926a7192574bcb9b3a732e1ec59a46d79cb45466`; no vendor bytes were copied
into the authored fixtures or claimed as installed-device qualification.

## Exact-source verification

| Check | Result | Scope limit |
|---|---|---|
| Full Go race suite | **104 unit tests**, six seeded fuzz targets; **110 top-level / 225 inclusive pass events**, zero failure/skip | Linux/amd64, UID/GID 1000, synthetic fixtures |
| New location controls | Known/custom path plans, no JSON path authority, exact account choice, missing layout/account, source preservation, privacy, shared budgets, nested links/FIFO/files, held-parent replacement and unprivileged permissions pass | No native folder picker, account enumeration or installed-profile parsing |
| Nested-mount negative control | Separately treating the mounted child as a new root allows a manifest read; anchored inspection from its parent rejects the same-device directory bind | Explicit disposable container mounts; tests do not mount or change privileges |
| Private worker | System-only/selected-account round trips, account-presence validation, secret filtering, mixed-operation rejection and atomic failure pass | No production main dispatch or consent/import flow |
| Static/cross-build | `go vet ./...`; six OS/architecture combinations, **24 bridge/package-test builds** | Windows/macOS compiled, not executed; Mac refusal regression compiled only |
| Mutation fuzzing | Six targets pass, two workers and five requested seconds each | Execution counts/timings in the [evidence index](make-plate-locations-verification.json); smoke, not exhaustive proof |
| Release/source guard | Release-contract check passes; API/web/schema 17, dependencies, original geometry parser and production entry points unchanged | No full API/web gate, image rebuild or advisory scan |

The directory listing counts ignored non-JSON entries against its remaining shared
10,000-entry allowance. Only one manifest body is read, capped at 8 MiB; there is no
reset of the 15-second parent deadline. The private response cap remains 2 MiB.
Later content discovery must extend aggregate file/byte accounting across profile
reads, not chain separately reset scans. Model uploads are unaffected.

## Durable evidence

Under `/home/vinnyc/.local/state/makersvault/verification/`:

- `containment-mp1b4-locations-preflight-20260913`: exit 0 on dirty entry sources,
  104 unit / 110 top-level / 225 inclusive passes and vet. Predates final shared-
  budget ignored-entry assertion and source contract documentation.
- `containment-mp1b4-locations-final-20260913`: complete race/vet/build/fuzz run on
  clean `123e0ba`, unchanged verification source before/after. Exact invocation,
  timestamps, exit status and stdout/stderr lengths/hashes are retained.

Both executed runs passed; no interrupted or failed test run occurred in this slice.
The final durable capture script runs directly to avoid the previous slice's short
outer compression-wrapper deadline. Formatting alone used a writable source mount.
Verification uses read-only source/fixture mounts, no network, UID/GID 1000 and Go
1.26.6 image `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
The [driver](make-plate-locations-check.sh) preserves failing fuzz corpora if any;
none occurred. The [read-only checker](make-plate-locations-verify.cjs) verifies four
log hashes, counts, source identity, fixture mounts and unchanged production surfaces.
Earlier source-bound checkers remain historical, not weakened or rerun as new passes.

## Re-cock

Next: bind manifest entries to actual document identities, resolve exact inheritance
and instantiate selectable Bambu presets under shared scan budgets. Keep explicit
user namespace separation and do not follow script includes. Native known-folder/
environment acquisition, account enumeration/local selection UI, independent app-
version observations, native Windows/lifecycle checks and matched consented worker
integration remain open; the planner/inspection primitives do not implement those.

The owner's Dell/Bambu Studio `v2.8.0.6` and YubiKey remain untested. No workstation
was scanned, software/handlers installed or Mac connection made. Production scanning
remains inactive. MP-1c still couples scoped import, immutable storage, additive
migration and portable/raw recovery; MP-1d still needs named real-application proof.
No gate closure, historical waiver transfer, push or publication. Existing Mac
file-open/browser scope and Mac-import/CNC/desktop/performance deferrals are unchanged.
All commits remain local; the owner's separate roadmap/desktop notes are untouched.
