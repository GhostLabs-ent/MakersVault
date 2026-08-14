# Gate 1 Evidence Review

**Gate:** 1 — Harden v5.1 trust boundaries and deployment

**Status:** Accepted

**Evidence date:** 2026-08-14

**Entry commit:** `8c1b646`

**Accepted implementation tip:** `22c55a4`

**Accepted:** 2026-08-14

**Publication state:** Local only; owner deferred all pushes until the coordinated
v5.1 rollout

## Objective result

A fresh v5.1 production launch now fails closed without deployment-specific
administrator credentials, applies explicit file/archive/image/storage budgets,
contains mounted and remote-import trust boundaries, uses a file-scoped desktop
bridge protocol, throttles login abuse, narrows browser-token persistence, and
ships tested response-header and host policies for its single-administrator,
self-hosted scope.

No result expands the product into multi-user identity, hosted operation, or
direct public-port exposure. Remote access remains supported through an
operator-managed HTTPS reverse proxy or equivalent private VPN.

## Accepted owner decisions

The owner accepted:

- guided environment setup rather than a first-visitor browser bootstrap;
- localhost/trusted-LAN direct use and HTTPS proxy/private-VPN remote use, with
  direct public exposure unsupported;
- per-file ingest limits without an ordinary multi-file batch quota;
- 90-second exact-file bridge grants, explicit local origin pairing, and no OS
  default opener;
- session-storage browser persistence for v5.1; and
- the dated browser query-token/session-revocation residuals assigned to Gates 2
  and 11 rather than an unmeasured media/session rewrite in Gate 1.

Gate 1 closeout was approved by the owner on 2026-08-14.

## Independent rollback points

| Slice | Local commit | Result |
|---|---|---|
| Gate 1 entry | `8c1b646` | Accepted Gate 0 and opened the Gate 1 workstream. |
| 1A | `a4caa34` | Fail-closed production authentication and setup path. |
| 1B | `09688d2` | Compatible dependency and verification toolchain refresh. |
| 1C | `d98f773` | Ingest/archive/image/storage budgets and filesystem containment. |
| 1D | `e25ebb8` | DNS/connection-pinned remote imports and controlled redirects. |
| 1E | `d37fd5c` | Exact-file bridge grants, origin pairing, and launcher containment. |
| 1F | `22c55a4` | Login abuse, session persistence, headers, host policy, and residual-risk disposition. |

These commits remain local by owner decision. No Gate 1 commit was pushed during
feature development.

## Exit-criterion evidence

| Gate 1 exit criterion | Status | Evidence |
|---|---|---|
| Confirmed v5.1 P0 findings have regression proof or an owned compensating control | Passed | Slices 1A–1F and the updated security ledger cover production secrets, vulnerable dependencies, bounded inputs, SSRF, bridge trust, and query-token residuals. |
| Malicious upload/import fixtures remain bounded | Passed | Per-file streaming, storage reserve, ZIP enumeration/selection/expansion/ratio, 3MF metadata, Pillow pixel, mounted symlink, redirect, DNS-change, and connection-peer abuse tests pass. |
| Default production launch cannot unknowingly use published secrets | Passed | Compose rejects absent values and API startup rejects missing, short, published, reused, or identical password/signing values. |
| Bridge abuse tests demonstrate the narrowed trust boundary | Passed | Exact origin/path, role, extension, redirect, size, partial cleanup, local confirmation, missing launcher, grant redaction, and session-token separation pass. |
| Supported deployment posture is explicit | Passed | Local/trusted LAN, HTTPS proxy/private VPN, separate-host compatibility, host allowlisting, CSP, HSTS ownership, and unsupported direct public exposure are documented. |
| Data and rollback boundary remains compatible | Passed | No schema, database-content, stored-file, or model-format migration occurred; each slice has a local rollback commit and configuration migration guidance. |

## Final local verification

| Check | Result |
|---|---|
| API/migration/security tests | Pass; 61 tests under Python 3.11 |
| Python runtime/development audits | Pass; zero known vulnerabilities in resolved locks |
| Web unit tests | Pass; 7 tests |
| Web type check and production build | Pass |
| npm production/development audit | Pass; zero known vulnerabilities at Slice 1B verification |
| Bridge tests/build | Pass; 10 tests under Go 1.26.6 |
| Go vulnerability scan | Pass at Slice 1B verification |
| Compose syntax and production-secret assertions | Pass |
| Container smoke | Pass; fresh schema 3, direct/same-origin API, generated security headers, request limit, and non-root processes |
| Complete repository harness | Pass; `make verify` at accepted implementation tip |

The web build retains its known large-chunk/browser-metadata warnings. Gate 2
owns measured preview and bundle behavior; Gate 1 introduced no unexplained
warning or generated source artifact.

## Security disposition

The authoritative ledger is
[GATE_0_REVALIDATION.md](../../security/GATE_0_REVALIDATION.md), updated through
accepted Gate 1 evidence.

Resolved in Gate 1:

- arbitrary desktop-bridge download/opener behavior;
- published production credentials and signing material;
- remote-import redirect/DNS/connection-target SSRF;
- vulnerable direct dependency/toolchain set;
- unbounded ingest/archive/image work owned by this gate;
- mounted-source symlink and ZIP path containment;
- single-process login abuse controls; and
- browser-security headers and configured host validation.

## Accepted residual risks and deferrals

- Browser file and thumbnail URLs retain the administrator query-token
  compatibility path. Remote HTTPS, no-referrer, private/no-store, CSP,
  session-only persistence, and bridge isolation are the accepted v5.1 controls.
  Gate 2 measures preview delivery; Gate 11 owns the final media/session contract.
- Active-page script execution can read the session token, and logout cannot
  revoke an already copied stateless JWT. Gate 11 owns HttpOnly/CSRF/session-ID
  and durable revocation design.
- Login cooldown state is bounded and process-local. A future multi-replica or
  multi-user deployment requires a shared identity/rate-limit architecture.
- HSTS remains an explicit external-proxy decision because the same application
  supports intentional trusted-LAN HTTP.
- Browser preview/parser time, complexity, concurrency, and memory remain Gate 2.
- Release SBOMs, checksums, signing, remote release CI, and upgrade/restore proof
  remain Gate 5. Gate 1 commits intentionally remain unpushed until rollout.

## Data, upgrade, and rollback result

Gate 1 changed configuration, request handling, browser storage, web/API response
policy, and the matched web/API/bridge protocol. It did not change schema version
3 or rewrite original files.

An upgrade requires safe production credentials and the v5.1 bridge. Existing
browser tokens migrate once into session storage; existing safe custom launcher
configuration remains valid. API, web, and bridge Slice 1E behavior must roll
back as a matched set. Database and storage restoration is not required solely
to reverse Gate 1, though normal release backup policy still applies.

## Next-gate recommendation

Gate 1 is accepted. Gate 2 may open with a non-private benchmark corpus and a
measured baseline before numeric preview budgets or user-visible skip behavior
are chosen. Only one roadmap gate remains active at a time.
