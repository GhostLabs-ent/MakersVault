# Gate 0 Security Finding Revalidation

**Status:** Gate 0 record; updated by Gate 1 evidence

**Revalidated:** 2026-08-13; Gate 1 candidate updates recorded 2026-08-14

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
| MV-SEC-001 | `RESOLVED IN GATE 1 SLICE 1E CANDIDATE` | The bridge accepts only 90-second exact-file grants from explicitly paired origins at the fixed redemption path; it rejects redirects/legacy URLs, bounds downloads, checks role extensions, and launches only built-in or locally configured applications without an OS-default file opener. | Gate 1 slice 1E verification and matched v5.1 bridge release. |
| MV-SEC-002 | `RESOLVED IN GATE 1 SLICE 1A CANDIDATE` | Production Compose requires explicit password/signing-secret values; API startup rejects missing, published, short, or reused secrets; the setup helper generates deployment-specific values without overwriting an existing `.env`. | Gate 1 slice 1A verification and local commit. |
| MV-SEC-003 | `RESOLVED IN GATE 1 SLICE 1D CANDIDATE` | Every import and source-resolver request validates all DNS answers, connects to the exact validated numeric peer, manually validates each redirect, rejects HTTPS downgrade, and strips cross-origin credentials. DNS-change, private-redirect, and live public-network probes pass. | Gate 1 slice 1D verification. |
| MV-SEC-004 | `RESOLVED IN GATE 1 SLICE 1B CANDIDATE` | `python-multipart==0.0.32` and the compatible FastAPI/Starlette set pass API/upload smoke tests; the resolved runtime lock audits clean. | Gate 1 slice 1B verification; slice 1C still owns explicit request and parser budgets. |
| MV-SEC-005 | `RESOLVED IN GATE 1 SLICE 1B CANDIDATE` | `Pillow==12.3.0` passes existing image/thumbnail behavior and the resolved runtime lock audits clean. | Gate 1 slice 1B verification; slice 1C still owns malicious/oversized-image bounds. |
| MV-SEC-006 | `RESOLVED IN GATE 1 SLICE 1C CANDIDATE` | Direct, supporting, remote, mounted, and extracted files share a streamed per-file ceiling and free-space reserve; ZIP enumeration, selection, expansion, ratio, 3MF metadata, and image decode work have explicit budgets. Ordinary multi-file imports retain unlimited batch count. | Gate 1 slice 1C verification; Gate 2 still owns browser preview time/complexity budgets. |
| MV-SEC-007 | `PARTIALLY RESOLVED IN GATE 1 SLICE 1E CANDIDATE` | Bridge handoff now uses a derived-key, file/role-scoped 90-second grant in a header and never receives the administrator JWT. Browser previews/file URLs still retain the query-token compatibility path. | Gate 1 slice 1F residual-risk decision; final session/file-delivery architecture in Gate 11. |
| MV-SEC-008 | `CONFIRMED` | The primary JWT is stored in browser `localStorage`. | Gate 1 risk decision; final session architecture in Gate 11. |
| MV-SEC-009 | `CONFIRMED` | Login has no throttle and JWT sessions have no identifier or revocation store. | Gate 1 for single-admin abuse controls; Gate 11 for full session lifecycle. |
| MV-SEC-010 | `RESOLVED IN CANDIDATE` | The current multi-stage web image builds with Vite and serves only static output through `nginxinc/nginx-unprivileged`; the container smoke test observes web PID 1 as UID 101. | Gate 0 verification; Gate 1 still owns headers and host policy. |
| MV-SEC-011 | `RESOLVED IN GATE 1 SLICE 1C CANDIDATE` | Mounted candidates reject symlinks in every path component; copy and no-copy inspection open the source with `O_NOFOLLOW`, require a regular descriptor beneath the configured root, and copy from that verified descriptor. | Gate 1 slice 1C verification. |
| MV-SEC-012 | `DEFERRED BY PRODUCT DECISION` | The current global single-admin model has no authorization entities. Multi-user/MFA/SSO is explicitly not a v5.1 feature. | Gate 11; it becomes a release blocker before any multi-user feature ships. |
| MV-SEC-013 | `RESOLVED IN GATE 1 SLICE 1C CANDIDATE` | ZIP downloads sanitize every folder, model, primary-file, and supporting-file path component; ZIP imports reject traversal and normalized duplicate paths. | Gate 1 slice 1C verification. |
| MV-SEC-014 | `PARTIALLY MITIGATED` | Lazy/cached preview work reduces normal load, but synchronous browser decompression and parser work still lacks complete size/time/complexity budgets. | Gate 2. |
| MV-SEC-015 | `CONFIRMED` | Nginx sets cache policy but no complete CSP, nosniff, referrer, permissions, frame, or trusted-host baseline. | Gate 1, validated against WASM/workers/blob and proxy modes. |
| MV-SEC-016 | `PARTIALLY RESOLVED IN CANDIDATE` | 8,311 generated/runtime paths were removed from Git tracking without deleting local files; root ignore policy, source-owned verification, CI, and Dependabot now exist. Checksums, SBOMs, signing, and release provenance remain. | Gate 0 for source hygiene; Gate 5 for release artifacts. |

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

Gate 0 may pass with confirmed product vulnerabilities because its purpose is to
make those facts reproducible and assign them. Gate 1 may not pass until all
confirmed P0 findings have regression evidence or an explicit, owned compensating
control. No current result supports unrestricted Internet exposure.

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
