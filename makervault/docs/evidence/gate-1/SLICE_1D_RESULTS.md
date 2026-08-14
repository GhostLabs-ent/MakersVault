# Gate 1 Slice 1D Evidence

**Slice:** Redirect- and connection-aware remote-import SSRF controls

**Status:** Locally verified candidate

**Evidence date:** 2026-08-14

**Finding:** MV-SEC-003

## Implemented boundary

All outbound requests in the remote-import surface now use a single controlled
transport. This includes direct files, HTML discovery, temporary ZIP staging,
and the MakerWorld, Printables, and Thingiverse JSON/API helpers.

For every initial request and redirect hop, the transport:

- accepts only HTTP/HTTPS URLs without embedded credentials, invalid ports, or
  control characters;
- resolves the hostname and rejects the entire answer set if any IPv4 or IPv6
  address is not globally routable;
- connects a socket to the exact validated numeric address, retaining the
  original hostname only for HTTP `Host` and HTTPS certificate/SNI validation;
- manually follows at most five redirects and validates the next URL before
  making another connection;
- rejects HTTPS downgrade redirects;
- strips authorization, cookie, proxy-authorization, and supplied host headers
  whenever an origin changes; and
- ignores implicit process proxy variables so the validated destination remains
  the connected peer.

Public multi-address hosts retain failover across their validated answers. The
socket timeout, HTML/JSON read bound, and shared file-size/storage budgets remain
in force. `IMPORT_MAX_REDIRECTS=5` is operator-configurable and accepts `0` to
disable redirects.

## Adversarial regression evidence

The API suite proves:

- direct loopback, metadata/link-local, carrier-grade NAT, unspecified, local
  hostname, and IPv6 loopback targets are rejected;
- URL credentials, non-HTTP schemes, invalid ports, and control characters are
  rejected;
- a mixed public/private DNS answer fails closed;
- a DNS answer changing after validation cannot replace the numeric socket peer;
- a redirect to a private DNS result is rejected before a second request;
- cross-origin cookies, authorization, and caller-supplied host headers are not
  forwarded;
- relative redirects and 301/302/303 method conversion behave compatibly;
- HTTPS downgrade and redirect-limit violations fail closed; and
- no production `urlopen` call remains in either import module.

Container compatibility probes also completed a certificate-validated public
HTTPS request, handled a public HTTP 404 through the existing `HTTPError`
contract, and followed a live cross-origin HTTPS redirect to a successful final
response.

## Verification

| Check | Result |
|---|---|
| API/migration/security tests | Pass; 51 tests |
| Compose validation and security assertions | Pass |
| Public HTTPS request and certificate/SNI validation | Pass |
| Public HTTP error compatibility | Pass; status, headers, and body preserved |
| Public cross-origin HTTPS redirect | Pass; final response returned |
| Web type check, tests, and production build | Pass |
| Bridge tests and build | Pass |
| Container smoke | Pass |
| Complete repository harness | Pass; `make verify` |

## Compatibility and rollback

Public HTTP/HTTPS direct imports and current source-specific discovery flows are
preserved. Split-horizon names returning any private result remain intentionally
unsupported. HTTPS downgrade redirects and implicit environment-proxy routing
are newly rejected. An operator needing an outbound proxy requires a future
explicit proxy trust contract rather than silently weakening peer validation.

No schema, stored-file format, or API response model changed. Rollback restores
the previous transport code and environment; no data restoration is required.

## Finding disposition and next slice

MV-SEC-003 is resolved in the locally verified candidate. Gate 1 remains open.
Slice 1E next needs the owner-approved grant and origin contract for short-lived,
file-scoped slicer/engraver handoffs before changing the API, web client, or
bridge.
