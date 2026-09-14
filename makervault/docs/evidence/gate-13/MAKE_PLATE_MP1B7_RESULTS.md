# MP-1b-7 — Local account choices and native location hints

**2026-09-14 America/New_York.** Owner directed the next slice after MP-1b-6.
Entry `c52722c202732ed4f30a03d2164cd6e272a337e3`; implementation
`9a72c9127de0c1006e5d54e7931c3ca277168471`.
**Local account/hint foundation verified. MP-1b/MP-1 remain open and inactive.**

## Delivered and not implied

- Account enumeration lists only direct directory names under one explicitly
  chosen data root's `user` folder. Confined metadata handles, no account descent,
  profile/manifest/general-config reads, automatic account choice or active-login
  assumption. A folder named `default` has no special authority.
- All entries, including ignored ordinary sidecars, count toward 10,000. Invalid
  portable names, case-fold collisions, links, special files, nested mounts and
  observed ancestry changes fail atomically. Missing/unreadable `user` is an error;
  an existing empty directory is a successful empty list. Later explicit selection
  rescans and can reject a listed directory's unavailable/unsupported contents.
- A new private worker `accounts` operation returns local-only picker data. It
  cannot include account selection, picks or generic file inputs; its results cannot
  cross into other operations, candidate payloads or partial/error responses.
  Existing worker deadline, cancellation, reap slot and response ceiling remain.
- Native Windows/Linux root hints feed the unchanged pure planner, without testing
  presence or choosing an installation. Linux reads only synthetic/injected XDG/home
  hints in tests. Windows implementation uses a current-user non-verifying known-
  folder request and fixed System32 DLL loading; it is **compiled, not native-tested**.
- Native hint lookup is separate from the sanitized worker and currently cooperative,
  **not hard-deadline isolated**. This remains an explicit integration/lifecycle gate,
  not a claim that the Windows Shell call cannot stall. No HOME/XDG/credential
  environment expansion was added to the worker, and no native-hints wire operation
  or production caller was added.

The [source contract and primary references](../../../slicer-bridge/internal/presetfiles/ACCOUNTS.md)
document exact API/flag choices, stricter invalid-hint refusal, metadata boundaries
and limits. Names and paths are private local UI data, never server-owned path
authority. A hint is not an installed version; a directory is not proof of a usable
preset, logged-in account, owned printer or reachable device. The owner's reported
Windows Bambu Studio v2.8.0.6 and real profiles remain unqualified.

## Verification and retained attempts

- **Preflight:** 152 unit/race tests plus nine seeded fuzz targets, **161 top-level
  / 326 inclusive pass events**, zero failure/skip; formatting and vet pass.
  Exit 0 in 28.383 seconds. Predates source-contract documentation, not runtime/
  test changes. No intentional old-source regression run: these are new operations,
  with explicit negative controls rather than a claimed formerly failing feature.
- **Final:** the same tests/counts and zero failure/skip, formatting, vet, six OS/
  architecture targets (**24 bridge/package-test builds**) and nine mutation fuzz
  smokes pass. Exit 0 in 152.783 seconds, clean matching implementation before/after.
  Each smoke requests five seconds with two workers; [exact counts/timings](make-plate-accounts-verification.json)
  are retained. Short fuzz runs are not exhaustive proof. Windows/macOS compiled
  only; no native device or Windows known-folder call executed.
- New controls cover no-descent/private-body non-read, absent/empty directories,
  sidecars across the 64-entry batch boundary, invalid/colliding names, links/FIFO/
  hard links, unreadable directories, held-parent replacement/change checks and
  same-device binds at both `user` and account-child levels. Hint tests cover
  synthetic Linux acquisition, narrow environment lookup, invalid/UNC/relative
  refusal, diagnostic redaction and cancellation. Worker tests cover private
  round trips, no implicit selection/fallback, unknown fields and mixed output.
- Release contract passes. API/web/schema 17, production main/file-open protocols,
  dependency declarations, pure planner, entire preset projection package and
  supervisor remain unchanged. No new full-app gate, image/advisory scan, waiver
  transfer or native-safety qualification is claimed.

Durable private captures under `/home/vinnyc/.local/state/makersvault/verification/`:
`containment-mp1b7-accounts-{preflight,final}-20260914`. Exact invocation, source
states, timing, exit and stdout/stderr hashes are retained. Both exit 0, stderr
empty; no failed/interrupted attempt or failing fuzz corpus occurred. Verification
uses read-only source/fixture mounts, network disabled, UID/GID 1000 and Go 1.26.6
image `sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
Formatting alone used a writable source mount. The durable capture wrapper bypasses
the known 120-second compression-wrapper ceiling while keeping heavy logs private.
The [driver](make-plate-accounts-check.sh) and [read-only checker](make-plate-accounts-verify.cjs)
join source/commands, fixture mounts, counts, nine fuzz outcomes and four log hashes.
Historical source-bound checkers and their pass records are unchanged.

## Re-cock

Next **MP-1b-8: local root/account picker and consent-session foundation**. Keep
opaque local choices separate from browser/server input, require explicit account
or system-only selection, handle stale choices/cancel/expiry, and show what would
be shared. Address bounded native-hint acquisition without broadening worker
environment inheritance before activation. This next foundation must remain
inactive in production until the matched-main, native Windows/hint/reader/lifecycle,
independent installed-version and real-profile gates are met.

Nested custom bases/version suffixes remain unsupported. MP-1c still couples scoped
claim/review/commit, immutable storage, additive migration and portable/raw recovery;
MP-1d still needs independent real Bambu/Orca/Prusa conformance. MP-2–4 not started.
Mac-local import, CNC/CAM, desktop Gate 12 and performance-tuning deferrals stay;
existing Mac file-open/browser scope remains. Windows/YubiKey tests are unrun.
No real workstation scan, Mac connection, live-vault/handler change, gate closeout,
push or publication. The owner's separate roadmap/desktop notes are untouched.
