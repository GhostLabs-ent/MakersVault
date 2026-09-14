# MP-1b-5 — Bambu machine identities, parent closure and bounded selection

**2026-09-14 America/New_York.** Owner directed continuation from MP-1b-4.
Entry `2257965bf0e69d354d7cf5c00b1a63d7f56672ea`; implementation
`535a0a106197e202036a551e6e83f61fafbe155d`.
**Explicit-machine discovery locally verified. MP-1b/MP-1 remain open and inactive.**

## Delivered boundary

- One chosen data root and optional explicit account keep the same held ancestry
  across manifest, user index, actual machine reads and final change checks.
  No joined child directory gains independent root authority.
- Every non-script system entry must match the document's actual name exactly.
  Filename stems, aliases and case-insensitive parent matches are not substituted.
  System/user namespaces remain separate; duplicate identities, ambiguous parents,
  missing parents, cycles, excess depth and unsupported includes fail atomically.
- Every loaded machine chain is checked, including hidden machines. Local discovery
  lists only explicit true instantiation and counts hidden machines/excluded scripts.
  These choices are not owned/online printers or complete layout snapshots.
- Recognized script-template manifest entries are excluded **before any file open**.
  A malformed body and FIFO trap demonstrate no read is attempted. An inheritance
  reference to such an excluded entry fails, rather than importing script geometry.
- Exact local selection rescans the current source, then projects up to 100 unique
  choices in requested order. Missing geometry remains incomplete with reasons;
  no default bed/nozzle/exclusions or automatic user correction is invented.
- The manifest and profiles share file/raw-byte/time accounting. The index itself,
  all its entries (even excluded scripts), and all chosen user-directory entries
  conservatively share 10,000. Reads share 8 MiB/file, 128 MiB total and 15 seconds;
  the bounded reader uses a one-byte overflow detection probe. Uploads are unchanged.
- New private `discover`/`select` worker operations preserve the parent deadline,
  process-reaping and 2-MiB output boundary, with no mixed/partial error frames.
  Root/account/filenames do not enter these results. Bundle and unknown application
  version remain separate; labels themselves still require visible privacy review.
- `bambu-projection-2` rejects malformed instantiation, case-aliased headers and
  duplicates, and non-ASCII JSON keys. The geometry implementation is unchanged;
  fingerprints intentionally include the new parser version.

## Important format limit

The [source contract and pinned primary references](../../../slicer-bridge/internal/presetfiles/DISCOVERY.md)
distinguish system-style machine JSON from ordinary saved-user JSON. Bambu's
saved-user writer does not guarantee type/instantiation headers. **Those saved-user
shapes are not yet supported**: missing type rejects the whole selected scan, and
missing instantiation is counted as hidden, not guessed true. A dedicated negative
fixture preserves that boundary. Synthetic explicit-machine user fixtures prove
namespace/graph handling only, not actual Bambu user-profile compatibility.

No full vendor bundle, installed v2.8.0.6 profile set, app version or account was
read. The reviewed upstream revision is `926a7192574bcb9b3a732e1ec59a46d79cb45466`;
references are source review, not byte-hashed vendor fixtures or native qualification.

## Verification and retained attempts

- First preflight: **122 unit tests / 129 top-level / 258 inclusive passes**, no
  failure/skip, plus vet; 28.517 seconds. Predates JSON case-alias hardening and
  the explicit saved-user negative control.
- Second preflight: **123 unit tests / 130 top-level / 260 inclusive passes**, no
  failure/skip, plus vet; 27.852 seconds. Includes the final runtime/test changes.
- Final exact-source run: 123 unit/race tests, seven seeded fuzz targets, 130
  top-level / 260 inclusive pass events; no failure/skip. Formatting, vet and six
  OS/architecture pairs (**24 bridge/package-test builds**) pass. Seven mutation
  fuzz smokes pass with two workers and five requested seconds each; exact counts
  are in the [evidence index](make-plate-discovery-verification.json). Final duration
  136.508 seconds, exit 0, clean matching implementation revision before/after.
- Release-contract check passes. Production main, old file-open protocols,
  API/web/schema 17, dependency declarations and geometry implementation are unchanged.
  No fresh full application gate, image/advisory scan or historical-waiver transfer.

Private captures under `/home/vinnyc/.local/state/makersvault/verification/` are
`containment-mp1b5-discovery-{preflight,preflight2,final}-20260914`. Exact commands,
source state before/after, durations, exit statuses and log hashes are retained.
All three executed runs passed; no failed/interrupted test attempt occurred.
The [read-only checker](make-plate-discovery-verify.cjs) joins six log hashes,
source identity, exact counts, fixture mounts and unchanged production surfaces.
The [driver](make-plate-discovery-check.sh) retains a failing fuzz corpus if needed;
none occurred. These short smokes are not exhaustive proof. The final durable wrapper runs
directly to avoid the known short compression-wrapper timeout; heavy output stays
in private logs. Verification is offline, source/fixtures read-only, UID/GID 1000,
using Go 1.26.6 image
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
Only formatting used a writable source mount. Existing evidence/checkers are unchanged.

## Re-cock

Next MP-1b-6: qualify a dedicated Bambu saved-user machine projection from the
explicit machine-directory context, without weakening system identity/schema rules,
guessing from filenames or copying source version into installed-app version.
Then native hint acquisition, account enumeration/local selector, independent
version/real-profile evidence and Windows reader/lifecycle qualification remain.
Do not activate production worker dispatch until matched consented integration and
the outstanding boundaries are met. MP-1c still joins scoped import, immutable
storage, additive migration and portable/raw recovery; MP-1d needs real app proof.

No workstation scan, Mac connection, installation/handler change, live-vault write,
gate closeout, push or publication. The owner's Windows/Bambu v2.8.0.6 and YubiKey
remain untested. New Mac import/CNC/desktop/performance deferrals and existing Mac
file-open/browser scope are unchanged. Owner roadmap/desktop notes remain untouched.
