# Gate 1 Slice 1B Evidence

**Slice:** Compatible dependency and toolchain upgrades

**Status:** Locally verified

**Evidence date:** 2026-08-14

**Findings:** MV-SEC-004, MV-SEC-005, and the Gate 0 build-toolchain residual

## Starting evidence

- `pip-audit` reported 52 overlapping advisory records in Starlette 0.38.5,
  Pillow 10.4.0, PyJWT 2.9.0, and python-multipart 0.0.9.
- Full `npm audit` reported one high and one moderate development-toolchain
  finding through Vite 5/esbuild. Production dependencies were clean.
- The bridge passed under Go 1.21.13, but that toolchain was no longer the
  supported release baseline.

## Candidate sets

### Python 3.11 runtime

| Package | Starting | Candidate |
|---|---:|---:|
| FastAPI | 0.115.0 | 0.141.1 |
| Starlette | 0.38.5 | 1.6.0 |
| python-multipart | 0.0.9 | 0.0.32 |
| Pillow | 10.4.0 | 12.3.0 |
| PyJWT | 2.9.0 | 2.13.0 |

The complete runtime and development locks were regenerated from the direct
requirements under Python 3.11. The test-only client moved from HTTPX 0.27.2 to
HTTPX2 2.9.0 after the upgraded Starlette emitted a deprecation warning for the
legacy adapter. Pytest moved from 8.3.5 to 9.0.3 after the development-lock audit
identified a fixed advisory in the old test runner.

### Web build toolchain

| Package | Starting | Candidate |
|---|---:|---:|
| Vite | 5.x | 8.2.1 |
| Vitest | 3.2.6 | 4.1.10 |

The npm lock was regenerated with lifecycle scripts disabled. The application
continues to build under the existing Node 20 container, which currently resolves
to Node 20.20.2 and satisfies the candidate engines.

### Bridge toolchain

The Go language directive is 1.26 and the reproducible verification image is
`golang:1.26.6`.

## Verification

| Check | Result |
|---|---|
| Python runtime lock audit | Pass; zero known vulnerabilities |
| Python development lock audit | Pass; zero known vulnerabilities |
| API/migration tests | Pass; 19 tests |
| npm production and full audit | Pass; zero findings |
| Web type check, tests, and production build | Pass |
| Bridge tests and build under Go 1.26.6 | Pass |
| `govulncheck ./...` under Go 1.26.6 | Pass; no vulnerabilities found |
| Compose validation and container smoke | Pass |
| Complete repository harness | Pass; `make verify` |

The existing generated-bundle size warning remains assigned to Gate 2. No new
application warning remains: the transient Starlette/HTTPX warning was resolved
before this evidence was accepted.

## Compatibility and rollback

No application schema, API contract, stored file, or browser workflow changed.
Rollback restores the previous requirement manifests, lockfiles, Node packages,
Go directive, and verification image. No data restoration is required.

## Residual risk and next slice

Dependency upgrades remove known advisory records but do not bound hostile input.
Slice 1C must still enforce upload, archive, image, model, time, and storage
budgets and prove ZIP-path and mounted-symlink containment.
