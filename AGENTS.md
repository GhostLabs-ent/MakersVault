# AGENTS.md — working in Curiarium

Orientation for an AI agent (or a new contributor) picking this repository up cold. Read
this, then the ticket store, then the docs index. Everything here is current as of
`main`; if something contradicts the code, the code wins and this file needs fixing.

## What this is

Curiarium is a self-hosted, household-scale vault for 3D print files: a FastAPI + SQLite
backend, a React + Vite frontend, and a small Go bridge for slicer handoff. MIT, forked
from MakersVault. **It is not a SaaS and not multi-tenant** — one library, a few users,
one or two printers.

## Repository layout

```
curiarium/api/            FastAPI backend (18 routers, SQLModel, versioned migrations)
  routers/                one module per feature surface; main.py is only app wiring
  migrations.py           append-only schema ledger (currently 12) - see ADRs 0002
  permissions.py          ROUTE_PERMISSIONS matrix; refuses to boot on an unclassified route
  audit.py                append-only audit actions; refuses to boot on uncovered mutations
  snapshots.py            snapshot providers: CephFS .snap, ZFS, BTRFS sidecar, null
  mfa.py / oidc.py / sessions.py / accounts.py   identity surface
  safe_http.py            no-redirect, IP-pinned HTTP client for all outbound fetches
  multipart_stream.py     streams uploads straight to storage (no /tmp spool)
  tests/                  ~1841 tests; conftest pins the environment
curiarium/web/            React 18 + Vite + Tailwind
  src/ui/asset-grid/      the virtualised grid, cards, preview queue
  src/ui/settings/        settings sections
  src/lib/api/            per-domain HTTP clients behind a barrel
  public/                 generated brand assets (icons, manifest, og-image)
curiarium/slicer-bridge/  Go protocol handler (curiarium-slicer://, curiarium-engrave://)
curiarium/scripts/        container-smoke.sh, wave_plan.py, check_version.py
curiarium/docs/           ADRs, CONFIGURATION, ARCHITECTURE_RUNBOOK, DEVELOPMENT, archive/
docs/                     TICKET_WORKFLOW.md, PERMISSIONS.md, AUDIT.md, brand/
.tickets/                 local ticket store (gitignored, tk)
```

`main.py` must stay wiring only. New endpoints go in a router, get classified in
`permissions.py`, and — if mutating — get an audit action or a recorded exemption.

## Commands

```bash
make verify-fast   # ~90 s: ruff+pytest (api), eslint+tsc+vitest (web), go test (bridge)
make verify        # full gate: lint in images, API, web build, bridge, compose, container smoke
make verify-api    # one layer at a time: -api, -web, -bridge, -compose, -smoke, -lint
```

`make verify-fast` uses a repo-local `.venv` if present:

```bash
uv venv --python 3.12 .venv
uv pip install -r curiarium/api/requirements.lock -r curiarium/api/requirements-dev.lock ruff
cd curiarium/web && npm ci
```

**Verification policy:** fast gate per change; **one** full `make verify` per batch, on
integrated `main`, before the release/publish step. No per-change full gates.

## Guardrails — the things that have actually bitten us

1. **Migrations are append-only and immutable.** Never edit an applied migration; add the
   next number. A database records version *and* name and will refuse to start on a
   mismatch.
2. **Never bind a security invariant to private third-party internals.** The permission
   guard enumerated routes from `app.routes` until fastapi's lazy route tree made that
   return nothing; it now walks our own routers, with a cardinality assertion so an empty
   walk cannot pass.
3. **Any test that reads repo-root files needs the module-skip idiom.** The API image's
   build context is `curiarium/api`, so `parents[3]` raises in-container. This defect has
   shipped three times.
4. **Destructive-path tests use temp directories.** Never a real network mount, never
   the real storage root, never a live deployment.
5. **Never merge, rebase or cherry-pick upstream.** The trees diverged deliberately (see
   `Mf-n60k` in the ticket store). Port by hand, one change at a time.
6. **Two serialisers decide whether work can run in parallel**: `curiarium/scripts/` entry
   points, lockfiles, `Makefile`, CI, `nginx.conf`, `conftest.py`, migrations, and shared
   contract files. `curiarium/scripts/wave_plan.py` is the authority on this.
7. **The app must keep working with auth disabled.** The deployment behind a portal gate
   runs with `AUTH_USERNAME`/`AUTH_PASSWORD` empty: `/health` reports
   `auth_required:false`, routes are open, `/login` returns 503. Every auth change is
   tested against both modes.

## Working with the ticket store

```bash
tk list | tk ready | tk blocked      # the queue
tk show <id>                         # scope + acceptance (the source of truth)
tk close <id> ; tk add-note <id> "..."
```

Batches are driven by the loop in [docs/TICKET_WORKFLOW.md](docs/TICKET_WORKFLOW.md):
oracle plan-gate before code, oracle commit-gate before commit, one commit per ticket
with the ticket ID in the subject, fast gate per ticket, one full gate per batch.
Artifacts the loop writes are gitignored: `.tickets/`, `.plans/`, `.lanes/`.

## Conventions

- Commit subjects: `Mf-xxxx: <what changed>` for ticket work, `deps(<scope>):` for
  Dependabot, otherwise a plain imperative subject.
- Python: ruff (`E,F,I,B`, line length 140, `E501` ignored), no type gate yet, prefer
  explicit functions over lambdas.
- TypeScript: strict, eslint with the two classic hook rules only; no `any` in new code
  without a comment.
- Docs: if behaviour changes, the doc that claims it changes too. Facts that drift in this
  repo have historically been version numbers, schema versions, route counts and image
  names.

## Where to read next

| Question | Document |
|---|---|
| What does every setting do? | [curiarium/docs/architecture/CONFIGURATION.md](curiarium/docs/architecture/CONFIGURATION.md) |
| How is it put together, and how do I recover it? | [curiarium/docs/ARCHITECTURE_RUNBOOK.md](curiarium/docs/ARCHITECTURE_RUNBOOK.md) |
| Why is it like this? | [curiarium/docs/adr/](curiarium/docs/adr/) |
| Who may do what? | [docs/PERMISSIONS.md](docs/PERMISSIONS.md) |
| What gets audited? | [docs/AUDIT.md](docs/AUDIT.md) |
| How do batches run? | [docs/TICKET_WORKFLOW.md](docs/TICKET_WORKFLOW.md) |
| Brand assets | [docs/brand/build.py](docs/brand/build.py) |
| Everything else, and what is historical | [curiarium/docs/README.md](curiarium/docs/README.md) |
