# Gate 1 Slice 1E Evidence

**Slice:** File-scoped handoff grants and bridge origin/launcher containment

**Status:** Locally verified candidate

**Evidence date:** 2026-08-14

**Findings:** MV-SEC-001, MV-SEC-007

## Implemented API capability

An authenticated `POST /asset/{id}/handoff` now issues a 90-second JWT for one
exact file identity and one role (`slicer` or `engraver`). Handoff tokens use an
HMAC key derived specifically for this purpose, with issuer, audience, type,
file-kind, file ID, asset ID, role, filename, size, timestamps, and unique ID
claims. They cannot validate under the administrator-session signing key.

Slicer grants prefer the current prepared attachment when present, including
pre-sliced G-code that remains hidden behind the model workflow. Otherwise they
select the primary model. Engraver grants select the primary asset. Both issuance
and redemption enforce role-specific extensions and current file identity/size.

`GET /handoff/redeem` accepts the grant only as
`Authorization: MakerVault-Handoff <grant>` plus the bridge's explicit tool-role
header. It does not accept query credentials. Grant JSON and file responses use
private/no-store cache policy.

## Browser protocol change

The web client first obtains the capability through its normal authenticated API
request. The custom protocol now contains only the fixed API redemption URL, the
short-lived grant, selected application ID, and display filename. It contains
neither the administrator JWT nor the legacy arbitrary `url` parameter. Removed
`other` options migrate to the existing OrcaSlicer or LightBurn defaults through
normal settings validation.

## Bridge containment

The v5.1 bridge:

- rejects legacy `url`/`token` payloads, malformed grants, unexpected actions,
  non-HTTP(S) redemption, query/fragment-bearing redemption URLs, and paths that
  do not end at `/handoff/redeem`;
- derives and requires an exact paired origin;
- prompts for first trust through an unguessable nonce path on a random
  `127.0.0.1` listener, displaying and HTML-escaping the exact origin;
- persists trust only after the local Trust action; Cancel writes nothing;
- warns before trusting unencrypted HTTP origins;
- sends the grant and tool only in headers, disables implicit proxies, follows no
  redirects, and applies a 5-minute/512 MiB default download budget;
- trusts the authenticated server filename, checks it against the role extension
  allowlist, creates files exclusively with mode `0600`, and removes every partial
  write after failure;
- redacts both legacy tokens and new grants from URL logs; and
- resolves only a built-in or explicitly local-configured application before
  pairing/download. Missing and `other` applications fail; no downloaded file is
  passed to the operating-system default handler.

The system browser is used only to display the bridge's own loopback pairing
page, never to open a downloaded file.

## Regression and abuse evidence

| Layer | Proof |
|---|---|
| API | Scoped grant redeems exact bytes and can retry within its validity window; query/Bearer use cannot authenticate normal routes; wrong role, expiry, tampering, wrong audience, and unknown assets fail; prepared files are selected for slicer. |
| Web | Protocol builder uses the correct role scheme and contains no `url`, `token`, or administrator credential. |
| Bridge | Legacy shapes, unexpected paths, `other`/missing apps, redirects, over-limit streams, role/extension mismatch, and cancelled pairing fail closed. Header redemption, server filename, partial cleanup, grant redaction, confirmed pairing, and config persistence pass. |

## Verification

| Check | Result |
|---|---|
| API/migration/security tests | Pass; 55 tests |
| Web unit tests | Pass; 5 tests |
| Web type check and production build | Pass |
| Bridge unit/abuse tests | Pass; 10 tests |
| Bridge build under Go 1.26.6 | Pass |
| Compose validation and security assertions | Pass |
| Container smoke | Pass |
| Complete repository harness | Pass; `make verify` |

## Compatibility and rollback

The visible actions remain one-click after initial origin confirmation. Existing
v5.0 bridge binaries cannot process the new protocol and must be upgraded with
v5.1. Existing custom command configuration remains valid; `trusted_origins` and
`max_download_mb` are additive optional config fields. `other`/default-opener
behavior is intentionally removed.

No database migration or stored-file rewrite occurred. API, web, and bridge must
roll back as a matched protocol set. Persisted paired origins are harmless if
left in the local bridge config.

## Finding disposition and next slice

MV-SEC-001 is resolved in the locally verified candidate. MV-SEC-007 is resolved
for bridge handoff: the administrator JWT no longer crosses the custom-protocol
boundary. The existing browser preview/file URL query-token compatibility path
remains explicitly assigned to Slice 1F's single-admin token-risk decision and
the longer-term Gate 11 session architecture.

Gate 1 remains open. Slice 1F next owns login throttling, session/token residual
risk, response security headers, host policy, and final deployment guidance.
