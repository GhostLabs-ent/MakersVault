# MakersVault Development Verification

## Prerequisites

- Docker with Docker Compose.
- GNU Make.
- `curl` for the container health check.

Host Python, Node, and Go installations are optional because the source-owned
verification targets use versioned container toolchains. Release image digests
are recorded later at the release-candidate gate.

Python direct dependencies are declared in `requirements.txt` and
`requirements-dev.txt`. The successful Python 3.11/Linux environments are frozen
in `requirements.lock` and `requirements-dev.lock`; Docker and CI install the lock
files.

## Complete verification

From the repository root:

```bash
make verify
```

This performs:

1. API migration tests under Python 3.11.
2. Web TypeScript checking, Vitest tests, and the production Vite build under
   Node 20.
3. Bridge tests and compilation under Go 1.26.6.
4. Validation of the local, canonical production, historical alias, and smoke
   Compose configurations.
5. A clean container smoke test with temporary named volumes, HTTP health checks,
   non-root runtime assertions, and schema-version verification.
6. A Chromium virtual-authenticator passkey workflow in its own disposable project.
7. The static release identity/publication contract check.

`make verify` is not the complete release qualification. Gate 13A identified that
the older preview/organization/mounted-import and exact-image harnesses still use
JWT Bearer auth, and recovery/release drills assert schema 5. Their historical
results remain valid for their named baselines; they need current cookie/CSRF and
schema handling before rerunning against later development. See the
[Gate 13 audit](evidence/gate-13/SUBGATE_13A_RESULTS.md) for the tracked repairs and
remaining lifecycle/browser/platform evidence. Do not re-enable obsolete auth to
make a harness pass.

The smoke test uses host ports `18000` and `15173` by default. Override them only
when necessary:

```bash
MAKERSVAULT_SMOKE_API_PORT=28000 \
MAKERSVAULT_SMOKE_WEB_PORT=25173 \
make verify-smoke
make verify-passkeys
```

The smoke project is removed with its named volumes on success, failure, or
interruption. It does not use `makervault/data` and does not open `api/app.db`.

## Focused verification

```bash
make verify-api
make verify-web
make verify-bridge
make verify-compose
make verify-smoke
make verify-passkeys
make verify-release
```

CI invokes these same targets. A local workaround that CI does not execute is not
release evidence.

The passkey drill installs locked Playwright dependencies inside a disposable
container and drives Chromium with a virtual authenticator through registration,
identity confirmation, required-Administrator policy, logout, and password-plus-
passkey login. It runs against an isolated local Compose project on ports `18005`
and `15178`, removes its own volumes afterward, and writes a secret-free result to
`benchmarks/organization/.artifacts/passkey-browser.json`. This validates the browser
and server integration; physical device and operating-system credential prompts
still need release qualification on the supported platforms.

## Schema migration rules

- Add the next immutable `Migration` entry in `api/migrations.py`.
- Never rename or reuse an applied version.
- Add fresh, prior-version, repeated-run, failure, and restore-oriented tests as
  applicable.
- Do not test against or commit a user's runtime database.
- A release that changes schema must document its supported source versions and
  matched database/storage restore procedure.
