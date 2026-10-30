#!/usr/bin/env python3
"""Fail when a product-version mirror drifts from the API's single source (Mf-cvoo).

`curiarium/api/version.py` holds the only version literal a human edits. The
web manifest and its lockfile carry copies because npm needs them, and the two
copies silently rot the moment someone bumps one and forgets the other - the
UI then reports a version the API never served.

    python3 curiarium/scripts/check_version.py

Prints every copy it read, then exits 0 when they all agree and 1 with the
offending path and value on stderr otherwise. To fix a mismatch, edit the
mirrors to match curiarium/api/version.py; never bump a copy on its own.
"""

import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "curiarium" / "api" / "version.py"
PACKAGE = ROOT / "curiarium" / "web" / "package.json"
LOCKFILE = ROOT / "curiarium" / "web" / "package-lock.json"

VERSION_LINE = re.compile('__version__ = "([^"]+)"')


def label(path: Path) -> str:
    """Repository-relative name, so the output reads the same from any cwd."""
    return str(path.relative_to(ROOT))


def read_source_version() -> str:
    match = VERSION_LINE.search(SOURCE.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"{label(SOURCE)}: no __version__ assignment found")
    return match.group(1)


def read_copies() -> list[tuple[str, str]]:
    """Every mirror of the canonical version, in report order."""
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    lockfile = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    return [
        (label(PACKAGE), package["version"]),
        (label(LOCKFILE), lockfile["version"]),
        (f'{label(LOCKFILE)} packages[""]', lockfile["packages"][""]["version"]),
    ]


def main(argv: Sequence[str]) -> int:
    if argv:
        raise SystemExit("check_version.py takes no arguments")
    canonical = read_source_version()
    copies = read_copies()
    print(f"{label(SOURCE)}: {canonical}")
    for name, value in copies:
        print(f"{name}: {value}")

    drifted = [(name, value) for name, value in copies if value != canonical]
    if drifted:
        sys.stdout.flush()  # keep the listing above the error when both are piped
        print(f"version drift: {label(SOURCE)} says {canonical}", file=sys.stderr)
        for name, value in drifted:
            print(f"  {name} says {value}", file=sys.stderr)
        print(f"Edit the mirrors to match {label(SOURCE)}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
