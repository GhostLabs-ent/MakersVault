# ADR 0012: Versioned local application adapters

**Status:** Accepted

**Proposed:** 2026-08-26

**Accepted:** 2026-08-26

## Context

Gate 1 narrowed workstation handoff to a 90-second exact-file grant, an explicitly
paired API origin, a bounded no-redirect download, and either a known executable or
a command configured on the local workstation. That contract is safe enough to
generalize, but the application IDs, labels, extensions, executable candidates,
and arguments are duplicated across API, web, and bridge switch maps. The current
configuration has no schema version or diagnostic/revocation interface, and macOS
has no installer or application discovery.

MakersVault must open supplied files in useful workshop applications without
becoming a remote command runner, plugin marketplace, application installer, or
machine controller.

## Decision

### Catalog and authority

The installed bridge owns one embedded, versioned catalog of declarative adapter
manifests. A built-in manifest has a stable ID and label, accepted content roles
and extensions, supported platforms, executable candidates, and a fixed argument
template. It contains data only: no downloaded code, dynamic library, script body,
shell expression, lifecycle hook, arbitrary URL, or device/network authority.

The API remains authoritative for stored file identity and ownership. A handoff
grant names one exact file ID, filename, expected size, and content role. The bridge
remains authoritative for whether the selected installed adapter accepts that role
and extension. A manifest may narrow a grant but cannot expand it.

The existing `makersvault-slicer` and `makersvault-engrave` schemes, settings, and
application IDs remain supported during a compatibility window. A general scheme
may be added alongside them, never as an unproven flag-day replacement.

### Built-ins

All existing slicer and engraver IDs remain compatibility adapters. The first
qualified conformance matrix covers OrcaSlicer, Bambu Studio, PrusaSlicer,
UltiMaker Cura, LightBurn, and EZCAD, plus FreeCAD and Inkscape as the first general
CAD/vector adapters. Other retained IDs remain available without claiming a deeper
vendor integration than documented local file-open invocation.

Gate 8 supports Windows, Linux, and macOS. macOS support includes user-local
install/uninstall, protocol registration, `.app` discovery, and direct launch
without a shell. Signing, notarization, packaging, and public distribution remain
release concerns and are not authorized by this decision.

### Local custom adapters

Custom commands remain permitted for compatibility, but only as explicitly enabled
local adapters. They are authored in the workstation configuration and cannot be
supplied by the API, browser, Project metadata, archive, or a remote catalog. The
bridge executes a canonical local executable directly without a shell. Arguments
are fixed literals with one explicit file placeholder; variable, environment,
command, URL, and general template expansion are forbidden.

A custom adapter declares a bounded subset of content roles and extensions. Invalid
or unavailable definitions fail closed with actionable local diagnostics. The old
`slicers`/`engravers` shape is translated for one compatibility release without
silently rewriting or deleting the operator's file.

### Diagnostics and revocation

The bridge provides local catalog/status diagnostics and exact-origin trust listing
and revocation. Revocation is immediate for later requests. Logs and diagnostics
redact grants, credential-bearing URLs, configured argument values, and unrestricted
local paths by default. Missing, revoked, unsupported, or ambiguous adapters never
fall back to another application or the operating-system default opener.

### File roles

Current/historical primary content, visible supporting files, and internal prepared
payloads remain distinct ownership roles. Prepared content may be offered only to
an adapter that explicitly accepts it and never becomes an ordinary browse/download
attachment. Gate 8 changes no schema or stored bytes.

## Alternatives considered

- **Server- or marketplace-supplied manifests:** rejected because a self-hosted web
  origin must not gain local command-definition authority.
- **Remove custom commands:** rejected because Gate 1 explicitly preserved safe
  local configuration and specialist workshop tools require an escape hatch.
- **Keep only slicer/engraver switch maps:** rejected because duplicated policy
  cannot safely support general file roles, diagnostics, or another platform.
- **Use the OS default opener:** rejected because it silently delegates execution
  to mutable workstation associations and was intentionally removed in Gate 1.
- **Ship Windows/Linux only:** rejected because the generalized contract is expected
  to work on the owner's macOS clients as well as the existing platforms.

## Consequences

API, web, and bridge changes must ship and roll back as a matched protocol set, but
the old schemes remain available until compatibility evidence passes. The bridge
catalog becomes the application-capability source of truth, while the API retains
file-ownership authority. More platform fixtures and fake-executable conformance
tests are required. No database migration, byte move, plugin SDK, auto-install,
machine control, push, tag, or publication follows from this decision.
