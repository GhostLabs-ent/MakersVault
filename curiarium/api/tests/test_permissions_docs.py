"""Guard docs/PERMISSIONS.md and the README against drift from the permission matrix.

This is a docs-drift guard, not a behaviour test: `permissions.ROUTE_PERMISSIONS`
is the authorization contract and `test_permissions_matrix.py` enforces it, so
the one remaining way to lie is for the human-readable tables to say something
else. Mf-01f0 added the contribute level, which moved nineteen routes between two
tables and added a role to a list and a column to a table - exactly the kind of
edit half of which gets forgotten.

Pathlib plus `permissions` and nothing else from the API: the matrix is the thing
being mirrored, so it is worth importing rather than re-parsing. The guarded docs
live above the API directory, so the module skips itself in the container, where
`curiarium/api` is the whole build context.
"""

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
CURIARIUM_ROOT = API_ROOT.parent
REPO_ROOT = CURIARIUM_ROOT.parent

PERMISSIONS_PATH = REPO_ROOT / "docs" / "PERMISSIONS.md"
README_PATH = REPO_ROOT / "README.md"

# Both files are absent inside the API image (the build context is
# `curiarium/api`, which becomes /app), but requiring both to be missing keeps a
# half-deleted docs tree failing loudly on a real checkout instead of skipping.
if not PERMISSIONS_PATH.exists() and not README_PATH.exists():
    pytest.skip(
        "permission docs guard is host-only (the API image builds from curiarium/api, so "
        "the repo README.md and docs/ are absent)",
        allow_module_level=True,
    )

import permissions  # noqa: E402  (imported after the host-only skip, like the docs paths above)

LEVELS = (
    permissions.PUBLIC,
    permissions.READ,
    permissions.CONTRIBUTE,
    permissions.WRITE,
    permissions.ADMIN,
)

# `### write (editor or admin)` and friends: the level is the first word of the
# heading, so the parenthetical can be reworded without breaking the guard.
TABLE_HEADING = re.compile(r"^###\s+(public|read|contribute|write|admin)\b", re.IGNORECASE)
HEADING = re.compile(r"^#{1,3}\s")
# `| POST   | `/upload`   | creates an asset |` - the path is always in backticks.
TABLE_ROW = re.compile(r"^\|\s*([A-Z]+)\s*\|\s*`([^`]+)`\s*\|")
ROUTE_COUNT = re.compile(r"(\d+)\s+routes:")
LEVEL_COUNT = re.compile(r"(\d+)\s+(public|read|contribute|write|admin)\b", re.IGNORECASE)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _route_tables(lines: list[str]) -> dict[str, set[tuple[str, str]]]:
    """The `(method, path)` rows of each `### <level>` route table, by level."""
    tables: dict[str, set[tuple[str, str]]] = {}
    current: str | None = None
    for line in lines:
        heading = TABLE_HEADING.match(line)
        if heading:
            current = heading.group(1).lower()
            tables.setdefault(current, set())
            continue
        if HEADING.match(line):
            current = None
            continue
        if current is None:
            continue
        row = TABLE_ROW.match(line)
        if row:
            tables[current].add((row.group(1), row.group(2)))
    return tables


def _route_count_sentence(lines: list[str]) -> str:
    """The line that states the matrix size, plus the two lines it may wrap onto."""
    for index, line in enumerate(lines):
        if ROUTE_COUNT.search(line):
            return " ".join(lines[index : index + 3])
    raise AssertionError("docs/PERMISSIONS.md has no '<n> routes:' line stating the matrix size")


def _capability_header_cells(lines: list[str]) -> list[str]:
    """The cells of the capability table's header row, lowercased."""
    for line in lines:
        cells = [cell.strip().strip("*`").lower() for cell in line.split("|")]
        if cells[1:2] == ["capability"]:
            return cells
    raise AssertionError("docs/PERMISSIONS.md has no capability table (a '| Capability | ... |' header row)")


def test_every_matrix_key_appears_in_its_levels_route_table() -> None:
    """The route tables in the docs are the matrix, spelled for a human reader.

    A route moved between levels in `permissions.py` without moving its row is
    the drift this catches, in both directions: missing from its own table and
    left behind in the table it no longer belongs to. Every problem is collected
    before failing, so a reviewer sees the whole move at once instead of one row
    per run. The table set itself is asserted first: a level whose table is
    absent would otherwise pass vacuously for every route at that level.
    """
    tables = _route_tables(_lines(PERMISSIONS_PATH))
    assert set(tables) == set(LEVELS), (
        f"docs/PERMISSIONS.md route tables are {sorted(tables)}, expected {sorted(LEVELS)}"
    )

    problems: list[str] = []
    for key, level in sorted(permissions.ROUTE_PERMISSIONS.items()):
        method, path = key
        for table_level in LEVELS:
            listed = key in tables[table_level]
            if table_level == level and not listed:
                problems.append(f"{method} {path} is {level} in ROUTE_PERMISSIONS but missing from the {table_level} table")
            elif table_level != level and listed:
                problems.append(f"{method} {path} is {level} in ROUTE_PERMISSIONS but listed in the {table_level} table")

    assert not problems, "docs/PERMISSIONS.md route tables have drifted from the matrix:\n  - " + "\n  - ".join(problems)


def test_the_docs_name_the_four_roles_and_the_capability_table() -> None:
    """A level nobody is offered is not a feature: the docs have to sell it.

    The README's "Users and roles" row is where a reader learns which roles
    exist, and the capability table is where they learn what each one may do.
    Both have to move with `accounts.ROLES`, or a client is built against a role
    list the docs never mentioned. The four columns are cross-checked against
    `ROLE_LEVELS`, which is the role set the rank ladder actually knows.
    """
    readme_lines = _lines(README_PATH)
    role_rows = [line for line in readme_lines if line.lstrip().startswith("|") and "users and roles" in line.lower()]
    assert len(role_rows) == 1, f"README.md must have exactly one 'Users and roles' feature row, found: {role_rows}"

    header = _capability_header_cells(_lines(PERMISSIONS_PATH))

    problems: list[str] = []
    if "contributor" not in role_rows[0]:
        problems.append(f"README.md's users/roles row does not name the contributor role: {role_rows[0]}")
    if "contributor" not in header:
        problems.append(f"docs/PERMISSIONS.md's capability table has no contributor column: {header}")
    undocumented = set(permissions.ROLE_LEVELS) - set(header)
    if undocumented:
        problems.append(f"the capability table has no column for {sorted(undocumented)}: {header}")
    assert not problems, "the docs do not document every role:\n  - " + "\n  - ".join(problems)


def test_the_docs_pin_the_matrix_size() -> None:
    """The stated size is computed from the live matrix, not a copied string.

    The total is pinned at 91 the way `test_the_matrix_is_the_documented_size`
    pins it, so a route added to only one side fails both tests with the same
    number. The per-level split is read from `ROUTE_PERMISSIONS` instead of being
    hard-coded here: the matrix test owns that pin, and repeating the numbers in
    a docs guard would make three places to update instead of two.
    """
    sentence = _route_count_sentence(_lines(PERMISSIONS_PATH))

    declared_total = int(ROUTE_COUNT.search(sentence).group(1))
    assert declared_total == 91, f"docs/PERMISSIONS.md states {declared_total} routes; the matrix is pinned at 91"
    assert declared_total == len(permissions.ROUTE_PERMISSIONS), (
        f"docs/PERMISSIONS.md states {declared_total} routes, ROUTE_PERMISSIONS has {len(permissions.ROUTE_PERMISSIONS)}"
    )

    stated = {level.lower(): int(count) for count, level in LEVEL_COUNT.findall(sentence)}
    computed = {level: sum(1 for value in permissions.ROUTE_PERMISSIONS.values() if value == level) for level in LEVELS}

    missing = sorted(level for level in computed if level not in stated)
    assert not missing, f"docs/PERMISSIONS.md's size sentence does not state {missing}: {sentence}"
    wrong = {level: (stated[level], count) for level, count in computed.items() if stated[level] != count}
    assert not wrong, f"docs/PERMISSIONS.md states (documented, actual) per level {wrong}: {sentence}"
