# Gate 8 Baseline and Owner Checkpoint

**Gate:** 8 — Generalize trusted local application adapters

**Status:** Owner-approved; subgate 8A authorized

**Opened:** 2026-08-26

**Approved:** 2026-08-26

**Entry commit:** `df62abf`

**Entry schema:** 10

**Entry bridge protocol:** Gate 1 file-scoped slicer/engraver grant contract

**Publication state:** Local only. Gate 8 does not authorize a push, tag, release,
binary, SDK, or public adapter package.

## Verified entry baseline

The complete untouched repository harness passed at `df62abf` on 2026-08-26:

- API: `147 passed`
- Web: `20 passed`; TypeScript and production build passed in an explicit
  invocation
- Bridge tests and build passed under Go 1.26.6
- Canonical/deploy/compatibility/benchmark Compose validation and production
  security assertions passed
- Container smoke passed for direct/same-origin API access, security headers,
  the 512 MiB file policy, non-root processes, and schema 10
- The immutable v5.1 release contract passed

The existing frontend dependency-age and bundle-size warnings remain unchanged
and non-blocking. An auxiliary bridge count command initially used a login shell
that removed Go from `PATH`; the canonical gate and corrected non-login invocation
both passed, so this was a command error rather than a product failure.

## Current executable truth

Gate 1 already provides the security boundary Gate 8 must preserve:

- an authenticated API mints a 90-second grant for one exact current primary or
  prepared file and one `slicer` or `engraver` role;
- the bridge accepts only the fixed redemption path at an explicitly paired exact
  origin, sends the grant in a header, follows no redirects, enforces extension
  and byte limits, cleans failed partial downloads, and never uses the OS default
  file opener;
- only built-in executable candidates or commands explicitly configured on the
  workstation may launch; `exec.Command` is used without a shell; and
- the custom-protocol URL contains no administrator token or arbitrary download
  URL. Existing slicer and LightBurn/EZCAD workflows are a compatibility contract.

The current implementation is not yet a general adapter contract:

| Area | Current behavior | Gate 8 gap |
|---|---|---|
| Catalog | API, web, and bridge separately hard-code roles, extensions, IDs, and labels | Drift is possible and there is no versioned source of truth |
| Roles | Only current primary/prepared slicer and current-primary engraver handoffs are minted | Revision primary and visible supporting-file ownership are undefined |
| Applications | 13 slicer IDs and LightBurn/EZCAD are embedded in switch maps | No declarative capability/platform/argument contract |
| Custom commands | Local JSON/environment values may override a role/ID and prepend fixed arguments | Schema/version/diagnostics/revocation are implicit; invalid config is silently ignored |
| Platform | Windows and Linux install/discovery exist | macOS install, protocol registration, and application discovery are unsupported |
| Diagnostics | Failures are written to a local log | No safe list/doctor/trust/revoke interface; command arguments may be over-reported |
| UI | Two enable/select settings produce two hard-coded buttons | No file-sensitive `Open with` choice or locally approved custom-ID workflow |

## Proposed Gate 8 contract

### 8A — Versioned adapter catalog and bridge containment

1. Replace switch-map policy with one embedded, versioned adapter catalog owned by
   the bridge. Each adapter declares a stable ID and label; supported content
   roles/extensions; supported operating systems; executable candidates; a fixed
   argument template; and whether it is built-in or locally configured.
2. Keep the catalog inside the installed bridge/repository for Gate 8. Do not
   download executable definitions, accept a server-supplied command, load code,
   publish an SDK, or add a plugin runtime.
3. Preserve the Gate 1 origin, grant, redirect, byte, extension, safe-file, and
   no-shell controls. A manifest may narrow those controls but cannot widen a grant
   beyond its exact file identity and declared content role.
4. Validate configuration before use and return actionable errors. Never silently
   fall back to a default opener, another adapter, or a broader extension set.
5. Add safe `list`, `doctor`, `trust list`, and `trust revoke` diagnostics that
   redact grants, URLs containing credentials, and configured argument values.
   Revocation is local and immediate; it does not delete downloaded source files or
   mutate MakersVault data.
6. Preserve both legacy custom schemes during the compatibility window. A general
   scheme may be added only alongside them and must retain the fixed redemption
   shape; removal of the old schemes is a later release decision.

### 8B — Exact-file role contract and compatible API/web flow

1. Define content ownership independently of application category: current or
   historical primary, visible supporting file, and internal prepared payload.
   Every grant remains bound to one exact persisted file ID, expected size,
   filename, and approved content role.
2. Prepared payloads remain internal and may be offered only to an adapter that
   explicitly accepts prepared/toolpath content. `Open with` must not turn them
   into ordinary browse/download attachments.
3. The bridge, not a webpage, is authoritative for whether an installed adapter
   accepts the granted role and extension. The API still validates the stored file
   and a bounded content category before minting a grant.
4. Preserve existing `Open in Slicer` and engraving settings while introducing a
   compact file-sensitive `Open with` surface. Existing settings migrate without
   losing their enabled state or selected application.
5. Fail closed for unavailable, revoked, unsupported, or ambiguous adapters. The
   user receives a useful local diagnostic without a grant, token, secret, command
   argument, or unrestricted path in the message/log.

### 8C — Platform and conformance evidence

1. Prove Windows and Linux installation/discovery and, if approved below, add
   macOS user-local installation, protocol registration, `.app` discovery, and
   launch without shell evaluation.
2. Use fake executables, protocol inputs, and HTTP fixtures to execute the real
   catalog/parser/resolver/launcher seams. Do not replace the unit under test.
3. Prove at least one model slicer, one prepared-toolpath workflow, one laser
   workflow, one CAD workflow, and one vector workflow where those built-ins are
   approved. Missing commercial applications may use fake paths; Gate 8 does not
   claim vendor integration beyond a documented file-open invocation.
4. Re-run Gate 1 abuse cases, Gate 6 revision/role ownership, Gate 7 Project/Trash
   interactions, bridge build/tests, web typecheck/tests/build, schema-10 smoke,
   and the complete repository harness.

## Recommended owner decisions

### Built-in catalog

Recommended: preserve every existing slicer and engraver ID as a compatibility
adapter, but make the first conformance matrix deliberately small:

- OrcaSlicer, Bambu Studio, PrusaSlicer, and UltiMaker Cura for model/prepared
  workflows;
- LightBurn and EZCAD for laser workflows; and
- FreeCAD and Inkscape as the first genuinely generalized CAD/vector `Open with`
  adapters.

Other existing slicer IDs remain available but are not described as deeply
qualified vendor integrations until their path/argument fixtures join the matrix.
Gate 8 adds no machine control, slicing, fabrication dispatch, telemetry, or vendor
network API.

### Custom commands

Recommended: retain custom commands because Gate 1 explicitly preserved locally
configured launchers, but constrain them as an advanced local-only adapter:

- definitions are authored in the workstation config, never supplied by the API,
  browser, Project, archive, or remote catalog;
- execution uses a canonical local executable directly, never a shell;
- arguments are fixed literals with one explicit file placeholder and no variable,
  environment, command, URL, or template expansion;
- the custom adapter declares only a bounded role/extension subset and requires an
  explicit local enable/approval record; and
- listing and errors reveal the adapter ID/status but redact command paths and
  arguments by default. Removing/disablement is the revocation mechanism.

The existing `slicers`/`engravers` config shape receives a documented compatibility
translator for one release. Gate 8 must not silently rewrite or delete the local
config.

### Platform scope

Recommended: Windows, Linux, and macOS are supported by the Gate 8 contract. macOS
support is new and must include user-local install/uninstall, both legacy protocol
handlers plus any approved general handler, `.app` bundle discovery, and regression
proof. Code-signing/notarization and public binary distribution remain release work,
not permission to publish from this gate.

## Explicit exclusions

- No remote adapter marketplace, SDK, downloaded manifest, dynamic library, script
  plugin, auto-install, auto-update, shell command, or arbitrary URL fetch.
- No printer/laser/CNC control, job submission, device credentials, telemetry, or
  claim that opening a file means it was fabricated.
- No schema change, stored-byte move, Project-export import, ACL, multi-user
  permission model, push, tag, release, or publication.

## Rollback and checkpoint

Gate 8 is expected to change API/web/bridge protocol behavior as a matched set but
not database schema or stored bytes. Each subgate must preserve the old schemes and
settings until its replacement passes compatibility evidence. Rollback restores the
previous matched API/web/bridge version; local trust/config entries may remain but
must be ignored safely by older code.

The owner accepted the built-in catalog, constrained local custom-command, and
Windows/Linux/macOS recommendations without amendment on 2026-08-26. ADR 0012
records the accepted architecture. Subgate 8A may implement the versioned catalog,
configuration validation, diagnostics, revocation, and legacy-scheme compatibility
before any generalized API/web flow.
