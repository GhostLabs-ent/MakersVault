"""Guard the auth documentation against drifting from the real token model.

Pure pathlib: the real defaults are parsed out of `auth.py` source rather than
imported, so this runs without FastAPI, sqlmodel, or a database.

The guarded docs live above the API directory, so the module skips itself in the
container, where `makervault/api` is the whole build context.
"""

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MAKERVAULT_ROOT = API_ROOT.parent
REPO_ROOT = MAKERVAULT_ROOT.parent

README_PATH = REPO_ROOT / "README.md"
ENV_EXAMPLE_PATH = API_ROOT / ".env.example"
CONFIGURATION_PATH = MAKERVAULT_ROOT / "docs" / "architecture" / "CONFIGURATION.md"
AUTH_SOURCE_PATH = API_ROOT / "auth.py"

DOC_PATHS = {
    "README.md": README_PATH,
    "makervault/api/.env.example": ENV_EXAMPLE_PATH,
    "makervault/docs/architecture/CONFIGURATION.md": CONFIGURATION_PATH,
}

# Every test below guards README.md and/or CONFIGURATION.md, so the whole module
# is host-only. Both paths are absent inside the API image (build context is
# makervault/api, which becomes /app), but requiring both to be missing keeps a
# half-deleted docs tree failing loudly on a real checkout instead of skipping.
if not README_PATH.exists() and not CONFIGURATION_PATH.exists():
    pytest.skip(
        "auth docs guard is host-only (the API image builds from makervault/api, so "
        "the repo README.md and makervault/docs/ are absent)",
        allow_module_level=True,
    )

README_BASELINE_ANCHOR = "Setting up the .env file"
DEPRECATION_MARKERS = ("deprecated", "ignored", "no-op", "noop")
STALE_TTL_LITERAL = "43200"
PUBLISHED_SAMPLE_VALUES = {"super-secret", "changeme-secret"}
FALSE_VALUES = {"0", "false", "no", "off"}

ACTIVE_TOKEN_TTL_ASSIGNMENT = re.compile(r"^\s*AUTH_TOKEN_TTL\s*=", re.MULTILINE)
# Both TTL regexes match auth.py's exact spelling of `int(os.getenv(<name>, "<digits>"))`
# and `str(<a * b * c>)`. That coupling is deliberate: a cosmetic rewrite of those two
# lines makes this test fail loudly instead of silently skipping the documented default.
ACCESS_TTL_SOURCE = re.compile(
    r'^AUTH_ACCESS_TOKEN_TTL\s*=\s*int\(os\.getenv\(\s*"AUTH_ACCESS_TOKEN_TTL"\s*,\s*"(?P<default>\d+)"\s*\)\s*\)',
    re.MULTILINE,
)
REFRESH_TTL_SOURCE = re.compile(
    r'^AUTH_REFRESH_TTL_SECONDS\s*=\s*int\(os\.getenv\(\s*"AUTH_REFRESH_TTL_SECONDS"\s*,\s*str\((?P<expression>[\d\s*]+)\)\s*\)\s*\)',
    re.MULTILINE,
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read_text(path).splitlines()


def _parse_env_lines(lines: list[str]) -> dict[str, str]:
    """Parse KEY=value assignments, skipping blanks and comments."""
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator:
            continue
        values[name.strip()] = value.strip()
    return values


def _env_sample_values(path: Path) -> dict[str, str]:
    return _parse_env_lines(_lines(path))


def _readme_baseline_block_lines() -> list[str]:
    """The fenced `yaml` block that follows the README's `.env` setup heading."""
    block: list[str] = []
    seen_anchor = False
    inside = False
    for raw in _lines(README_PATH):
        stripped = raw.strip()
        if not seen_anchor:
            if README_BASELINE_ANCHOR in stripped:
                seen_anchor = True
            continue
        if not inside:
            if stripped == "```yaml":
                inside = True
            continue
        if stripped.startswith("```"):
            break
        block.append(raw)
    assert seen_anchor, (
        f"README.md is missing the {README_BASELINE_ANCHOR!r} section that documents the baseline .env file"
    )
    assert block, f"README.md has no fenced yaml baseline .env block after {README_BASELINE_ANCHOR!r}"
    return block


def _readme_baseline_values() -> dict[str, str]:
    return _parse_env_lines(_readme_baseline_block_lines())


def _auth_source() -> str:
    return _read_text(AUTH_SOURCE_PATH)


def _configuration_row(variable: str) -> str:
    """The CONFIGURATION.md table row that documents `variable`."""
    row = next((line for line in _lines(CONFIGURATION_PATH) if line.startswith(f"| `{variable}`")), None)
    assert row is not None, f"CONFIGURATION.md has no {variable} table row"
    return row


def _parsed_access_ttl_default() -> int:
    match = ACCESS_TTL_SOURCE.search(_auth_source())
    assert match, "auth.py no longer defines AUTH_ACCESS_TOKEN_TTL with a string default"
    return int(match.group("default"))


def _parsed_refresh_ttl_default() -> int:
    match = REFRESH_TTL_SOURCE.search(_auth_source())
    assert match, "auth.py no longer defines AUTH_REFRESH_TTL_SECONDS as str(<seconds expression>)"
    expression = match.group("expression")
    product = 1
    for factor in expression.split("*"):
        product *= int(factor.strip())
    return product


def _unmarked_line_mentions(needle: str) -> list[str]:
    """Every doc line mentioning `needle` that carries no deprecation marker."""
    offenders: list[str] = []
    for label, path in DOC_PATHS.items():
        for number, line in enumerate(_lines(path), start=1):
            if needle not in line:
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in DEPRECATION_MARKERS):
                continue
            offenders.append(f"{label}:{number}: {line.strip()}")
    return offenders


def _format_offenders(offenders: list[str]) -> str:
    return "\n".join(f"  {offender}" for offender in offenders)


def test_token_ttl_mentions_are_marked_deprecated() -> None:
    offenders = _unmarked_line_mentions("AUTH_TOKEN_TTL")
    assert not offenders, (
        "these lines mention AUTH_TOKEN_TTL without marking it deprecated/ignored:\n"
        f"{_format_offenders(offenders)}"
    )


def test_stale_ttl_literal_is_marked_deprecated() -> None:
    offenders = _unmarked_line_mentions(STALE_TTL_LITERAL)
    assert not offenders, (
        f"these lines use the stale {STALE_TTL_LITERAL}-second (12-hour) TTL literal "
        "without marking it deprecated/ignored:\n"
        f"{_format_offenders(offenders)}"
    )


def test_no_active_token_ttl_assignment() -> None:
    for label, path in DOC_PATHS.items():
        match = ACTIVE_TOKEN_TTL_ASSIGNMENT.search(_read_text(path))
        assert match is None, (
            f"{label} still tells a new deployment to set AUTH_TOKEN_TTL: {match.group(0).strip()!r}"
        )


def test_docs_name_both_current_ttl_variables() -> None:
    for label, path in DOC_PATHS.items():
        text = _read_text(path)
        for variable in ("AUTH_ACCESS_TOKEN_TTL", "AUTH_REFRESH_TTL_SECONDS"):
            assert variable in text, f"{label} does not mention {variable}"


def test_access_token_ttl_default_matches_auth_module() -> None:
    default = _parsed_access_ttl_default()
    assert default > 0, f"auth.py AUTH_ACCESS_TOKEN_TTL default is not a positive lifetime: {default}"

    for label, values in (
        ("README.md baseline .env block", _readme_baseline_values()),
        ("makervault/api/.env.example", _env_sample_values(ENV_EXAMPLE_PATH)),
    ):
        assert values.get("AUTH_ACCESS_TOKEN_TTL") == str(default), (
            f"{label} does not set AUTH_ACCESS_TOKEN_TTL={default} (found {values.get('AUTH_ACCESS_TOKEN_TTL')!r})"
        )

    row = _configuration_row("AUTH_ACCESS_TOKEN_TTL")
    assert f"`{default}`" in row, f"CONFIGURATION.md AUTH_ACCESS_TOKEN_TTL row does not show {default}: {row}"


def test_auth_samples_avoid_published_defaults() -> None:
    for label, values in (
        ("README.md baseline .env block", _readme_baseline_values()),
        ("makervault/api/.env.example", _env_sample_values(ENV_EXAMPLE_PATH)),
    ):
        for variable in ("AUTH_PASSWORD", "AUTH_SECRET"):
            value = values.get(variable, "")
            assert value, f"{label} leaves {variable} empty"
            assert value not in PUBLISHED_SAMPLE_VALUES, (
                f"{label} uses the published sample value for {variable}: {value!r}"
            )

    for label, path in (
        ("README.md", README_PATH),
        ("makervault/api/.env.example", ENV_EXAMPLE_PATH),
    ):
        for number, line in enumerate(_lines(path), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped.startswith("AUTH_ALLOW_INSECURE_DEFAULTS="):
                continue
            value = stripped.partition("=")[2].strip().lower()
            assert value in FALSE_VALUES, (
                f"{label}:{number} enables the insecure-defaults escape hatch: {stripped}"
            )


def test_refresh_token_ttl_matches_auth_default() -> None:
    default = _parsed_refresh_ttl_default()
    assert default > 0, f"auth.py AUTH_REFRESH_TTL_SECONDS default is not a positive lifetime: {default}"

    for label, values in (
        ("README.md baseline .env block", _readme_baseline_values()),
        ("makervault/api/.env.example", _env_sample_values(ENV_EXAMPLE_PATH)),
    ):
        assert values.get("AUTH_REFRESH_TTL_SECONDS") == str(default), (
            f"{label} does not set AUTH_REFRESH_TTL_SECONDS={default} "
            f"(found {values.get('AUTH_REFRESH_TTL_SECONDS')!r})"
        )

    row = _configuration_row("AUTH_REFRESH_TTL_SECONDS")
    assert f"`{default}`" in row, f"CONFIGURATION.md AUTH_REFRESH_TTL_SECONDS row does not show {default}: {row}"
