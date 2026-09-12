"""The bounded native update is shared by test/runtime, not a system upgrade."""
from pathlib import Path
import re


API_ROOT = Path(__file__).resolve().parents[1]


def test_native_package_lock_is_exact_and_bounded() -> None:
    lines = (API_ROOT / "native-packages.lock").read_text().splitlines()
    assert len(lines) == 6
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*=[0-9][A-Za-z0-9.+:~\-]*", line) for line in lines)
    pins = dict(line.split("=", 1) for line in lines)
    assert set(pins) == {"gzip", "libc-bin", "libc6", "libpcre2-8-0", "libsqlite3-0", "perl-base"}
    assert pins["libc6"] == pins["libc-bin"]


def test_native_update_is_shared_and_restricted() -> None:
    recipe = (API_ROOT / "Dockerfile").read_text()
    base = recipe.split("FROM base AS test", 1)[0]
    assert "COPY native-packages.lock ./" in base
    assert "< native-packages.lock" in base
    for policy in ("APT::Update::Error-Mode=any", "Acquire::AllowInsecureRepositories=false",
                   "APT::Get::AllowUnauthenticated=false", "--no-install-recommends",
                   "--only-upgrade", "--no-remove"):
        assert policy in base
    assert "FROM base AS runtime" in recipe
    assert "--allow-unauthenticated" not in recipe
    assert not re.search(r"\b(?:dist-upgrade|full-upgrade|apt-get\s+upgrade)\b", recipe)
