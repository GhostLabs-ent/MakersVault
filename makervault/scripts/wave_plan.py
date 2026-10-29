#!/usr/bin/env python3
"""Validate a proposed scheduler wave before any lane starts work.

A wave is two or three tickets run concurrently, each in its own git worktree
and each with the touch-set its Oracle plan-gate declared. This tool refuses a
wave when two lanes touch the same path, when a lane touches a serialiser, or
when a lane is malformed. A shared directory is only a warning: git merges it
cleanly, the review is what costs.

    python3 makervault/scripts/wave_plan.py --list-serialisers
    python3 makervault/scripts/wave_plan.py --lane Mf-6d52:makervault/api/permissions.py --lane Mf-nhhy:README.md
    python3 makervault/scripts/wave_plan.py --plan /tmp/wave-1.json --max-lanes 3
    python3 makervault/scripts/wave_plan.py --plan /tmp/wave-1.json --json
    python3 makervault/scripts/wave_plan.py --check-delta .plans/batch-13/Mf-z5qa.json
    python3 makervault/scripts/wave_plan.py --report-timings .plans/batch-13

A plan file is a statement of intent plus a touch-set, and a per-ticket plan
file carries the commit it was written against. The delta check exists because
the plan says what will be done, not what happened since: re-validating the
plan against base..HEAD is the cheap check before implementation starts, and it
is not a re-plan. A wave file is {"lanes": [{"id": "Mf-6d52", "touches":
["path/one.py"], "serialises": false, "reason": "why this lane serialises"}]}.

Exit 0 accepts the wave, reports a fresh plan, or prints a timing report; 1
refuses the wave or fails a delta check closed with the reason on stderr; 2 is
a usage error or a malformed plan file.
"""

import argparse
import fnmatch
import json
import math
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

Serialiser = tuple[str, str, str]


def entry_group(*pairs: tuple[str, str], reason: str) -> list[Serialiser]:
    """One reason for several serialising values that always move together."""
    return [(kind, value, reason) for kind, value in pairs]


# The serialising set: (kind, value, reason), in documentation order.
# --list-serialisers prints it, docs/TICKET_WORKFLOW.md and .pi/agents/scheduler.md
# quote it, and makervault/api/tests/test_wave_plan.py pins both docs to it, so an
# entry carries the reason it exists.
SERIALISERS: list[Serialiser] = [
    ("path", "makervault/api/migrations.py", "the schema ledger: every migration is an append to this one file"),
    *entry_group(
        ("glob", "**/migration_*.py"),
        ("dir", "makervault/api/migrations"),
        reason="a new migration is a schema change: full gate plus a boot-guard recheck, and migrations are append-only",
    ),
    *entry_group(
        ("glob", "makervault/api/requirements*.txt"),
        ("glob", "makervault/api/requirements*.lock"),
        reason="dependency locks: never covered by the fast gate, and two lanes bumping one lock cannot be reconciled by git",
    ),
    *entry_group(
        ("glob", "**/package.json"),
        ("glob", "**/package-lock.json"),
        reason="the node lock pair: same class as the python locks",
    ),
    ("path", "Makefile", "it is the gate: an edit changes the commands every other lane runs"),
    ("glob", ".github/workflows/*", "one CI workflow for the whole repository"),
    *entry_group(
        ("glob", "**/nginx.conf"),
        ("path", "makervault/web/security-headers.conf"),
        reason="proxy and security-header config: no unit test covers it, full gate only",
    ),
    ("glob", "**/conftest.py", "fixtures for every API test module: a change re-baselines the whole suite"),
    *entry_group(
        ("path", "makervault/scripts/container-smoke.sh"),
        ("path", "makervault/scripts/wave_plan.py"),
        reason=(
            "container-smoke.sh is the recipe verify-smoke executes and wave_plan.py is the wave validator itself, "
            "so an edit changes how every future wave is judged; a new sibling file under scripts/ is lane-able, and "
            "makervault/scripts/check_version.py is a known gap - not yet serialised - pending a follow-up ticket"
        ),
    ),
    *entry_group(
        ("path", "makervault/api/Dockerfile"),
        ("path", "makervault/web/Dockerfile"),
        ("path", "makervault/docker-compose.yml"),
        ("path", "makervault/docker-compose.deploy.yml"),
        ("path", "makervault/docker-compose.smoke.yml"),
        ("path", "makervault/docker-deploy.yml"),
        reason="the owner decision makes the full `make verify` mandatory per ticket for these, so they can never ride in a lane",
    ),
    (
        "path",
        "makervault/api/main.py",
        (
            "app wiring and the lifespan boot guards: the router split landed, so it is no longer the chokepoint it "
            "was, but every new router and guard edits the include list"
        ),
    ),
    (
        "path",
        "makervault/api/models.py",
        "shared contract modules: two lanes adding models or schemas merge cleanly and then fail semantically",
    ),
    (
        "path",
        "makervault/api/schemas/__init__.py",
        (
            "the barrel every schema module is re-exported through: the per-domain modules beside it are lane-able, "
            "which is what the split is for, but the barrel's import list, MODULES tuple and __all__ are the shared "
            "surface, and an exact path entry cannot be left on the deleted schemas.py because stem_files() keys on "
            "(directory, stem) and never matches a file under schemas/"
        ),
    ),
    (
        "path",
        "makervault/web/src/lib/api/index.ts",
        (
            "the barrel every UI file imports by name: the per-domain clients beside it are lane-able, which is what "
            "the split is for; the same-stem loss is deliberate, because a test beside this barrel stops serialising "
            "while two lanes editing one test still conflict in git and each lane's own full suite is the semantic "
            "gate; the domain clients carry no stem protection, so the only guard there is a shared-directory warning, "
            "the same accepted hole the entry-point narrowing documents; and a second module at the same stem would "
            "shadow this barrel and must never be created"
        ),
    ),
    *entry_group(
        ("path", "makervault/web/src/lib/api/baseUrl.ts"),
        ("path", "makervault/web/src/lib/api/http.ts"),
        ("path", "makervault/web/src/lib/api/grantPriming.ts"),
        reason="the api transport core every domain client imports",
    ),
    *entry_group(
        ("path", "makervault/web/src/ui/App.tsx"),
        ("path", "makervault/web/src/ui/Sidebar.tsx"),
        reason="shell components every view mounts through: the component split landed but these two are still the hot shared surface",
    ),
    *entry_group(
        ("path", "makervault/web/src/ui/asset-grid/AssetGrid.tsx"),
        ("path", "makervault/web/src/ui/settings/Settings.tsx"),
        reason=(
            "the entry points are serialised and the same-stem rule keeps AssetGrid.test.tsx and Settings.test.tsx "
            "serialised with them; non-entry siblings in those directories are lane-able because an unreferenced "
            "module is inert until an entry file imports it"
        ),
    ),
]


@dataclass(frozen=True)
class Lane:
    """One wave slot: an id, its normalised touch-set, and its declaration."""

    id: str
    touches: tuple[str, ...]
    serialises: bool = False
    reason: str = ""


def normalise_path(raw: str) -> str:
    """Compare-ready path: forward slashes, no `./`, no doubled or trailing `/`."""
    path = raw.replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def is_outside_repo(path: str) -> bool:
    """True for an absolute path or for any path climbing through `..`."""
    if path.startswith("/"):
        return True
    return ".." in path.split("/")


def clean_touches(raw_paths: Iterable[str]) -> tuple[str, ...]:
    touches: list[str] = []
    for raw in raw_paths:
        path = normalise_path(raw)
        if path and path not in touches:
            touches.append(path)
    return tuple(touches)


def parse_lane(spec: str) -> Lane:
    lane_id, separator, raw_paths = spec.partition(":")
    if not separator or not lane_id.strip():
        raise ValueError(f"--lane expects ID:path[,path...], got {spec!r}")
    return Lane(id=lane_id.strip(), touches=clean_touches(raw_paths.split(",")))


def load_plan(path: Path) -> list[Lane]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("lanes"), list):
        raise TypeError(f'{path}: expected {{"lanes": [...]}}')
    lanes: list[Lane] = []
    for item in raw["lanes"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError(f"{path}: every lane needs a non-empty string id")
        touches = item.get("touches", [])
        if not isinstance(touches, list) or any(not isinstance(touch, str) for touch in touches):
            raise TypeError(f"{path}: lane {item['id']} touches must be a list of strings")
        lanes.append(
            Lane(
                id=item["id"].strip(),
                touches=clean_touches(touches),
                serialises=bool(item.get("serialises", False)),
                reason=str(item.get("reason", "")),
            )
        )
    return lanes


def match_serialiser(kind: str, value: str, path: str) -> bool:
    if kind == "path":
        return path == value
    if kind == "dir":
        return path == value or path.startswith(value + "/")
    if kind == "glob":
        return fnmatch.fnmatchcase(path, value)
    raise ValueError(f"unknown serialiser kind: {kind}")


def stem_files() -> dict[tuple[str, str], str]:
    """Serialised exact files keyed by (directory, filename up to the first dot)."""
    indexed: dict[tuple[str, str], str] = {}
    for kind, value, _ in SERIALISERS:
        if kind != "path":
            continue
        directory, _, name = value.rpartition("/")
        indexed.setdefault((directory, name.split(".", 1)[0]), value)
    return indexed


STEM_FILES = stem_files()


def serialiser_hit(path: str) -> tuple[str, str] | None:
    """The (pattern, reason) that serialises this path, or None."""
    for kind, value, reason in SERIALISERS:
        if match_serialiser(kind, value, path):
            return value, reason
    directory, _, name = path.rpartition("/")
    serialised = STEM_FILES.get((directory, name.split(".", 1)[0]))
    if serialised is not None and serialised != path:
        return serialised, f"same-stem sibling of {serialised}"
    return None


def over_max_lanes(lanes: Sequence[Lane], max_lanes: int) -> str | None:
    if len(lanes) > max_lanes:
        return f"over max lanes: {len(lanes)} > {max_lanes}"
    return None


def duplicate_lane_ids(lanes: Sequence[Lane]) -> str | None:
    seen: set[str] = set()
    for lane in lanes:
        if lane.id in seen:
            return f"lane id {lane.id} appears twice"
        seen.add(lane.id)
    return None


def empty_touch_sets(lanes: Sequence[Lane]) -> str | None:
    for lane in lanes:
        if not lane.touches:
            return f"lane {lane.id} has an empty touch-set"
    return None


def outside_repo(lanes: Sequence[Lane]) -> str | None:
    for lane in lanes:
        for path in lane.touches:
            if is_outside_repo(path):
                return f"lane {lane.id} path {path} is outside the repo"
    return None


def declared_serialises(lanes: Sequence[Lane]) -> str | None:
    for lane in lanes:
        if lane.serialises:
            declared = f" ({lane.reason})" if lane.reason else ""
            return f"lane {lane.id} declared serialises: true{declared}"
    return None


def serialiser_touches(lanes: Sequence[Lane]) -> str | None:
    for lane in lanes:
        for path in lane.touches:
            hit = serialiser_hit(path)
            if hit is not None:
                pattern, reason = hit
                return f"lane {lane.id} touches {path}, a serialiser ({pattern}): {reason}"
    return None


def shared_paths(lanes: Sequence[Lane]) -> str | None:
    owner: dict[str, str] = {}
    for lane in lanes:
        for path in lane.touches:
            first = owner.setdefault(path, lane.id)
            if first != lane.id:
                return f"lane {first} and lane {lane.id} both touch {path}"
    return None


def refusal(lanes: Sequence[Lane], max_lanes: int) -> str | None:
    """The first reason the wave cannot run, in check order, or None."""
    checks = (
        over_max_lanes(lanes, max_lanes),
        duplicate_lane_ids(lanes),
        empty_touch_sets(lanes),
        outside_repo(lanes),
        declared_serialises(lanes),
        serialiser_touches(lanes),
        shared_paths(lanes),
    )
    return next((reason for reason in checks if reason is not None), None)


def common_directory(left: str, right: str) -> str:
    """Deepest directory both touch paths sit under, or "" for none."""
    left_parts = left.split("/")[:-1]
    right_parts = right.split("/")[:-1]
    shared: list[str] = []
    for first, second in zip(left_parts, right_parts):
        if first != second:
            break
        shared.append(first)
    return "/".join(shared)


def directory_warnings(lanes: Sequence[Lane]) -> tuple[str, ...]:
    """One warning per lane pair, naming the deepest directory they share."""
    notes: list[str] = []
    for index, first in enumerate(lanes):
        for second in lanes[index + 1 :]:
            shared = [
                directory
                for left in first.touches
                for right in second.touches
                if (directory := common_directory(left, right))
            ]
            if shared:
                deepest = max(shared, key=lambda directory: directory.count("/"))
                notes.append(f"warning: {first.id} and {second.id} both work in {deepest}/ (merge-clean, review-expensive)")
    return tuple(notes)


def lane_entries(lanes: Sequence[Lane]) -> list[dict[str, object]]:
    return [
        {
            "id": lane.id,
            "touches": list(lane.touches),
            "files": len(lane.touches),
            "serialises": lane.serialises,
            "reason": lane.reason,
        }
        for lane in lanes
    ]


def print_serialisers() -> None:
    print(f"{len(SERIALISERS)} serialiser entries: a lane that touches one of these never rides in a wave")
    print()
    value_width = max(len(value) for _, value, _ in SERIALISERS)
    kind_width = max(len(kind) for kind, _, _ in SERIALISERS)
    print(f"{'value':<{value_width}}  {'kind':<{kind_width}}  reason")
    for kind, value, reason in SERIALISERS:
        print(f"{value:<{value_width}}  {kind:<{kind_width}}  {reason}")


def print_wave(lanes: Sequence[Lane], max_lanes: int, notes: Sequence[str]) -> None:
    print(f"wave accepted: {len(lanes)} lane(s), max {max_lanes}")
    print()
    id_width = max(len("lane"), *(len(lane.id) for lane in lanes))
    print(f"{'lane':<{id_width}}  {'files':>5}  serialises")
    for lane in lanes:
        declared = "yes" if lane.serialises else "no"
        print(f"{lane.id:<{id_width}}  {len(lane.touches):>5}  {declared}")
    print()
    path_count = sum(len(lane.touches) for lane in lanes)
    print(f"disjoint: {path_count} path(s) across {len(lanes)} lane(s), no path touched by two lanes")
    for note in notes:
        print(note)


# --- per-ticket plans: the delta check and the plan-gate timing report ------


@dataclass(frozen=True)
class GateRun:
    """One gate record from a plan: the unit the timing report aggregates."""

    gate: str
    seconds: float | None
    oracle_calls: int
    overlapped_with: str


@dataclass(frozen=True)
class TicketPlan:
    """One ticket's plan: the lane shape plus the metadata the scheduler doc requires."""

    id: str
    touches: tuple[str, ...]
    serialises: bool = False
    reason: str = ""
    base: str = ""
    approach: str = ""
    risks: tuple[str, ...] = ()
    acceptance: tuple[tuple[str, str], ...] = ()
    gates: tuple[GateRun, ...] = ()


def optional_strings(raw: dict[str, object], key: str, path: Path) -> tuple[str, ...]:
    """A list-of-strings field that may be absent, or raise naming the file and field."""
    value = raw.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{path}: {key} must be a list of strings")
    return tuple(value)


def optional_acceptance(raw: dict[str, object], path: Path) -> tuple[tuple[str, str], ...]:
    """The acceptance map as ordered pairs: presence is all the warnings need."""
    value = raw.get("acceptance")
    if value is None:
        return ()
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
        raise TypeError(f"{path}: acceptance must be an object of string keys to string values")
    return tuple((str(key), item) for key, item in value.items())


def gate_seconds(raw: dict[str, object]) -> float | None:
    """Measured seconds, or None when the record carries no usable number.

    `bool` is an int in Python and JSON permits `NaN`/`Infinity`, so both are
    rejected here: a non-finite value would slip past the `<= 0` warning and
    poison the total into `nan`.
    """
    seconds = raw.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return None
    return float(seconds) if math.isfinite(seconds) else None


def parse_gate(raw: dict[str, object]) -> GateRun:
    """One gate record; a field the plan did not record stays absent instead of guessed."""
    calls = raw.get("oracle_calls")
    counted = calls if isinstance(calls, int) and not isinstance(calls, bool) else 0
    return GateRun(
        gate=str(raw.get("gate", "")),
        seconds=gate_seconds(raw),
        oracle_calls=counted,
        overlapped_with=str(raw.get("overlapped_with") or ""),
    )


def optional_gates(raw: dict[str, object], path: Path) -> tuple[GateRun, ...]:
    """Gate records: the only structural rule is a list of objects, fields are read leniently."""
    value = raw.get("gates")
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError(f"{path}: gates must be a list of objects")
    return tuple(parse_gate(item) for item in value)


def load_ticket_plan(path: Path) -> TicketPlan:
    """Read one per-ticket plan, or raise naming the file and the field at fault.

    The same loader serves the delta check and the timing report so both agree
    on what a well-formed plan is: 2 for the check, a skipped file for the
    report. Everything opt-in is optional, because an in-flight plan is a
    legitimate thing to see and must never crash the report.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{path}: expected a JSON object, got {type(raw).__name__}")
    plan_id = raw.get("id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise ValueError(f"{path}: id must be a non-empty string")
    touches = raw.get("touches")
    if not isinstance(touches, list) or not touches or any(not isinstance(touch, str) for touch in touches):
        raise TypeError(f"{path}: touches must be a non-empty list of strings")
    base = raw.get("base")
    if not isinstance(base, str) or not base.strip():
        raise ValueError(f"{path}: base must be a non-empty string naming the commit the plan was written against")
    approach = raw.get("approach")
    return TicketPlan(
        id=plan_id.strip(),
        touches=clean_touches(touches),
        serialises=bool(raw.get("serialises", False)),
        reason=str(raw.get("reason", "")),
        base=base.strip(),
        approach=approach.strip() if isinstance(approach, str) else "",
        risks=optional_strings(raw, "risks", path),
        acceptance=optional_acceptance(raw, path),
        gates=optional_gates(raw, path),
    )


def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
    """One git call in the process's working directory: every check is cwd-relative."""
    return subprocess.run(["git", *arguments], capture_output=True, check=False, text=True)


def in_git_work_tree() -> bool:
    """`rev-parse --is-inside-work-tree` answers the repo question and nothing else."""
    result = run_git("rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def resolves_to_commit(revision: str) -> bool:
    """`cat-file -e <rev>^{commit}` fails when the object is absent or is not a commit."""
    return run_git("cat-file", "-e", f"{revision}^{{commit}}").returncode == 0


def is_ancestor(base: str) -> bool:
    """`merge-base --is-ancestor base HEAD`: exit 0 means ancestor, 1 means not.

    Not a `rev-parse`-based comparison: rev-parse happily resolves a sha that
    lives only on a side branch and the diff it enables is nonsense. Refuse
    unless this plain exit-0 ancestry test passes.
    """
    return run_git("merge-base", "--is-ancestor", base, "HEAD").returncode == 0


def rev_parse(*arguments: str) -> str:
    """Trimmed rev-parse stdout, or "" when the call fails."""
    result = run_git("rev-parse", *arguments)
    return result.stdout.strip() if result.returncode == 0 else ""


def short_sha(revision: str) -> str:
    """Short form for the prose message, falling back to the raw value."""
    return rev_parse("--short", revision) or revision


def commit_count(base: str) -> int:
    """Commits in the delta: `rev-list --count base..HEAD`."""
    result = run_git("rev-list", "--count", f"{base}..HEAD")
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def delta_paths(base: str, head: str) -> tuple[str, ...] | None:
    """Changed paths between two commits, normalised for touch-set comparison.

    `git diff <base> <head>` is commit-to-commit, so uncommitted work cannot
    make a plan look stale. There is no dirty-tree guard on purpose: it could
    only manufacture re-plans, and every re-plan is real Oracle spend.

    `-z` because the default output C-quotes a non-ASCII path, which would then
    never match the plan's touch-set and a stale plan would read as fresh.
    """
    result = run_git("diff", "--name-only", "-z", base, head)
    if result.returncode != 0:
        return None
    return tuple(normalise_path(name) for name in result.stdout.split("\0") if name.strip())


def delta_refusal(reason: str) -> int:
    """Fail closed: the diagnostic goes to stderr and the caller returns 1."""
    print(f"FAIL-CLOSED: {reason}", file=sys.stderr)
    return 1


def plan_warnings(plan: TicketPlan) -> tuple[str, ...]:
    """Non-fatal plan faults: each one means this ticket cannot ride a lane."""
    notes: list[str] = []
    if not plan.approach:
        notes.append(f"warning: {plan.id}: the plan has no approach, which the scheduler doc requires before implementation")
    if not plan.acceptance:
        notes.append(f"warning: {plan.id}: the plan has no acceptance records, which the scheduler doc requires")
    if plan.serialises:
        notes.append(f"warning: {plan.id}: the plan declares serialises: true, so this ticket cannot ride a lane")
    for path in plan.touches:
        hit = serialiser_hit(path)
        if hit is not None:
            pattern, reason = hit
            notes.append(f"warning: {plan.id}: the plan touches {path}, a serialiser ({pattern}): {reason} - cannot ride a lane")
    return tuple(notes)


def check_delta(plan: TicketPlan) -> int:
    """Re-validate one plan against base..HEAD: 0 fresh, 1 stale or unresolvable.

    Exit 2 is decided by the caller before this runs, so the two failure modes
    stay distinguishable: 2 means the plan file itself is wrong, 1 means the
    repository moved under a plan that is otherwise well-formed.
    """
    if not in_git_work_tree():
        return delta_refusal("the current directory is not inside a git work tree, so base..HEAD cannot be compared")
    if not resolves_to_commit(plan.base):
        return delta_refusal(f"base {plan.base} does not resolve to a commit in this repository")
    if not is_ancestor(plan.base):
        return delta_refusal(
            f"base {plan.base} is not an ancestor of HEAD: a sha that lives only on a side branch yields a nonsense delta"
        )
    head = rev_parse("HEAD")
    changed = delta_paths(plan.base, head)
    if changed is None:
        return delta_refusal(f"git diff {plan.base} HEAD failed, so the delta is unknown")
    touches = set(plan.touches)
    stale = [path for path in changed if path in touches]
    if stale:
        print(
            f"STALE: the delta {short_sha(plan.base)}..{short_sha(head)} changes {len(stale)} path(s) this plan declares, "
            "so the plan predates a merge that touched its own work. Do not implement: re-plan against the new base with a fresh plan gate.",
            file=sys.stderr,
        )
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    print(f"plan {plan.id}: FRESH")
    print(f"base {short_sha(plan.base)}, {commit_count(plan.base)} commit(s) since base")
    print(f"HEAD {head}")
    print(f"declared touch-set: {len(plan.touches)} path(s), 0 changed by the delta")
    print()
    if not changed:
        print("changed outside the touch-set: none")
    else:
        print(f"changed outside the touch-set ({len(changed)}):")
        for path in changed:
            print(f"  {path}")
            hit = serialiser_hit(path)
            if hit is not None:
                pattern, reason = hit
                print(f"    serialiser: {pattern} - {reason}")
    notes = plan_warnings(plan)
    if notes:
        print()
        for note in notes:
            print(note)
    return 0


@dataclass(frozen=True)
class TimingRow:
    """One plan's plan-gate cost, as printed by the timing report."""

    id: str
    plan_gate_s: float | None
    overlapped: str
    replans: int
    oracle_calls: int


TIMING_FOOTER = """note: oracle_calls is this scheduler's own ledger of gate invocations (it dispatches
them, so it can count them). This repository has no OpenTelemetry instrumentation in
its deps or code, so no independent trace corroborates the count. plan_gate_s is the
self-reported sum of the plan-gate records, not a stopwatch this tool ran."""


def timing_row(plan: TicketPlan) -> tuple[TimingRow, tuple[str, ...]]:
    """Aggregate one plan's gate records, with a warning per unmeasured plan gate.

    A self-reported zero is not a measurement, so it is reported and warned
    about rather than quietly summed into the total as if it were real.
    """
    plan_gates = [gate for gate in plan.gates if gate.gate == "plan"]
    oracle_calls = sum(gate.oracle_calls for gate in plan.gates)
    if not plan_gates:
        row = TimingRow(id=plan.id, plan_gate_s=None, overlapped="no", replans=0, oracle_calls=oracle_calls)
        return row, (f"warning: {plan.id}: timings are unknown - the plan records no plan gate",)
    notes: list[str] = []
    for gate in plan_gates:
        if gate.seconds is None:
            notes.append(f"warning: {plan.id}: a plan gate record has no numeric seconds, so plan_gate_s undercounts")
        elif gate.seconds <= 0:
            notes.append(f"warning: {plan.id}: a plan gate reports {gate.seconds:g}s, which is not a measurement")
    measured = [gate.seconds for gate in plan_gates if gate.seconds is not None and gate.seconds > 0]
    row = TimingRow(
        id=plan.id,
        plan_gate_s=sum(measured) if measured else None,
        overlapped=plan_gates[0].overlapped_with or "no",
        replans=max(len(plan_gates) - 1, 0),
        oracle_calls=oracle_calls,
    )
    return row, tuple(notes)


def print_timings(rows: Sequence[TimingRow], notes: Sequence[str], skipped: int) -> None:
    """The table, then the warnings, then the totals, then the honest footer."""
    print(f"plan-gate timings: {len(rows)} plan(s)")
    print()
    id_width = max(len("ticket"), *(len(row.id) for row in rows))
    print(f"{'ticket':<{id_width}}  {'plan_gate_s':>12}  {'overlapped':<10}  {'replans':>7}  {'oracle_calls':>12}")
    for row in rows:
        gate_seconds = "not recorded" if row.plan_gate_s is None else f"{row.plan_gate_s:.1f}"
        print(f"{row.id:<{id_width}}  {gate_seconds:>12}  {row.overlapped:<10}  {row.replans:>7}  {row.oracle_calls:>12}")
    print()
    for note in notes:
        print(note)
    if notes:
        print()
    measured = [row.plan_gate_s for row in rows if row.plan_gate_s is not None]
    overlapped = sum(1 for row in rows if row.overlapped != "no")
    print(
        f"totals: {len(rows)} plan(s) reported, plan_gate_s {sum(measured):.1f}s, "
        f"overlapped {overlapped} of {len(rows)}, replans {sum(row.replans for row in rows)}, "
        f"oracle_calls {sum(row.oracle_calls for row in rows)}, "
        f"{skipped} plan file(s) skipped as unreadable or malformed"
    )
    print()
    print(TIMING_FOOTER)


def report_timings(directory: Path) -> int:
    """Report per-ticket plan-gate cost from a plan directory; 2 when there is nothing to report."""
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    files = sorted(path for path in directory.rglob("*.json") if path.is_file())
    if not files:
        print(f"error: {directory} holds no *.json plan files", file=sys.stderr)
        return 2
    rows: list[TimingRow] = []
    notes: list[str] = []
    skipped = 0
    for path in files:
        try:
            plan = load_ticket_plan(path)
        except (OSError, ValueError, TypeError) as error:
            print(f"warning: skipping {path}: {error}", file=sys.stderr)
            skipped += 1
            continue
        row, row_notes = timing_row(plan)
        rows.append(row)
        notes.extend(row_notes)
        if path.stem != plan.id:
            notes.append(f"warning: {path.name} holds plan {plan.id}, so the file name and the plan id disagree")
    if not rows:
        print(f"error: {directory} holds no readable plan files ({skipped} skipped)", file=sys.stderr)
        return 2
    print_timings(rows, notes, skipped)
    return 0


def lane_limit(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an integer: {raw!r}") from error
    if not 1 <= value <= 3:
        raise argparse.ArgumentTypeError(f"must be 1, 2 or 3, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wave_plan.py",
        description="Refuse a scheduler wave whose lanes are not disjoint.",
        epilog=(
            "Exit 0 accepts the wave, reports a fresh plan or prints a timing report; "
            "1 refuses the wave or fails a delta check closed with the reason on stderr; "
            "2 is a usage error or a malformed plan file."
        ),
    )
    parser.add_argument("--list-serialisers", action="store_true", help="print the serialising set and exit")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--lane",
        action="append",
        dest="lanes",
        metavar="ID:path[,path...]",
        help="a lane with its touch-set (repeatable)",
    )
    source.add_argument(
        "--plan",
        metavar="FILE",
        help='a wave JSON file: {"lanes": [{"id", "touches", "serialises", "reason"}]}',
    )
    source.add_argument(
        "--check-delta",
        metavar="FILE",
        help="one per-ticket plan: re-validate base..HEAD and exit 0 fresh, 1 stale",
    )
    source.add_argument(
        "--report-timings",
        metavar="DIR",
        help="a directory of per-ticket plan files: report plan-gate cost per ticket",
    )
    parser.add_argument(
        "--max-lanes",
        type=lane_limit,
        default=2,
        metavar="N",
        help="lanes allowed in one wave, 1-3 (default 2)",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of prose")
    return parser


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_serialisers:
        print_serialisers()
        return 0
    if args.check_delta is not None:
        try:
            plan = load_ticket_plan(Path(args.check_delta))
        except (OSError, ValueError, TypeError) as error:
            parser.error(str(error))
        return check_delta(plan)
    if args.report_timings is not None:
        return report_timings(Path(args.report_timings))
    if args.plan is not None:
        try:
            lanes = load_plan(Path(args.plan))
        except (OSError, ValueError, TypeError) as error:
            parser.error(str(error))
    elif args.lanes:
        try:
            lanes = [parse_lane(spec) for spec in args.lanes]
        except ValueError as error:
            parser.error(str(error))
    else:
        parser.error("one of --lane, --plan, --check-delta or --report-timings is required")

    reason = refusal(lanes, args.max_lanes)
    if reason is not None:
        print(reason, file=sys.stderr)
        if args.json:
            print(json.dumps({"accepted": False, "reason": reason}))
        return 1

    notes = directory_warnings(lanes)
    if args.json:
        print(
            json.dumps(
                {
                    "accepted": True,
                    "max_lanes": args.max_lanes,
                    "lanes": lane_entries(lanes),
                    "paths": sum(len(lane.touches) for lane in lanes),
                    "warnings": list(notes),
                    "reason": None,
                }
            )
        )
    else:
        print_wave(lanes, args.max_lanes, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
