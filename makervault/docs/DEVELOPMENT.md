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

0. Ruff (API) and ESLint (web) gates; `make verify-lint` runs them alone.
1. API migration tests under Python 3.11.
2. Web TypeScript checking, Vitest tests, and the production Vite build under
   Node 20.
3. Bridge tests and compilation under Go 1.21.13.
4. Validation of the local, canonical production, historical alias, and smoke
   Compose configurations.
5. A clean container smoke test with temporary named volumes, HTTP health checks,
   non-root runtime assertions, and schema-version verification.

The smoke test uses host ports `18000` and `15173` by default. Override them only
when necessary:

```bash
MAKERSVAULT_SMOKE_API_PORT=28000 \
MAKERSVAULT_SMOKE_WEB_PORT=25173 \
make verify-smoke
```

The smoke project is removed with its named volumes on success, failure, or
interruption. It does not use `makervault/data` and does not open `api/app.db`.

## Fast gate for individual tickets

```bash
make verify-fast
```

Runs ruff + pytest (API), eslint + tsc + vitest (web, no production build) and
`go test ./...` (bridge) on the host toolchains in about a minute. It needs a
repo-local `.venv` (created with `uv venv --python 3.12 .venv`, then
`uv pip install -r requirements.lock -r requirements-dev.lock ruff` from
`makervault/api/`) and `npm ci` once in `makervault/web/`. Use it per ticket,
then `make verify` once per wave; the full gate is still required per ticket for
anything touching migrations, Dockerfiles, nginx, compose manifests or locks.

## Focused verification

```bash
make verify-api
make verify-web
make verify-bridge
make verify-compose
make verify-smoke
```

CI invokes these same targets. A local workaround that CI does not execute is not
release evidence.

## Schema migration rules

- Add the next immutable `Migration` entry in `api/migrations.py`.
- Never rename or reuse an applied version.
- Add fresh, prior-version, repeated-run, failure, and restore-oriented tests as
  applicable.
- Do not test against or commit a user's runtime database.
- A release that changes schema must document its supported source versions and
  matched database/storage restore procedure.
