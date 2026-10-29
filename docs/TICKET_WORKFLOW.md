# Ticket Completion Workflow (scheduler / oracle-gated)

This project completes work tickets through a **scheduler → orchestrator →
oracle** pipeline so every ticket gets an Oracle plan-gate and commit-gate,
independent verification, and a clean one-commit-per-ticket landing.

Adapted from `~/ggreq_agent/docs/project_notes/TICKET_WORKFLOW.md` and
`~/card_event_tracker/.pi/agents/scheduler.md`, which in turn use the global
`oracle-gated-ticket-batch` skill.

## Roles
- **scheduler** (`.pi/agents/scheduler.md`) — the **wave planner**: packs 2
  tickets (max 3) whose plan-gate touch-sets are disjoint into lanes, dispatches
  those lanes in parallel into git worktrees, merges them into `main` one at a
  time with the full gate after each merge, then trust-but-verifies each ticket
  is closed before moving on. It plans ahead as well as packing waves: while a
  wave is in flight it runs the next candidates' plan-gates and writes each
  approved plan to `.plans/batch-<n>/<ticket>.json`, so a lane starts from a
  delta check instead of a fresh gate (see [Plan-ahead](#plan-ahead)). It decides
  packing with `makervault/scripts/wave_plan.py`, never by judgement. Produces a
  per-ticket report.
- **orchestrator** (built-in Pantheon orchestrator) — plans, delegates to
  specialists (oracle / fixer / explorer / designer), plumbs, commits, verifies.
- **oracle** — the review authority: approves the plan (plan-gate) before code,
  and the diff (commit-gate) before committing.

## Hard rules
1. **Oracle plan-gate** before any code; **oracle commit-gate** before commit.
2. **Delegate by default** — oracle for review, fixer for implementation.
3. **Waves, not a queue.** Pack 2 tickets (hard max 3) into one wave when their
   plan-gate touch-sets are **pairwise disjoint** and none serialises; a
   serialiser — `Makefile`, migrations, locks, `main.py`, the UI shell — never
   rides in a lane (see [Lanes](#lanes)). Lanes run in parallel and merge
   **serially** into `main`; dependencies first; a single-lane wave is the
   fallback.
4. **Verify-close before advancing** — commit references the ticket ID, ticket is
   `closed`, and the verify suite is green (run it yourself, don't trust the report).
5. No hidden processes; only the Agent tool launches work. Lane dispatch is the
   one sanctioned `run_in_background: true` — background Agent tasks stream in
   the UI, unlike the bash-spawned `pi` processes this rule exists to stop.
6. One commit per ticket with the ticket ID in the subject.

## Lanes

A **wave** is 2 tickets (hard max 3); a **lane** is one ticket in its own git
worktree. A wave is allowed only when every candidate's oracle plan-gate has
returned a `touches` set and the sets are pairwise disjoint. The decision is the
helper's, and its verdict is recorded:

```bash
python3 makervault/scripts/wave_plan.py --plan /tmp/wave-<n>.json            # exit 0 accept, 1 refuse with the reason
python3 makervault/scripts/wave_plan.py --plan /tmp/wave-<n>.json --max-lanes 3   # only when packing a third lane
python3 makervault/scripts/wave_plan.py --list-serialisers
```

The wave file holds one `{"id", "touches", "serialises", "reason"}` entry per
lane (the ticket id as `id`), with repo-relative file paths — tests and doc
updates included, because a permission change that edits `docs/PERMISSIONS.md`
must declare it or the disjointness evidence is a lie. A refusal exits 1 with the
reason on stderr (shared path, serialiser hit, over max lanes, malformed path):
drop the last candidate and run it sequentially in the next wave. A warning that
two lanes work in the same directory is still an acceptance, but the review is
what costs, so prefer a candidate elsewhere. A single-lane wave is legal and is
the fallback; `.pi/agents/scheduler.md` is the executable version of this
section, including the full serialiser table.

### Plan-ahead

While ticket N is in its lane, the Oracle plan-gates for N+1 (and N+2) are
already running in parallel, off the critical path, and each approved plan is
written to a per-ticket file in the main checkout:
`.plans/batch-<n>/<ticket>.json`.

```json
{
  "id": "Mf-z5qa",
  "touches": ["makervault/scripts/wave_plan.py"],
  "serialises": false,
  "reason": "one line: what this lane is",
  "base": "<full sha the plan was written against>",
  "approach": "how it will be built",
  "risks": ["..."],
  "acceptance": {"AC-1": "the evidence that proves it"},
  "gates": [
    {"gate": "plan", "seconds": 877, "oracle_calls": 2, "overlapped_with": null, "verdict": "approved"}
  ]
}
```

That is the wave-lane shape (`id`, `touches`, `serialises`, `reason`) plus
planning metadata, so the same normalisation and serialiser logic in
`makervault/scripts/wave_plan.py` validates both. `base` is the full sha the gate
planned against and `gates` records each gate invocation with its wall-clock,
Oracle-call count and the ticket it overlapped. `.plans/` is gitignored: a plan
file must never ride a lane diff, or the touch-set check has nothing to check.

Implementation starts from the queue rather than from a fresh gate, and its
**first action** is the delta check, run from the lane's own cwd against the plan
file's absolute path in the main checkout:

```bash
python3 makervault/scripts/wave_plan.py --check-delta /abs/main/.plans/batch-<n>/<ticket>.json
```

- **exit 0** - fresh: proceed. It also prints every changed path outside the
  touch-set, annotated when one is a serialiser. Read it: the exit-0 decision is
  only honest if a human can see what the delta actually did.
- **exit 1** - fail closed, re-plan: the base does not resolve, is not an
  ancestor of `HEAD`, or the `base..HEAD` delta changes a declared touch-set
  path.
- **exit 2** - malformed plan: fix the file.

The check is `git merge-base --is-ancestor <base> HEAD`. A `rev-parse` comparison
would happily resolve a sha that lives only on a side branch and yield a nonsense
diff. There is deliberately **no dirty-tree guard**: the diff is
commit-to-commit, so a dirty-tree check is dead code that only manufactures
spurious re-plans, i.e. real Oracle spend. `gates` is optional for the delta
check, so an in-flight plan validates instead of crashing.

`.plans/` is invisible from a lane: `.lanes/<ticket>/` is a separate working
directory. The lane brief therefore passes the **absolute** path of the plan file
in the main checkout and the check runs from the lane's own cwd - the worktree
shares `.git/objects`, so `base` and `HEAD` both resolve. That read is blessed
process state, exactly like the `tk add-note` a lane already does against the
shared ticket store: it is a read, not an edit, so the "stay inside the
worktree" rule is untouched.

Disjointness is economy, not legality. Plan-ahead is not conditional on
disjoint touch-sets: two tickets that both touch `lib/api/index.ts` or
`models.py` are the highest-value pipeline case, because their plans are legal
and the delta check arbitrates at implementation time, with every re-plan
counted in `replans` and `oracle_calls` rather than assumed away. The rule that
two lanes never work on the same files is unchanged.

Lane width is unchanged: 2-3 lanes, `--max-lanes` capped at 1-3 with a default of
2. A queue of approved plans is not an authorisation to run more lanes than the
cap.

Timings come out of the plan directory:

```bash
python3 makervault/scripts/wave_plan.py --report-timings .plans/batch-<n>
```

It prints `plan_gate_s`, `overlapped`, `replans` and `oracle_calls` per ticket
plus totals, tolerates a gates-less in-flight plan (`not recorded`) and warns
when a self-reported plan-gate timing is `<= 0`. `oracle_calls` is a
**self-reported ledger**, not a trace: this repo has no opentelemetry/otlp
dependency or code, so the count is the scheduler's own tally of the gates it
dispatched. Batch 13 is the **baseline**: its gates ran in parallel with each
other, not beside another ticket's implementation, so every one of them would
record `overlapped_with: null` (`overlapped_with` names the ticket whose
implementation was in flight while the gate ran). Its per-ticket cost is real -
Mf-z5qa 877 s / 2 calls, Mf-0bl6 1091 s / 1, Mf-3r90 312 s / 1 - and it replaces
a plan-gate paid serially on the critical path, roughly a third of the ~60 min per
ticket measured across batches 10-11, for which no per-ticket table was archived.
The first gate that actually overlaps an implementation is owed by the first
batch that runs under v3; that column is the feature's evidence, and until then
it is an assumption rather than a measurement.

### Serialisers — never in a lane

`makervault/scripts/wave_plan.py --list-serialisers` prints this set and
`.pi/agents/scheduler.md` quotes it; `makervault/api/tests/test_wave_plan.py`
pins both documents to the ledger, so every value below is the exact spelling the
helper matches.

| Group | Files | Why |
|---|---|---|
| schema | `makervault/api/migrations.py`, `**/migration_*.py`, `makervault/api/migrations` (directory) | a new migration is a schema change: full gate plus a boot-guard recheck, and migrations are append-only |
| locks | `makervault/api/requirements*.txt`, `makervault/api/requirements*.lock`, `**/package.json`, `**/package-lock.json` | dependency locks: never covered by the fast gate, and two lanes bumping one lock cannot be reconciled by git |
| the gate | `Makefile`, `.github/workflows/*`, `makervault/scripts/container-smoke.sh`, `makervault/scripts/wave_plan.py` | the gate, the one CI workflow, the smoke recipe `verify-smoke` runs and the wave validator itself: an edit changes the commands every lane runs or how every future wave is judged |
| config | `**/nginx.conf`, `makervault/web/security-headers.conf`, `makervault/api/Dockerfile`, `makervault/web/Dockerfile`, `makervault/docker-compose.yml`, `makervault/docker-compose.deploy.yml`, `makervault/docker-compose.smoke.yml`, `makervault/docker-deploy.yml` | proxy and security-header config plus the container manifests: no unit test covers it, verified by the single end-of-batch full gate |
| fixtures | `**/conftest.py` | fixtures for every API test module: a change re-baselines the whole suite |
| training wheels: API contracts | `makervault/api/main.py`, `makervault/api/models.py`, `makervault/api/schemas/__init__.py` | shared wiring and contracts: two lanes merge cleanly, then fail semantically; the schema package's per-domain modules are lane-able, which is what the split was for, but its barrel is not |
| training wheels: UI shell | `makervault/web/src/lib/api/index.ts`, `makervault/web/src/ui/App.tsx`, `makervault/web/src/ui/Sidebar.tsx`, `makervault/web/src/ui/asset-grid/AssetGrid.tsx`, `makervault/web/src/ui/settings/Settings.tsx` | the barrel the UI imports by name plus the components every view mounts through |
| training wheels: UI transport | `makervault/web/src/lib/api/baseUrl.ts`, `makervault/web/src/lib/api/http.ts`, `makervault/web/src/lib/api/grantPriming.ts` | the api transport core every domain client imports |

Two gaps are accepted. A new file beside an entry point no longer serialises:
the entry point itself does not change, and an unreferenced module is inert until
something imports it, at which point whoever imports it edits a serialised entry
file. And `makervault/scripts/check_version.py` is a known gap, not yet
serialised, pending a follow-up ticket.

The three training-wheels groups are what the router, component and transport
splits were for; they stay serialised until nothing hot hangs off a single entry
point. The helper also serialises a same-directory sibling with the same stem
(`makervault/web/src/ui/Sidebar.test.tsx` matches `makervault/web/src/ui/Sidebar.tsx`), so a test-only lane
cannot defeat the gate.

### Worktrees

```bash
git worktree add .lanes/<ticket> -b ticket/<ticket>            # from the repo root
# lane works, commits and verifies inside .lanes/<ticket>
git worktree remove .lanes/<ticket> && git branch -d ticket/<ticket>   # after a green merge
```

`.lanes/` is gitignored. A failed lane keeps its worktree until the wave drains,
then goes the same way — you may need its state to explain the failure.

### Lane bootstrap

```bash
cd .lanes/<ticket>
uv venv --python 3.12 .venv
cd makervault/api && uv pip install --python ../../.venv/bin/python -r requirements.lock -r requirements-dev.lock ruff && cd ../..
cd makervault/web && npm ci --no-audit --no-fund && cd ../..
```

Measured on this host with warm caches: each `uv` step under 1 s, `npm ci` about
4 s (235 MB of `node_modules`), so about 6 s of setup and then ~83 s for the
lane's first `make verify-fast`. Borrowing the main checkout's interpreter
(`make verify-fast VENV=/abs/main/.venv`) is allowed for the python, ruff and
bridge half only — it saves under 2 s. **Never symlink the lane's `node_modules`
at the main checkout's:** `vite.config.js` sets no `cacheDir`, so the
dep-optimiser cache is `node_modules/.vite` and concurrent vitest runs would race
it, and `npm ci` deletes `node_modules` first, so the lane would delete the main
checkout's modules.

### Isolation

`MV_RUN_ID` namespaces everything a verification run creates: the API test
database and storage root (`/tmp/makersvault-tests/<id>/`), the four image tags,
the smoke Compose project name and the smoke host ports. Lanes set it explicitly
(`MV_RUN_ID=<ticket> make verify-fast`) and **never pin a port** — the smoke
script claims lanes 0-2 by scanning and atomically locking
`/tmp/makersvault-smoke-lanes/`. Two lanes may therefore run `make verify-fast`
at once, with `make verify` on `main` at the same time.

### Merging

One lane at a time, in dispatch (priority) order, from the repo root:

```bash
git merge --no-ff ticket/<ticket>
make verify        # full gate ONCE, at the end of the batch
```

`--no-ff` keeps one commit per ticket. A conflict is resolved **on `main`, by a
foreground orchestrator task — never in the lane** — and that resolution is
oracle commit-gated. A merge that conflicts twice ends the wave.

### Stop conditions

A lane fails (red gate, refused commit-gate, or a diff outside its declared
touch-set), a merge conflicts twice, or a lane finds it needs a serialiser:
dispatch nothing new, drain the lanes already running, `make verify` on `main`,
record the reason on every ticket in the wave, report. Never start a lane while
an unmerged lane ahead of it touches the same files. The planner notes its
decision per lane (`tk add-note <ticket>` with the helper's accept/refuse output
and the merge order), so a wave can be audited afterwards.

A scheduler that is already running is unaffected by an edit to
`.pi/agents/scheduler.md`: its instructions are in its context, and the change
governs the next invocation.

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
Docker runs on this host (daemon up), so `make verify` is the gate. Use the host
toolchains for fast iteration:

```bash
cd makervault/api && source ../../.venv/bin/activate \
  && ruff check . && python -m pytest -q

cd makervault/web && npm run verify      # eslint + tsc + vitest + vite build
```

The venv is the repo-local one `make verify-fast` uses. Never borrow another
checkout's `.venv`: a lane is its own worktree with its own `.venv`, and a
foreign interpreter hides a missing dependency until the merge.

**Per ticket: the fast gate (~71-83 s).** Run before every commit:

```bash
make verify-fast        # ruff+pytest (api), lint+tsc+vitest (web), go test (bridge)
```

It uses a repo-local `.venv` if one exists (`uv venv --python 3.12 .venv` then
`uv pip install -r makervault/api/requirements.lock -r
makervault/api/requirements-dev.lock ruff`), otherwise `python3`/`ruff` from
PATH. The web target needs `npm ci` once per clone.

In a lane, always name the run from inside the lane's worktree:

```bash
MV_RUN_ID=<ticket> make verify-fast
```

so its test database, storage root, image tags and smoke ports collide with
neither another lane nor `main`.

**Per merge: the full gate (~90-96 s).** Run on `main` after every lane merge
(`--no-ff`, one at a time), and per ticket whenever it touches migrations,
Dockerfiles, `nginx.conf`, the compose manifests or a dependency lockfile —
exactly the things the fast gate does not cover:

```bash
make verify             # lint in images, API tests, web build, bridge, compose, container smoke
```

A wave is not done until the full gate is green; fix forward with a corrective
commit (oracle commit-gated, ticket ID in the subject) rather than reporting a
red wave.

CI duplicates the same jobs, so it stays a safety net rather than the only check:

```bash
gh workflow run Verify --repo insanemal/MakersVault --ref main
gh run list --repo insanemal/MakersVault --limit 1
gh run view <run-id> --repo insanemal/MakersVault --json jobs \
  -q '.jobs[] | "\(.name): \(.status)/\(.conclusion)"'
```

All four jobs (api, web, bridge, containers) must be `success`.

## Safeguards
- **Never push to, merge, or rebase onto `upstream` (GhostLabs-ent/MakersVault).** It is a
deliberately diverged line: they built overlapping features their own way and our
migrations/permissions/audit differ. Port features by hand into our idioms, one
ticket at a time (see the fork-stance ticket), never with `git cherry-pick` or
`git merge`.
- **Never touch the live deployment** (`root@192.168.0.197`, `/opt/makersvault`,
  the Cosmos app, `/mnt/ceph/3D_models`) unless the ticket says so. Tests must use
  temp directories.
- **Do not modify migrations that have already shipped** (versions 1-9).
  Migrations are append-only and immutable — add a new version.
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
the verify suite above, and the scope guards. For a wave, the scheduler runs the
candidates' oracle plan-gates in parallel and writes each approved plan to
`.plans/batch-<n>/<ticket>.json`, packs the wave with
`makervault/scripts/wave_plan.py` (see [Lanes](#lanes) and
[Plan-ahead](#plan-ahead)), and merges serially; each lane re-checks its plan
with `--check-delta` before it starts. It needs nothing beyond this doc and
`.pi/agents/scheduler.md` to do that.
