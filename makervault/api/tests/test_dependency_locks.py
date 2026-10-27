from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        assert separator, f"{path.name} contains a non-exact dependency: {line}"
        normalized_name = name.split("[", 1)[0].strip().lower()
        pins[normalized_name] = version.strip()
    return pins


def test_runtime_direct_dependencies_match_lock() -> None:
    direct = exact_pins(API_ROOT / "requirements.txt")
    locked = exact_pins(API_ROOT / "requirements.lock")
    assert {name: locked.get(name) for name in direct} == direct


def test_test_direct_dependencies_match_lock() -> None:
    direct = exact_pins(API_ROOT / "requirements-dev.txt")
    locked = exact_pins(API_ROOT / "requirements-dev.lock")
    assert {name: locked.get(name) for name in direct} == direct
