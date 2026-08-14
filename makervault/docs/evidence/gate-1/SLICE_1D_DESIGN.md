# Gate 1 Slice 1D Design

**Slice:** Redirect- and connection-aware remote-import SSRF controls

**Status:** Implementation contract

**Prepared:** 2026-08-14

**Finding:** MV-SEC-003

## Current executable truth

The API validates the initial URL hostname, asks the operating-system resolver
for its addresses, and rejects known local address classes. It then hands the
original hostname to `urllib`, which independently resolves and connects and
automatically follows redirects. The final URL string is validated only after
the connection and response already occurred. A DNS answer can therefore change
between validation and connection, and a redirect can reach a forbidden target
before its URL is inspected.

The same unrestricted behavior exists in seven source-resolver helper requests
for MakerWorld, Printables, and Thingiverse. Fixing only the main download path
would leave those server-side requests outside the policy.

## Transport contract

Every outbound request made for remote import or source resolution will use one
transport with these rules:

1. Accept only HTTP and HTTPS URLs with no embedded credentials or control
   characters and a valid host/port.
2. Resolve the hostname once for each request hop. Require every returned
   address to be globally routable; reject loopback, private, link-local,
   multicast, unspecified, reserved/special-use, and mixed public/private
   answer sets for both IPv4 and IPv6.
3. Connect directly to one of the already-validated socket addresses without a
   second hostname lookup. Preserve the original hostname for the HTTP `Host`
   header and HTTPS certificate/SNI validation.
4. Disable automatic redirect handling. Follow at most five HTTP redirects,
   resolving, validating, and pinning each hop before it is contacted.
5. Reject HTTPS-to-HTTP downgrade redirects. On any origin change, remove
   `Authorization`, `Cookie`, `Proxy-Authorization`, and caller-supplied `Host`
   headers before the next request.
6. Resolve relative `Location` values against the current URL. Preserve methods
   for 307/308; apply normal browser-compatible GET conversion for 301/302/303.
7. Ignore implicit process proxy variables. A proxy would make the proxy—not the
   validated destination—the connected peer and therefore cannot be silently
   introduced into this trust contract. Future proxy support requires an
   explicit, separately validated operator configuration.
8. Apply the same transport to direct downloads, HTML discovery, JSON/API source
   resolvers, and ZIP staging. Policy violations remain actionable HTTP 400
   responses; remote HTTP status and reachability behavior remains compatible.

The current 30-second socket timeout and bounded response/file readers remain in
force. This slice does not broaden allowed URL schemes, enable private-network
imports, or change the supported single-admin deployment posture.

## Adversarial proof requirements

- Direct IPv4 and IPv6 local/special-use targets are rejected.
- A hostname resolving to any forbidden address is rejected, including a mixed
  public/private result.
- The connector receives the exact validated numeric socket address and does not
  resolve the hostname again.
- A DNS answer change after validation cannot alter the connected address.
- Relative and public redirects work within the hop limit.
- A redirect to a private target is rejected before a second connection.
- HTTPS downgrade and excessive redirects fail closed.
- Cross-origin redirects do not forward cookies or authorization headers.
- Every resolver helper imports the shared safe transport; no production
  `urlopen` call remains in the API import surface.

## Compatibility and rollback

Public HTTP/HTTPS direct links and the existing source-specific discovery flows
remain supported. Public hosts using several public A/AAAA answers retain
connection fallback. Split-horizon hosts that return a private answer are
intentionally rejected, matching the existing documented prohibition on local
addresses. HTTPS downgrade redirects and implicit environment-proxy routing are
newly rejected security behaviors.

No schema, stored file, or API response model changes. Rollback restores the
previous transport code; no data migration or restoration is required.
