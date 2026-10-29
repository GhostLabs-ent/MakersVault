# Gate 0 Security Finding Revalidation

**Status:** Evidence review

**Revalidated:** 2026-08-13

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
| MV-SEC-001 | `CONFIRMED` | The bridge accepts any HTTP(S) `url`, downloads it, and can fall back to the OS default opener. Gate 0 tests only establish its current parser boundary. | Gate 1: scoped, short-lived handoff grants; origin, role, size, redirect, and opener restrictions. |
| MV-SEC-002 | `CONFIRMED` | `api/auth.py`, production Compose, `.env.example`, and README still contain known credential/signing fallbacks or examples. | Gate 1: secure first-run/explicit environment and compatibility migration. |
| MV-SEC-003 | `CONFIRMED` | Initial and final URL strings are validated, but `urllib` resolves/connects and follows redirects before final validation. DNS/redirect TOCTOU remains unproven. | Gate 1: controlled redirect/connection implementation and adversarial tests. |
| MV-SEC-004 | `CONFIRMED` | `python-multipart==0.0.9` remains pinned. Current `pip-audit` reports multiple records with fixes in newer releases. | Gate 1: compatible dependency upgrade plus upload regression tests. |
| MV-SEC-005 | `CONFIRMED` | `Pillow==10.4.0` remains pinned and processes user-controlled images. Current `pip-audit` reports multiple fixed advisories. | Gate 1: upgrade and malicious/oversized-image tests. |
| MV-SEC-006 | `CONFIRMED` | Remote imports and generated thumbnails have some per-file bounds, but direct primary/supporting uploads and total ZIP expansion are not consistently bounded. | Gate 1 for server limits; Gate 2 for browser preview budgets. |
| MV-SEC-007 | `CONFIRMED` | The API accepts `?token=` and the web client appends the primary JWT to file URLs and bridge handoffs. Threat model and interim acceptance are ADR 0004; the signed-grant implementation is ticket `M3-7bb7`. | Gate 1: narrow signed file/handoff grants; implementation in `M3-7bb7`, decided in ADR 0004. |
| MV-SEC-008 | `CONFIRMED` | The primary JWT is stored in browser `localStorage`. The HttpOnly-cookie remediation was explicitly declined for v5.1 with compensating controls (15-minute access-token TTL, single-use rotation, `UserSession` revocation store); see ADR 0004. | Gate 1 risk decision: accepted in ADR 0004 with compensating controls; final session architecture in Gate 11. |
| MV-SEC-009 | `PARTIALLY MITIGATED` | Login throttling (`api/login_throttle.py`) and a `UserSession` revocation store (`api/sessions.py`) now exist, so the original "no throttle, no revocation" evidence is stale. Residual: replay of an already-rotated refresh token is not yet treated as theft (Mf-7op4) and full session lifecycle is deferred. | Gate 1 residual for single-admin abuse controls; Gate 11 for full session lifecycle; mitigations recorded in ADR 0004. |
| MV-SEC-010 | `RESOLVED IN CANDIDATE` | The current multi-stage web image builds with Vite and serves only static output through `nginxinc/nginx-unprivileged`; the container smoke test observes web PID 1 as UID 101. | Gate 0 verification; Gate 1 still owns headers and host policy. |
| MV-SEC-011 | `CONFIRMED` | Mounted copy mode uses `is_file`, `stat`, and `shutil.copyfile` without rejecting or re-checking resolved symlink targets. | Gate 1. |
| MV-SEC-012 | `DEFERRED BY PRODUCT DECISION` | The current global single-admin model has no authorization entities. Multi-user/MFA/SSO is explicitly not a v5.1 feature. | Gate 11; it becomes a release blocker before any multi-user feature ships. |
| MV-SEC-013 | `CONFIRMED` | ZIP output paths concatenate user-controlled folder/model/supporting filenames without normalizing every archive component. | Gate 1 or the earliest ZIP hardening change. |
| MV-SEC-014 | `PARTIALLY MITIGATED` | Lazy/cached preview work reduces normal load, but synchronous browser decompression and parser work still lacks complete size/time/complexity budgets. | Gate 2. |
| MV-SEC-015 | `CONFIRMED` | Nginx sets cache policy but no complete CSP, nosniff, referrer, permissions, frame, or trusted-host baseline. | Gate 1, validated against WASM/workers/blob and proxy modes. |
| MV-SEC-016 | `PARTIALLY RESOLVED IN CANDIDATE` | 8,311 generated/runtime paths were removed from Git tracking without deleting local files; root ignore policy, source-owned verification, CI, and Dependabot now exist. Checksums, SBOMs, signing, and release provenance remain. | Gate 0 for source hygiene; Gate 5 for release artifacts. |
| MV-SEC-017 | `CONFIRMED` | Browser-proxied MakerWorld/Thingiverse session cookies post-date this review (Mf-vesa, `baf2b78`): session-scoped by default with an opt-in persistence toggle, sent as body fields to the API and proxied only to a closed credentialed-host registry, never persisted server-side and never logged. A remembered cookie is exposed to origin JavaScript and is a live third-party credential. | ADR 0004 threat model; residual owned there. |

## Dependency scan evidence

### Python runtime

Command basis: `pip-audit -r api/requirements.lock` against the resolved Python
3.12 API environment, re-measured for Mf-9azr after `sqlmodel` moved to `0.0.39`
and `uvicorn` moved to `0.52.1`.

Result: 118 advisory rows (83 distinct advisory identifiers) across four pinned
packages:

- `starlette==0.38.5` (14 rows)
- `python-multipart==0.0.9` (14 rows)
- `pillow==10.4.0` (66 rows)
- `PyJWT==2.9.0` (22 rows)

The count includes duplicate/overlapping advisory records returned by the audit
service, so the earlier 52-record figure is not comparable row for row with this
one; it is a re-measurement, not growth attributable to Mf-9azr. The `sqlmodel`
and `uvicorn` bumps added no advisories, and no advisory names `fastapi`,
`pydantic` or `SQLAlchemy` at the versions now pinned.

Every recorded starlette advisory is fixed only in `>=0.40`, while
`fastapi==0.115.0` requires `starlette<0.39`. The starlette rows therefore cannot
be cleared by a starlette bump alone; they clear with the FastAPI/Starlette pair
on `Mf-0bl6`. Gate 1 must select that compatible FastAPI/Starlette/Pydantic set
and test the upgrade; the record is not a recommendation to install isolated
transitive versions blindly.

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
