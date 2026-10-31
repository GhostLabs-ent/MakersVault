# Contributing to Curiarium

Thanks for helping. This is a self-hosted vault for 3D-print files — a household library,
not a storefront — and it is developed in the open under the MIT licence.

Two things make this repository unusual, and both are worth knowing before your first
commit:

1. It is an **independent fork** of [GhostLabs-ent/MakersVault](https://github.com/GhostLabs-ent/MakersVault).
   The two lines have diverged structurally (this fork rebuilt identity, folders, projects
   and snapshots), so features are **ported by hand, one at a time**. Never merge, rebase or
   cherry-pick `upstream` into this repository.
2. Two boot guards refuse to start the API if you forget them: every route must be
   classified in `permissions.ROUTE_PERMISSIONS`, and every mutating route needs an audit
   action or a recorded exemption in `audit.py`. This is by design; see
   [PERMISSIONS.md](docs/PERMISSIONS.md) and [AUDIT.md](docs/AUDIT.md).

## Getting it running

```bash
uv venv --python 3.12 .venv
uv pip install -r curiarium/api/requirements.lock -r curiarium/api/requirements-dev.lock ruff
cd curiarium/web && npm ci && cd ../..

make verify-fast          # ~90 s: ruff + pytest, eslint + tsc + vitest, go test
```

For the full stack, `docker compose` against the manifest for your target, or build the
backend and run `uvicorn main:app` from `curiarium/api` with `AUTH_MODE=local`. State this
repository does not want in git is covered by `.gitignore`; do not fight it.

## The gates

```bash
make verify-fast    # per change
make verify         # once per batch, on integrated main, before a release or publish
make verify-api     # one layer at a time: -api, -web, -bridge, -compose, -smoke, -lint, -version
```

**Policy: the fast gate per change, and exactly one full `make verify` per batch.** Not one
per commit — it builds container images and takes minutes.

Three rules that will otherwise bite you:

- **Migrations are append-only and immutable.** Add a new numbered migration; never edit a
  landed one (`curiarium/api/migrations.py`, ADR [0002](curiarium/docs/adr/0002-versioned-sqlite-migrations.md)).
- **`main.py` stays wiring only.** New endpoints live in a router.
- **Tests that touch destructive paths use temporary directories.** Never a real mount, never
  a real library.

## Commits and review

- Commit subjects: `Mf-xxxx: <what changed>` when the work has a ticket, `deps(<scope>):` for
  dependency updates, otherwise a plain imperative subject.
- One logical change per commit, and say *why* in the body — the diff explains what.
- `main` is protected: no force-push, no deletion. Open a pull request and let CI run
  (`Verify` covers api, web, bridge and containers; `Publish` only runs on `main`).
- Never commit secrets, databases, `dist/`, `node_modules/`, `.venv/`, or anything from
  `.tickets/`, `.plans/`, `.lanes/` or `.pi/`.
- Do not publish private paths, hostnames or another project's names in tracked files.

## Documentation

Documentation has two roots, split by purpose. Put a document where it belongs rather than
where it is convenient:

| Location | What belongs there |
|---|---|
| `docs/` | Contracts and process: `PERMISSIONS.md`, `AUDIT.md`, `TICKET_WORKFLOW.md` |
| `curiarium/docs/` | The product: runbook, configuration, reverse proxy, development, `adr/` |
| `curiarium/docs/archive/` | Historical writing from the pre-fork era — **never edited** |

Every product document must be listed in [curiarium/docs/README.md](curiarium/docs/README.md),
in the correct table. That index is how a reader tells authoritative current documentation
from archaeology.

If behaviour changes, the document that claims the behaviour changes in the same commit.
Facts that have historically drifted here: product version, schema version, route counts,
test counts, and image names. Grep for the number you just changed before you close a pull
request.

### Architecture decision records

An ADR is required for a decision someone would otherwise relitigate: storage layout,
authentication, migration strategy, threat models. They live in `curiarium/docs/adr/` and
are numbered sequentially (`0009-…` is next). Use the same four headings as the existing
ones, all of them:

```markdown
# 0009. The decision in one line

## Context
## Decision
## Consequences
## Alternatives considered
```

A test (`curiarium/api/tests/test_adr_collection.py`) rejects an ADR that drops a heading or
the entry in the docs index, so run `make verify-fast` after adding one.

### Images in documentation

Figures live in [`docs/images/`](docs/images/README.md), organised by topic, and are
referenced with a relative path from the document that embeds them. Read that file before
your first screenshot: it covers naming, format and size limits, the mandatory alt text, and
the redaction rules. The redaction rules are not optional — this repository is public, so a
screenshot must never show a real username, hostname, library, token or signed URL.

Brand artwork is generated: edit the sources and run `docs/brand/build.py` rather than
hand-editing files in `docs/brand/`.

## Where to read next

| Document | Why |
|---|---|
| [AGENTS.md](AGENTS.md) | Repository map, commands and the guardrails that have actually bitten us |
| [docs/TICKET_WORKFLOW.md](docs/TICKET_WORKFLOW.md) | How work is planned, gated and landed |
| [curiarium/docs/README.md](curiarium/docs/README.md) | The documentation index: what is current, what is historical |
| [curiarium/docs/DEVELOPMENT.md](curiarium/docs/DEVELOPMENT.md) | Toolchains, local workflow, migration rules |
| [curiarium/docs/ARCHITECTURE_RUNBOOK.md](curiarium/docs/ARCHITECTURE_RUNBOOK.md) | How the system fits together, failure modes, recovery |
| [docs/PERMISSIONS.md](docs/PERMISSIONS.md) · [docs/AUDIT.md](docs/AUDIT.md) | The role matrix and the audit ledger |

## Licence

Curiarium is MIT licensed. By contributing you agree your work is released under the same
terms; the file keeps the original copyright notice and this fork's, and the reasoning is in
[NOTICE](NOTICE).
