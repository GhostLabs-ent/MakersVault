# Gate 8 Trusted Local Adapter Results

**Gate:** 8 — Generalize trusted local application adapters

**Status:** Verified; awaiting final owner acceptance

**Date:** 2026-08-26

**Entry commit:** `df62abf`

**Opening checkpoint:** `e127294`

**Architecture approval:** `dba76be`

**Bridge implementation:** `f2a7c1b`

**API/web implementation:** `f9ccde8`

**Schema:** 10 unchanged

**Publication state:** Local only. Nothing was pushed, tagged, released, deployed,
or published.

## Delivered behavior

- The bridge owns an embedded version-1 adapter catalog. It preserves every
  existing slicer and engraver ID and qualifies OrcaSlicer, Bambu Studio,
  PrusaSlicer, UltiMaker Cura, LightBurn, EZCAD, FreeCAD, and Inkscape under
  explicit platform, role, extension, executable-candidate, and argument rules.
- Existing `makersvault-slicer://` and `makersvault-engrave://` contracts remain
  available. `makersvault-open://` adds a general exact-file path without accepting
  arbitrary URLs, administrator tokens, server commands, default openers, shells,
  redirects, or unpaired origins.
- General grants bind one active asset, exact persisted file ID, filename, expected
  size, content role, adapter ID, and 90-second lifetime. Current primary,
  historical primary, visible supporting, and internal prepared files have
  separate selection and redemption checks. Wrong tool, role, or adapter headers
  fail closed.
- The bridge independently requires the selected local adapter to declare the
  granted role and downloaded extension before redemption and launch. The API
  retains a bounded safe extension category but does not supply executable paths or
  arguments.
- Advanced custom adapters exist only in local versioned configuration. They
  require an explicit enabled value, absolute regular executable, fixed literal
  arguments, exactly one standalone `{file}` argument, and bounded roles and
  extensions. Legacy slicer/engraver config and environment overrides remain
  compatible for the documented window.
- `list`, `doctor`, `trust list`, and exact `trust revoke` provide local diagnostics
  without exposing command paths, argument values, grants, or secrets. Malformed,
  unknown-field, and future-version configuration fails closed.
- The web keeps existing slicer and engraving actions and adds file-sensitive
  `Open with FreeCAD` or `Open with Inkscape` actions for current assets,
  supporting files, and immutable historical revisions. Browser protocol URLs
  contain only the fixed redemption endpoint, scoped grant, filename, adapter, and
  role—never a session token or direct file URL.
- Windows and Linux installers register all three schemes. macOS gains a user-local
  `~/Applications/MakerVault Bridge.app`, system and user `.app` discovery, Intel
  and Apple-silicon builds, and an exact user-local unregister/remove command.
  Signing, notarization, binaries, and public distribution remain release work.

## Regression-first evidence

The catalog tests were first run against the accepted bridge and failed to compile
because the versioned catalog, manifest validation, and resolver seams did not
exist. The diagnostics tests likewise failed on missing strict config decoding,
safe list/doctor output, and trust list/revoke behavior.

The general bridge tests then failed on missing content-role/adapter fields,
manifest authorization, and bound redemption headers. After those passed, the API
regression run produced `3 failed, 5 passed`: general requests were rejected as
unknown while an ambiguous legacy-plus-general body was incorrectly accepted.
The web regression failed type-checking because the general protocol builder did
not exist. The final macOS regression failed on missing user-application discovery
and exact bundle-path helpers.

Each regression passed after its bounded implementation. Tests exercise the real
parser, resolver, HTTP downloader, JWT validation, database/file selection, URL
builder, and platform contract seams; no unit under test is replaced by a stub.

## Verification

Focused verification on the workstation passed before the implementation commits:

- API handoff suite: `8 passed`
- Web: `21 passed`; TypeScript and production build passed
- Bridge: native tests/build under Go 1.26.6
- Platform conformance: Windows amd64, macOS amd64, and macOS arm64 cross-builds
  passed in addition to the native Linux build
- `git diff --check` and credential/debug marker scans passed

The complete repository `make verify` then passed at `f9ccde8` on the workstation
under a sleep inhibitor:

- API: `150 passed in 20.66s`
- Web: its previously verified Docker test layer passed; the immediately preceding
  uncached focused build recorded all `21 passed`, TypeScript, and production build
- Bridge tests and native build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose
  validation passed; production Compose still rejects missing authentication
  secrets
- Container smoke passed for direct/same-origin API access, security headers, the
  512 MiB file policy, non-root API/web processes, and unchanged schema 10
- The immutable v5.1 release contract passed

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking. The first sleep-inhibitor attempt was denied by desktop
policy before tests began; the authorized sudo invocation ran the complete gate.

## Rollback and remaining boundary

Gate 8 has no database migration or stored-byte move. Rollback requires keeping
API, web, and bridge versions matched; older clients safely ignore local version-1
adapter configuration while the preserved legacy schemes remain available. The
macOS bundle and local trust/config state can be removed independently without
mutating MakersVault data.

The unrelated untracked desktop architecture note remained untouched. Final owner
acceptance is still required to close Gate 8. No push, tag, release, deployment,
marketplace, SDK, remote manifest, auto-install, machine control, or publication is
authorized by this evidence.
