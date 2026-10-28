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

Exit 0 accepts the wave, 1 refuses it with the reason on stderr, 2 is a usage
error. A plan file is {"lanes": [{"id": "Mf-6d52", "touches": ["path/one.py"],
"serialises": false, "reason": "why this lane serialises"}]}.
"""

import argparse
import fnmatch
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

Serialiser = tuple[str, str, str]


def entry_group(*pairs: tuple[str, str], reason: str) -> list[Serialiser]:
    """One reason for several serialising values that always move together."""
    return [(kind, value, reason) for kind, value in pairs]


# The serialising set: (kind, value, reason), in documentation order. This is
# the single source of truth - --list-serialisers prints it and the scheduler
# doc quotes it, so an entry carries the reason it exists.
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
    ("dir", "makervault/scripts", "the verification scripts themselves (container-smoke.sh, wave_plan.py): every gate runs them"),
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
            "app wiring and the lifespan boot guards: the router split landed (12 routers under makervault/api/routers/, 152 lines), "
            "so it is no longer the 16-commit chokepoint, but every new router and guard edits the include list"
        ),
    ),
    *entry_group(
        ("path", "makervault/api/models.py"),
        ("path", "makervault/api/schemas.py"),
        reason="shared contract modules: two lanes adding models or schemas merge cleanly and then fail semantically",
    ),
    ("path", "makervault/web/src/lib/api.ts", "one HTTP client for the whole UI: every frontend ticket appends to the same object"),
    *entry_group(
        ("path", "makervault/web/src/ui/App.tsx"),
        ("path", "makervault/web/src/ui/Sidebar.tsx"),
        reason="shell components every view mounts through: the component split landed but these two are still the hot shared surface",
    ),
    *entry_group(
        ("dir", "makervault/web/src/ui/asset-grid"),
        ("dir", "makervault/web/src/ui/settings"),
        reason=(
            "the split landed (Settings.tsx is 160 lines) but 12 and 20 files hang off two entry points: "
            "serialise the directories so a split-out test cannot slip past an entry-point lane"
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
        epilog="Exit 0 accepts the wave, 1 refuses it with the reason on stderr, 2 is a usage error.",
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
        parser.error("one of --lane or --plan is required")

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
