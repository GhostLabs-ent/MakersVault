# Gate 1 Slice 1E Design

**Slice:** File-scoped handoff grants and bridge origin/launcher containment

**Status:** Owner-approved implementation contract

**Approved:** 2026-08-14

**Findings:** MV-SEC-001, MV-SEC-007

## Current executable truth

The web client places the full administrator JWT in a file URL and then embeds
that URL in `makersvault-slicer://` or `makersvault-engrave://`. Any webpage can
invoke a registered custom protocol, while the bridge currently accepts any
HTTP(S) download URL, follows redirects, writes an unbounded response, and may
launch the file through the operating-system default handler. The bridge cannot
distinguish a MakersVault request from an unrelated website.

## Approved capability contract

1. An authenticated API request may mint a grant for one exact stored primary or
   prepared file and exactly one tool role: `slicer` or `engraver`.
2. Grants expire 90 seconds after issue and are signed with a key derived for
   handoffs, not the administrator-session signing key. A handoff grant must
   never authenticate a normal API route.
3. The custom-protocol URL carries only a fixed redemption URL, the scoped grant,
   selected local application ID, and display filename. It never carries the
   administrator JWT or an arbitrary download URL.
4. Redemption accepts the grant only in an authorization header. It verifies
   audience, type, expiry, tool role, asset/file identity, and current file
   existence before streaming with private/no-store cache policy.
5. The bridge accepts a redemption URL only from an exact paired HTTP(S) origin
   and only at the handoff redemption path. It follows no redirects and applies
   declared and streamed byte limits with partial-file cleanup.
6. First trust of an origin requires an explicit local confirmation page bound to
   loopback. The page displays the exact origin and uses an unguessable one-time
   path; confirmation persists the origin in the bridge config. No manual config
   edit is required.
7. The protocol's slicer/engraver role must match the grant at redemption. The
   downloaded extension must be appropriate for that role.
8. The bridge launches only a known built-in application or a command explicitly
   configured by the local operator. Missing/`other` applications fail with an
   actionable error; the operating-system default file opener is removed.
9. Grants may be retried during their 90-second validity window. They are
   stateless and not single-use so a transient bridge/download failure does not
   consume the only attempt.
10. Existing v5.0 bridge protocol payloads are rejected. v5.1 requires the v5.1
    bridge binary and a one-time origin confirmation per MakersVault API origin.

## Pairing and trust details

The bridge derives the candidate origin from the redemption URL. If it is not in
`trusted_origins`, the bridge starts a short-lived HTTP server on a random
`127.0.0.1` port and opens the system browser to a nonce-bearing confirmation
page. The page shows the scheme, hostname, and port and provides Trust and Cancel
actions. Only confirmation at that unguessable loopback URL persists trust.

Pairing an HTTP origin is permitted because v5.1 supports explicitly trusted LAN
deployments, but the confirmation page warns that transport is unencrypted.
Remote deployments should pair only an HTTPS API origin.

## Default limits and roles

- Grant lifetime: 90 seconds.
- Bridge download timeout: 5 minutes.
- Bridge file ceiling: 512 MiB, matching the default server policy.
- Slicer extensions: STL, 3MF, STEP/STP, OBJ, G-code/GCO/BGCODE.
- Engraver extensions: the existing engraving UI set (SVG, LBRN/LBRN2, DXF,
  AI/EPS, PDF, PLT/HPGL, PNG/JPEG/WebP/BMP/GIF/TIFF, and EZD).
- Redirects: none.

## Required proof

- A handoff grant cannot authenticate `/assets` or another administrator route.
- Expired, wrong-audience, wrong-role, altered, or unknown-file grants fail.
- Slicer grants select prepared content when present; engraver grants remain
  scoped to the primary file.
- The web custom URI contains no administrator token and no legacy arbitrary
  `url` parameter.
- The bridge rejects legacy shapes, unpaired origins, redirects, excessive
  responses, role/extension mismatch, and missing/`other` launchers.
- Pairing persists only after explicit nonce-bound loopback confirmation.
- Failed downloads remove partial files; logs redact grants.

## Compatibility and rollback

The user-visible action remains Open in Slicer/Open in Engraving Software. First
use against an origin adds one explicit confirmation. Existing app selection and
locally configured commands remain supported except `other`/OS-default launch.

No database migration or stored-file rewrite is required. Rolling back the API
and web also requires rolling back the bridge protocol as a matched set. Paired
origin entries are harmless if retained in the local bridge config.
