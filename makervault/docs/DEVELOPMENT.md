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

The smoke test picks a free host-port lane, so a single run still lands on the
historical `18000` (API) and `15173` (web) whenever those are free. Lanes are
10 ports apart:

| Lane | API port | Web port |
| ---- | -------- | -------- |
| 0    | 18000    | 15173    |
| 1    | 18010    | 15183    |
| 2    | 18020    | 15193    |

`MV_LANE=1 make verify-smoke` pins a lane and fails fast if that lane is
already claimed by another run or either of its ports is busy. With `MV_LANE`
unset the script scans lanes 0-2 in order and takes the first that is both
unclaimed and has two free ports. A lane is claimed atomically with a lock
directory under `/tmp/makersvault-smoke-lanes/` (POSIX `mkdir` is atomic), not
merely probed: `compose up --build` needs minutes before it binds the ports, so
a probe alone would let two simultaneous runs pick the same lane. A run killed
hard leaves a stale lock, and the next run checks the recorded pid and takes
over automatically. The documented port overrides still win and disable both
scanning and locking:

```bash
MAKERSVAULT_SMOKE_API_PORT=28000 \
MAKERSVAULT_SMOKE_WEB_PORT=25173 \
make verify-smoke
```

The smoke project is removed with its named volumes and its images on success,
failure, or interruption. It does not use `makervault/data` and does not open
`api/app.db`.

## Parallel-safe verification

Two verification runs may share one host and one Docker daemon. Every mutable
thing a run creates is namespaced by `MV_RUN_ID`:

- the API test database and storage root, under
  `/tmp/makersvault-tests/<run id>/`;
- the four image tags (the repository names are unchanged, only the `:` tag is
  per run);
- the smoke Compose project name, and therefore its container names and named
  volumes;
- the smoke host ports, selected per lane as described above.

The default run id is the pid of the `make` process plus the worktree directory
name, sanitised to `[a-z0-9_-]`. Set `MV_RUN_ID` yourself to join a named lane,
for example `MV_RUN_ID=Mf-ly4o make verify`; values are lowercased and
sanitised, so that id becomes `mf-ly4o`. `make verify-fast` runs pytest on the
host and inherits the id, so a lane's database, storage and images share one
name. The `verify-api` container derives its own id from its pid instead: a
container has a private `/tmp`, so it has nothing to share with another run. The
smoke project is named `makersvault-gate0-smoke-<run id>`, so two runs never
share container names or named volumes.

A plain `make verify` is otherwise unchanged: same targets, same commands, and
it still lands on `18000`/`15173` whenever those are free. Each run removes the
images it built (the make targets remove theirs after use, and the smoke project
is torn down with `--rmi local`), so per-run tags do not accumulate.

A run killed hard (SIGKILL before the interpreter exits) can leave
`/tmp/makersvault-tests/<run id>/` behind. That directory is safe to delete and
belongs to no other run. It can also leave lane locks under
`/tmp/makersvault-smoke-lanes/`; those are reclaimed from their recorded pid
automatically, but `rm -rf /tmp/makersvault-smoke-lanes/*` clears them if a
stale lock ever blocks a run.

A run never deletes a database it did not create, so pointing `DB_URL` and
`FILE_STORAGE` at fixed paths keeps that data for investigation after the run
finishes.

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
