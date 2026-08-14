# Gate 0 Security Finding Revalidation

**Status:** Gate 0 record; reconciled through accepted Gate 1 evidence

**Revalidated:** 2026-08-13; Gate 1 accepted updates recorded 2026-08-14

**Committed anchor:** `80ddc5bb8849c0532ecf4de91010e450df28b940`

**Evaluated state:** committed anchor plus the preserved v5.1 and Gate 0 working
tree

This record reconciles the original security analysis with current executable
source. `CONFIRMED` means the behavior still exists; it does not mean remediation
has been implemented. `RESOLVED IN CANDIDATE` requires the Gate 0 verification
suite to remain green before release.

## Finding dispositions

| ID | Disposition | Current evidence | Owning gate |
|---|---|---|---|
| MV-SEC-001 | `RESOLVED IN ACCEPTED GATE 1` | The bridge accepts only 90-second exact-file grants from explicitly paired origins at the fixed redemption path; it rejects redirects/legacy URLs, bounds downloads, checks role extensions, and launches only built-in or locally configured applications without an OS-default file opener. | Gate 1 slice 1E verification and matched v5.1 bridge release. |
| MV-SEC-002 | `RESOLVED IN ACCEPTED GATE 1` | Production Compose requires explicit password/signing-secret values; API startup rejects missing, published, short, or reused secrets; the setup helper generates deployment-specific values without overwriting an existing `.env`. | Gate 1 slice 1A verification and local commit. |
| MV-SEC-003 | `RESOLVED IN ACCEPTED GATE 1` | Every import and source-resolver request validates all DNS answers, connects to the exact validated numeric peer, manually validates each redirect, rejects HTTPS downgrade, and strips cross-origin credentials. DNS-change, private-redirect, and live public-network probes pass. | Gate 1 slice 1D verification. |
| MV-SEC-004 | `RESOLVED IN ACCEPTED GATE 1` | `python-multipart==0.0.32` and the compatible FastAPI/Starlette set pass API/upload smoke tests; the resolved runtime lock audits clean. | Gate 1 slice 1B verification. |
| MV-SEC-005 | `RESOLVED IN ACCEPTED GATE 1` | `Pillow==12.3.0` passes existing image/thumbnail behavior and the resolved runtime lock audits clean. | Gate 1 slice 1B verification. |
| MV-SEC-006 | `RESOLVED IN ACCEPTED GATE 1` | Direct, supporting, remote, mounted, and extracted files share a streamed per-file ceiling and free-space reserve; ZIP enumeration, selection, expansion, ratio, 3MF metadata, and image decode work have explicit budgets. Ordinary multi-file imports retain unlimited batch count. | Gate 1 slice 1C verification; Gate 2 owns browser preview time/complexity budgets. |
| MV-SEC-007 | `PARTIALLY RESOLVED; V5.1 RESIDUAL ACCEPTED IN SLICE 1F` | Bridge handoff uses a derived-key exact-file grant and never receives the administrator JWT. Browser previews/file URLs retain query-token compatibility with remote HTTPS, no-referrer, private/no-store, session-only persistence, and CSP as compensating controls. | Gate 2 measured preview delivery and final Gate 11 session/file-delivery architecture. |
| MV-SEC-008 | `PARTIALLY MITIGATED IN ACCEPTED GATE 1` | The primary JWT migrates from persistent local storage to session storage; CSP narrows script execution. Active-page XSS can still read it. | Gate 11 HttpOnly/session architecture and revocation. |
| MV-SEC-009 | `LOGIN ABUSE RESOLVED; SESSION LIFECYCLE DEFERRED` | Bounded progressive source/identity cooldowns, constant-time checks, generic responses, and secret-free audit events protect the single-process login. JWTs still have no durable revocation store. | Gate 1 slice 1F for login abuse; Gate 11 for durable session lifecycle. |
| MV-SEC-010 | `RESOLVED IN ACCEPTED GATE 0` | The current multi-stage web image builds with Vite and serves only static output through `nginxinc/nginx-unprivileged`; the container smoke test observes web PID 1 as UID 101. | Gate 0 verification; accepted Gate 1 adds headers and host policy. |
| MV-SEC-011 | `RESOLVED IN ACCEPTED GATE 1` | Mounted candidates reject symlinks in every path component; copy and no-copy inspection open the source with `O_NOFOLLOW`, require a regular descriptor beneath the configured root, and copy from that verified descriptor. | Gate 1 slice 1C verification. |
| MV-SEC-012 | `DEFERRED BY PRODUCT DECISION` | The current global single-admin model has no authorization entities. Multi-user/MFA/SSO is explicitly not a v5.1 feature. | Gate 11; it becomes a release blocker before any multi-user feature ships. |
| MV-SEC-013 | `RESOLVED IN ACCEPTED GATE 1` | ZIP downloads sanitize every folder, model, primary-file, and supporting-file path component; ZIP imports reject traversal and normalized duplicate paths. | Gate 1 slice 1C verification. |
| MV-SEC-014 | `PARTIALLY MITIGATED` | Lazy/cached preview work reduces normal load, but synchronous browser decompression and parser work still lacks complete size/time/complexity budgets. | Gate 2. |
| MV-SEC-015 | `RESOLVED IN ACCEPTED GATE 1` | Generated Nginx responses carry a tested CSP plus nosniff, no-referrer, permissions, and frame denial; direct API responses carry the non-CSP baseline; `PUBLIC_URL` or `TRUSTED_HOSTS` enables API host enforcement. | Gate 1 slice 1F verification and external-proxy HSTS guidance. |
| MV-SEC-016 | `PARTIALLY RESOLVED IN ACCEPTED GATE 0` | 8,311 generated/runtime paths were removed from Git tracking without deleting local files; root ignore policy, source-owned verification, CI, and Dependabot now exist. Checksums, SBOMs, signing, and release provenance remain. | Gate 0 for source hygiene; Gate 5 for release artifacts. |

## Dependency scan evidence

### Python runtime

Command basis: `pip-audit` against the resolved Python 3.11 API environment, now
captured in `api/requirements.lock`.

Result: 52 advisory records across four pinned packages:

- `starlette==0.38.5`
- `python-multipart==0.0.9`
- `pillow==10.4.0`
- `PyJWT==2.9.0`

The count includes duplicate/overlapping advisory records returned by the audit
service. Gate 1 must select a compatible FastAPI/Starlette/Pydantic set and test
the upgrade; the record is not a recommendation to install isolated transitive
versions blindly.

### Web runtime and development toolchain

- `npm audit --omit=dev`: zero known vulnerabilities.
- Full `npm audit`: two development-toolchain vulnerabilities remain through the
  Vite 5/esbuild chain, requiring a major Vite upgrade according to npm.
- The critical advisory initially exposed by the new test dependency was removed
  by moving Vitest to `3.2.6`; tests and production build are re-run by CI.

The production image contains static output and Nginx, not Vite or `node_modules`.
Gate 1 still owns the build-tool upgrade and its compatibility evidence.

### Go bridge

- The bridge has no third-party Go module dependencies.
- `govulncheck v1.7.0` reports zero called vulnerabilities.
- It reports one vulnerability in an imported standard-library package whose
  vulnerable symbol is not called.
- Compatibility currently builds under Go 1.21.13; the supported/release
  toolchain should be refreshed before v5.1 artifacts are published.

## Gate implication

Gate 0 passed with confirmed product vulnerabilities because its purpose was to
make those facts reproducible and assign them. Gate 1 is now accepted with every
v5.1 P0 finding covered by regression evidence or an explicit, owned
compensating control. No current result supports unrestricted Internet exposure.

## Gate 1 slice 1B update — 2026-08-14

The isolated dependency candidate upgrades FastAPI/Starlette,
python-multipart, Pillow, and PyJWT as one resolver-compatible Python 3.11 set.
The runtime and verification locks audit with zero known vulnerabilities. The
first candidate exposed Starlette's deprecation of the legacy test-only HTTPX
adapter; switching the verification lock to HTTPX2 removed that warning.

Vite and Vitest were upgraded as one build-tool set. The complete npm audit now
reports zero production or development findings, and the production bundle and
web tests pass. The bridge builds and tests under Go 1.26.6, and `govulncheck`
reports no vulnerabilities. Exact versions and commands are recorded in
[SLICE_1B_RESULTS.md](../evidence/gate-1/SLICE_1B_RESULTS.md).

## Gate 1 slice 1C update — 2026-08-14

The local candidate now applies one streamed file policy to every ingest path,
retains an operational storage reserve, bounds ZIP and 3MF expansion work, and
limits Pillow to supported decoders and a decoded-pixel ceiling. Rejected writes
remove partial files and provisional rows. Mounted imports reject symlinked path
components and copy from a verified regular descriptor. ZIP import and export
names are normalized before use.

The limits remain compatible with large libraries and ordinary large file sets:
there is no library quota or ordinary batch-count limit. Exact defaults,
adversarial tests, and verification are recorded in
[SLICE_1C_RESULTS.md](../evidence/gate-1/SLICE_1C_RESULTS.md).

## Gate 1 slice 1D update — 2026-08-14

The local candidate replaces automatic `urllib` connections and redirects with
one import transport that pins each socket to the globally routable DNS answer
it validated. Every redirect is resolved and checked before connection; HTTPS
downgrades fail, and cookies/authorization are removed on origin changes. All
source-specific helper requests use the same boundary.

Adversarial coverage includes IPv4/IPv6 special-use targets, mixed DNS answers,
DNS changes, private redirects, cross-origin credential stripping, method rules,
and redirect limits. Live container probes preserve public HTTPS, HTTP-error, and
redirect behavior. Exact evidence is recorded in
[SLICE_1D_RESULTS.md](../evidence/gate-1/SLICE_1D_RESULTS.md).

## Gate 1 slice 1E update — 2026-08-14

The local candidate replaces administrator-token/arbitrary-URL custom-protocol
payloads with a 90-second capability for one exact file and tool role. The bridge
requires explicit nonce-bound local confirmation for each API origin, redeems
only at the fixed path without redirects, bounds and cleans downloads, validates
role extensions, and removes the operating-system default file opener.

API, web, and bridge abuse tests cover token separation, expiry/tampering,
prepared-file selection, protocol contents, origin confirmation/cancellation,
redirects, size cleanup, role mismatch, missing applications, and grant
redaction. Exact evidence is recorded in
[SLICE_1E_RESULTS.md](../evidence/gate-1/SLICE_1E_RESULTS.md).

## Gate 1 slice 1F update — 2026-08-14

The local candidate adds bounded, progressive, process-local login cooldowns,
constant-time credential checks, and outcome/source-only audit events. Browser
authentication migrates once from persistent local storage to session storage.
Protected file responses are private/no-store, and the browser query-token path
is retained as an explicit v5.1 residual rather than incorrectly marked fixed.

The generated web gateway now carries the tested CSP and common browser-security
headers. Direct API responses carry the non-CSP baseline. `PUBLIC_URL` derives
the recommended host policy; `TRUSTED_HOSTS` handles separate API or combined
public/LAN hostnames. HSTS remains at the operator-managed TLS proxy. Exact
evidence is recorded in
[SLICE_1F_RESULTS.md](../evidence/gate-1/SLICE_1F_RESULTS.md).

## Gate 1 accepted closeout — 2026-08-14

The owner accepted Gate 1 after all six slices passed the complete local
verification harness. The browser file-query and stateless-session limitations
remain explicit accepted residuals assigned to Gates 2 and 11. Direct public
port exposure remains unsupported, and HSTS remains an external TLS-proxy
decision. Consolidated exit criteria, rollback points, and publication state are
recorded in [Gate 1 results](../evidence/gate-1/RESULTS.md).
