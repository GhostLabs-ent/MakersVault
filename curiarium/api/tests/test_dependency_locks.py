import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

# PEP 503 normalisation: dependency names compare case-insensitively with any
# run of '-', '_' and '.' collapsed to a single '-'. The pin files spell the same
# package inconsistently (requirements.txt's PyJWT vs the dev lock's pyjwt;
# requirements.lock's typing_extensions vs the dev lock's typing-extensions), so
# both sides must normalise identically or a future direct dependency whose name
# contains an underscore would false-fail the guard.
_PEP503_SEPARATORS = re.compile(r"[-_.]+")


def normalize_name(raw_name: str) -> str:
    name = raw_name.split("[", 1)[0].strip()
    return _PEP503_SEPARATORS.sub("-", name).lower()


def exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        assert separator, f"{path.name} contains a non-exact dependency: {line}"
        pins[normalize_name(name)] = version.strip()
    return pins


def test_runtime_direct_dependencies_match_lock() -> None:
    direct = exact_pins(API_ROOT / "requirements.txt")
    locked = exact_pins(API_ROOT / "requirements.lock")
    assert {name: locked.get(name) for name in direct} == direct


def test_test_direct_dependencies_match_lock() -> None:
    direct = exact_pins(API_ROOT / "requirements-dev.txt")
    locked = exact_pins(API_ROOT / "requirements-dev.lock")
    assert {name: locked.get(name) for name in direct} == direct


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("typing_extensions", "typing-extensions"),
        ("zope.interface", "zope-interface"),
        ("My__Pkg", "my-pkg"),
        ("A..B__C--D", "a-b-c-d"),
        ("pkg[extra]", "pkg"),
    ],
)
def test_normalize_name_collapses_pep503_separators(raw_name: str, expected: str) -> None:
    assert normalize_name(raw_name) == expected


@pytest.mark.parametrize(
    ("txt_name", "lock_name"),
    [
        ("typing_extensions", "typing-extensions"),
        ("zope.interface", "zope-interface"),
        ("My__Pkg", "my-pkg"),
    ],
)
def test_exact_pins_normalises_both_sides(tmp_path: Path, txt_name: str, lock_name: str) -> None:
    txt = tmp_path / "requirements.txt"
    lock = tmp_path / "requirements.lock"
    txt.write_text(f"{txt_name}==1.2.3\n", encoding="utf-8")
    lock.write_text(f"{lock_name}==1.2.3\n", encoding="utf-8")
    expected = {normalize_name(txt_name): "1.2.3"}
    assert exact_pins(txt) == expected
    assert exact_pins(lock) == expected
