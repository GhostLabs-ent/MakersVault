# Ticket Completion Workflow (scheduler / oracle-gated)

This project completes work tickets through a **scheduler → orchestrator →
oracle** pipeline so every ticket gets an Oracle plan-gate and commit-gate,
independent verification, and a clean one-commit-per-ticket landing.

Adapted from `~/ggreq_agent/docs/project_notes/TICKET_WORKFLOW.md` and
`~/card_event_tracker/.pi/agents/scheduler.md`, which in turn use the global
`oracle-gated-ticket-batch` skill.

## Roles
- **scheduler** (`.pi/agents/scheduler.md`) — drives an ordered list of tickets
  one-at-a-time. For each: shows the ticket, launches the orchestrator
  (FOREGROUND, via the Agent tool), then trust-but-verifies the ticket is closed
  and the suite is green before moving on. Produces a per-ticket report.
- **orchestrator** (built-in Pantheon orchestrator) — plans, delegates to
  specialists (oracle / fixer / explorer / designer), plumbs, commits, verifies.
- **oracle** — the review authority: approves the plan (plan-gate) before code,
  and the diff (commit-gate) before committing.

## Hard rules
1. **Oracle plan-gate** before any code; **oracle commit-gate** before commit.
2. **Delegate by default** — oracle for review, fixer for implementation.
3. **Sequential, one ticket at a time**; dependencies first.
4. **Verify-close before advancing** — commit references the ticket ID, ticket is
   `closed`, and the verify suite is green (run it yourself, don't trust the report).
5. No hidden processes; only the Agent tool launches work (foreground, so it streams).
6. One commit per ticket with the ticket ID in the subject.

## Tickets
Tickets live in `.tickets/` (gitignored) via `tk`:

```
tk list | tk ready | tk blocked
tk show <id>            tk add-note <id> "..."
tk start <id>           tk close <id>
```

Epics are parents (`tk show <epic>` lists children); `<- [id]` in `tk list` means
"blocked by". Work the epics in this order: foundation → perf → folders →
uploads → deploy, except where a ticket unblocks another.

## Verify suite for THIS repo
Docker is **not** available on this host (daemon needs sudo, currently stopped),
so `make verify*` targets cannot run locally. Use the host toolchains:

```bash
cd makervault/api && source /home/mal/fuck_it_ill_do_it_myself/MakersVault/.venv/bin/activate \
  && ruff check . && python -m pytest -q

cd makervault/web && npm run verify      # eslint + tsc + vitest + vite build
```

CI is authoritative for the container layer (compose validation + container
smoke test):

```bash
gh workflow run Verify --repo insanemal/MakersVault --ref main
gh run list --repo insanemal/MakersVault --limit 1
gh run view <run-id> --repo insanemal/MakersVault --json jobs \
  -q '.jobs[] | "\(.name): \(.status)/\(.conclusion)"'
```

All four jobs (api, web, bridge, containers) must be `success`.

## Safeguards
- **Never push to `upstream` (GhostLabs-ent/MakersVault)**; it is read-only for us.
- **Never touch the live deployment** (`root@192.168.0.197`, `/opt/makersvault`,
  the Cosmos app, `/mnt/ceph/3D_models`) unless the ticket says so. Tests must use
  temp directories.
- **Do not modify migrations that have already shipped** (versions 1-3, and 4 once
  landed). Migrations are append-only and immutable — add a new version.
- **Stop before destructive behaviour.** Recursive folder deletion
  (`Mf-5gh0`) needs the owner's explicit go-ahead; until then folder DELETE keeps
  its current semantics.
- **No major dependency upgrades** (Tailwind 4, React 19, node 25) unless the
  ticket is specifically that.
- Never commit secrets, `config.yml` equivalents, local DBs, `dist/`, or
  `node_modules/`.

## Invoking
Launch the `scheduler` sub-agent (background) with a self-contained brief: repo
path, ordered ticket IDs, this doc plus the `oracle-gated-ticket-batch` skill,
the verify suite above, and the scope guards.
