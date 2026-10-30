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
| MV-SEC-005 | `CONFIRMED` | `Pillow==12.3.0` remains pinned and still processes user-controlled images; `pip-audit` still reports 39 advisory rows against it, every one fixed at exactly `13.0.0`; the `10.4.0 -> 12.3.0` bump (Mf-xzei) net-cleared 27 rows / 11 distinct advisory identifiers. | Gate 1: malicious/oversized-image tests (upgrade landed in Mf-xzei); reassess Pillow >= 13.0.0. |
| MV-SEC-006 | `CONFIRMED` | Remote imports and generated thumbnails have some per-file bounds, but direct primary/supporting uploads and total ZIP expansion are not consistently bounded. | Gate 1 for server limits; Gate 2 for browser preview budgets. |
| MV-SEC-007 | `RESOLVED IN CANDIDATE` | `?token=` is retired: `require_auth` in `api/auth.py` is header-only, so a session token in the query string is a 401 on every route, the four file routes included. Those four accept a `?sig=` file grant instead - one path, `scope="file:read"`, 60 s TTL with the verifier independently capping `exp - iat` at 300 s, bound to a live session so sign-out invalidates it, signed with the domain-separated subkey `file_grant_key()`, and mintable only by `POST /file-grants` (READ) from a four-template, existence-checked allow-list. The access-log and error-log surfaces are closed: `web/nginx.conf` binds `log_format curiarium` (`$request_method $uri $server_protocol`, never `$request`, plus query-free `$upstream_addr`/`$upstream_status`), disables request-time error logging with `error_log /dev/null` (nginx has no error-log format and embeds the request line in upstream failures), `api/Dockerfile` runs uvicorn with `--no-access-log`, and `scripts/container-smoke.sh` sends a live canary and then a dead-upstream canary and fails the smoke run if the canary, `?token=` or `?sig=` reaches any container log. Pinned by `api/tests/test_file_grants.py`, `api/tests/test_operator_log_hygiene.py` and `api/tests/test_auth_users.py::test_query_token_no_longer_authorizes`; design in ADR 0005, tickets `M3-7bb7` and `Mf-c80i`. Residual: browser history, copied URLs, screenshots and `Referer` still see a 60-second read-only grant, and no CSP baseline exists yet (MV-SEC-015). | Gate 0 verification suite must stay green before release; ADR 0004 recorded the interim acceptance and ADR 0005 supersedes it for the implemented design, landed in `M3-7bb7` (error-log closure in `Mf-c80i`). |
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

Command basis: `pip-audit -r api/requirements.lock --no-deps` against Python
3.12, re-measured for Mf-0bl6 after `fastapi` moved `0.115.0 -> 0.141.1` and
`starlette` moved `0.38.5 -> 1.10.0`. The pair is coupled, not independent:
fastapi 0.115.0 requires `starlette<0.39`, fastapi 0.141.1 requires
`starlette>=0.46.0` (resolved: 1.10.0), and the bump adds one transitive
dependency, `annotated-doc==0.0.5`.

Before the bump, same tool and command, 2026-10-29: 116 advisory rows (81
distinct advisory identifiers) across four pinned packages -
`starlette==0.38.5` (14 rows), `python-multipart==0.0.9` (14), `pillow==10.4.0`
(66), `PyJWT==2.9.0` (22).

After the bump, same tool and command, 2026-10-29: 102 advisory rows (74
distinct advisory identifiers) across three pinned packages:

- `pillow==10.4.0` (66 rows)
- `PyJWT==2.9.0` (22 rows)
- `python-multipart==0.0.9` (14 rows)

All 14 starlette rows are cleared by the pair this ticket landed: every advisory
recorded against 0.38.5 is fixed no earlier than `0.40.0` and the newest only at
`1.3.1`, so 1.10.0 clears them and adds none. No advisory names
`fastapi==0.141.1`, `annotated-doc==0.0.5`, `pydantic` or `SQLAlchemy` at the
versions now pinned.

The counts include duplicate/overlapping advisory records returned by the audit
service, and the advisory database itself moves, so these figures are not
comparable row for row with an earlier measurement (the Mf-9azr record was 118
rows / 83 identifiers for the same lock). They are re-measurements, not changes
attributable to a bump.

Two residuals are owned explicitly rather than dropped silently:

- `python-multipart==0.0.9` (14 rows) is untouched here. The Mf-0bl6 acceptance
  criteria exclude the floor and its CVEs; the multipart upload path is covered
  by the API suite, but the pin stays until Gate 1 raises it (MV-SEC-004
  remains `CONFIRMED`).
- `starlette.testclient` now prefers `httpx2` and emits a
  `StarletteDeprecationWarning` when it falls back to the `httpx==0.27.2` the
  verification lock pins. This is test-only with no production exposure - the
  warning comes from the test client, not the runtime image - and moving the
  development lock to `httpx2` is a follow-up owned outside Mf-0bl6.

Mf-xzei then moved the pin `10.4.0 -> 12.3.0` in all three files
(`requirements.txt:9`, `requirements.lock:16`, `requirements-dev.lock:17`).
Same command and tool, `pip-audit 2.10.1`, measured 2026-10-29 against
`pillow==12.3.0`: 75 advisory rows (63 distinct advisory identifiers) across
three pinned packages - `pillow==12.3.0` (39 rows), `PyJWT==2.9.0` (22) and
`python-multipart==0.0.9` (14). The latter two are unchanged by this bump;
before it, same tool and command, the same lock was 102 rows (74 identifiers)
with `pillow==10.4.0` at 66 rows. The move decomposes gross as 33 rows / 17
distinct identifiers cleared and 6 identifiers newly applicable to 12.3.0, all
of them fixed at `13.0.0`; 33 cleared minus 6 added is the 27-row net and 17
minus 6 the 11-identifier net. All 39 remaining pillow rows are fixed at
exactly `13.0.0` - nothing in 12.3.0 is fixable below that, which is why
MV-SEC-005 stays `CONFIRMED`. The byte identity of generated thumbnails between
the two Pillow versions is a wheel artefact, not a guarantee this record relies
on.

### Web runtime and development toolchain

- The web build image moved node 20 -> node 24 LTS (`node:20-alpine` ->
  `node:24-alpine`) and npm 10 -> npm 11; npm 11.11+ persists `libc` metadata
  in lock entries where npm 10.9.x never did, which a future re-resolution
  will surface as `libc`-only additions. On this lock it was a no-op: the
  committed lock already satisfied every declared range, npm rewrote it
  byte-identically, diff empty (0 of ~500 entries, `lockfileVersion` 3, both
  `version` fields `5.2.0-rc.1`). No dependency version moves, so the recorded
  `npm audit` / advisory set below is unchanged, its counts still applying.
- `npm audit --omit=dev`: zero known vulnerabilities (re-measured for Mf-9azr
  after `fflate` moved to `0.8.3` and `lucide-react` moved to the `1.x` line).
- Full `npm audit`: ten development-toolchain vulnerabilities as of this
  re-measurement - 2 critical (`vitest`, `tinypool`), 4 high (`vite`,
  `source-map-js`, `browserslist`, `brace-expansion`) and 4 moderate
  (`esbuild`, `@vitest/mocker`, `postcss-selector-parser`,
  `baseline-browser-mapping`). The advisory set has grown since the two findings
  recorded at Gate 0; none of it is attributable to Mf-9azr, whose `fflate` and
  `lucide-react` bumps name neither package. All of it is cleared by the Vite 5
  -> 7 / Vitest 3 -> 4 toolchain upgrade tracked on `Mf-qj7j`.
- The critical advisory initially exposed by the new test dependency was removed
  by moving Vitest to `3.2.6`; a later critical (`vitest`/`tinypool`) has since
  been published against that same version and is owned by `Mf-qj7j`. Tests and
  production build are re-run by CI.

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
