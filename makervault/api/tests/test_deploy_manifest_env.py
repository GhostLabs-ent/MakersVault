"""Guard the production deploy manifest against dropping operator-tunable keys.

The API reads a stable set of environment variables, and the production Compose
manifest is what forwards an operator's `.env` value into the container. A key
that the code reads but the manifest forgets silently falls back to its code
default no matter what the operator sets; a key the manifest forwards but the
code never reads is an inert no-op (the `AUTH_TOKEN_TTL` bug class).

The real defaults are parsed out of source rather than imported, so this runs
without FastAPI, sqlmodel, or a database. The manifest and the architecture
docs live above the API directory, so the tests that read them skip inside the
container, where `makervault/api` is the whole build context. The derivation
tests and the `.env.example` guard keep running in-image.

The operator-facing docs are guarded too: every key this change adds must appear
in `makervault/api/.env.example` and have a row in
`makervault/docs/architecture/CONFIGURATION.md`, otherwise a key can be
forwarded and defaulted correctly while remaining undiscoverable.
"""

import re
from pathlib import Path

import pytest
import yaml

API_ROOT = Path(__file__).resolve().parents[1]
MAKERVAULT_ROOT = API_ROOT.parent
MANIFEST_PATH = MAKERVAULT_ROOT / "docker-compose.deploy.yml"
CONFIGURATION_PATH = MAKERVAULT_ROOT / "docs" / "architecture" / "CONFIGURATION.md"

requires_manifest = pytest.mark.skipif(
    not MANIFEST_PATH.exists(),
    reason="deploy manifest is outside the API image build context",
)
requires_docs = pytest.mark.skipif(
    not CONFIGURATION_PATH.exists(),
    reason="architecture docs are outside the API image build context",
)

# Variables read through `os.getenv(<name>)` inside main.py's CORS loop over a
# tuple. The regex only sees quoted literals, so these are listed by hand.
INDIRECT_READS: set[str] = {"PUBLIC_URL", "VITE_API_URL"}

# Keys the Compose files themselves consume, or that only exist to place a
# volume; the API never reads them.
COMPOSE_ONLY_KEYS: set[str] = {
    "API_IMAGE",
    "WEB_IMAGE",
    "API_PORT",
    "WEB_PORT",
    "IMPORT_MOUNT_PATH_HOST",
}

# Pinned to container paths in the manifest by design.
PINNED_TO_CONTAINER_PATHS: set[str] = {"FILE_STORAGE", "DB_URL"}
# Legacy alias of IMPORT_MOUNT_PATH, which is already forwarded.
LEGACY_ALIASES: set[str] = {"MOUNT_IMPORT_PATH"}
# Deprecated no-op, deliberately not forwarded.
DEPRECATED_NO_OPS: set[str] = {"AUTH_TOKEN_TTL"}

# Opt-in BTRFS sidecar keys, deliberately not forwarded. An unconfigured
# deployment must not point at a sidecar that is not running, so the manifest
# leaves both unset and the code default (empty) means "disabled". They are
# documented in `.env.example` and CONFIGURATION.md, and the "not forwarded"
# half is pinned in test_snapshot_btrfs.py.
SIDECAR_KEYS: set[str] = {"SNAPSHOT_BTRFS_SIDECAR_URL", "SNAPSHOT_BTRFS_SIDECAR_TOKEN"}

EXCEPTIONS: set[str] = PINNED_TO_CONTAINER_PATHS | LEGACY_ALIASES | DEPRECATED_NO_OPS | SIDECAR_KEYS

# If the regex silently stops matching, the derived set shrinks and every
# forwarding test keeps passing over less and less. These sentinels and per-file
# minimum counts make a cosmetic refactor that breaks the idiom fail loudly.
REQUIRED_KEYS: set[str] = {
    "AUTH_ACCESS_TOKEN_TTL",
    "AUTH_REFRESH_TTL_SECONDS",
    "AUTH_ALLOW_INSECURE_DEFAULTS",
    "AUTH_TOKEN_TTL",
    "MAX_UPLOAD_MB",
    "IMPORT_MAX_MB",
    "IMPORT_ZIP_MAX_MB",
    "ASSET_FILE_MAX_MB",
    "ASSET_FILE_TOTAL_MAX_MB",
    "ASSET_FILE_MAX_COUNT",
    "IMPORT_MOUNT_PATH",
    "LOGIN_MAX_FAILURES",
    "CHOWN_MODE",
}

MINIMUM_KEY_COUNTS = {
    "config.py": 18,
    "auth.py": 7,
    "docker-entrypoint.sh": 3,
}

# The entries added by this change. Only these carry default-equality checks.
# PUID and PGID predate the change. Pre-existing manifest entries are exempt
# because IMPORT_MOUNT_ON_STARTUP deliberately diverges (code default True,
# manifest false, documented), IMPORT_MOUNT_* stay as-is per the ticket, and
# AUTH_USERNAME/AUTH_PASSWORD/AUTH_SECRET intentionally default to the published
# sample values so the API fails loudly.
NEW_KEYS: set[str] = {
    "AUTH_ACCESS_TOKEN_TTL",
    "AUTH_REFRESH_TTL_SECONDS",
    "AUTH_ALLOW_INSECURE_DEFAULTS",
    "MAX_UPLOAD_MB",
    "IMPORT_MAX_MB",
    "IMPORT_ZIP_MAX_MB",
    "IMPORT_TIMEOUT_SECONDS",
    "IMPORT_MAX_REDIRECTS",
    "IMPORT_HTML_MAX_KB",
    "ASSET_FILE_MAX_MB",
    "ASSET_FILE_TOTAL_MAX_MB",
    "ASSET_FILE_MAX_COUNT",
    "MAKERWORLD_COOKIE",
    "THINGIVERSE_COOKIE",
    "CHOWN_MODE",
    "SNAPSHOT_POLICY_PREDELETE",
    "SNAPSHOT_POLICY_PREPURGE",
    "SNAPSHOT_POLICY_PREBULK",
    "SNAPSHOT_REQUIRE_CAPABILITY",
    "SNAPSHOT_SCHEDULE_ENABLED",
    "SNAPSHOT_SCHEDULE_HOURS",
    "SNAPSHOT_SCHEDULE_CHECK_SECONDS",
    "SNAPSHOT_SCHEDULE_START_DELAY_SECONDS",
    # OIDC / SSO (Mf-4c24). All ten are read by config.py and forwarded by the
    # deploy manifest, so they carry the same fallback-equality contract.
    "OIDC_ENABLED",
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_SCOPES",
    "OIDC_GROUPS_CLAIM",
    "OIDC_ALLOWED_GROUPS",
    "OIDC_ALLOWED_DOMAINS",
    "OIDC_EDITOR_GROUPS",
    "OIDC_ADMIN_GROUPS",
}

PYTHON_SOURCES = ("config.py", "auth.py", "db.py", "main.py", "import_resolvers.py")
ENTRYPOINT_SOURCE = "docker-entrypoint.sh"

ENV_INT_RE = re.compile(r'env_int\(\s*"(?P<name>[A-Z0-9_]+)"\s*,\s*(?P<default>\d+|[A-Z][A-Z0-9_]*)\s*\)')
ENV_BOOL_RE = re.compile(r'env_bool\(\s*"(?P<name>[A-Z0-9_]+)"\s*,\s*(?P<default>True|False)\s*\)')
INT_GETENV_RE = re.compile(r'int\(os\.getenv\(\s*"(?P<name>[A-Z0-9_]+)"\s*,\s*"(?P<default>\d+)"\s*\)\s*\)')
INT_PRODUCT_RE = re.compile(
    r'int\(os\.getenv\(\s*"(?P<name>[A-Z0-9_]+)"\s*,\s*str\((?P<expression>[\d\s*]+)\)\s*\)\s*\)'
)
STRING_GETENV_RE = re.compile(r'os\.getenv\(\s*"(?P<name>[A-Z0-9_]+)"(?:\s*,\s*"(?P<default>[^"]*)")?\s*\)')
SHELL_DEFAULT_RE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+):-(?P<default>[^}]*)\}")
MANIFEST_PASSTHROUGH_RE = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+):-(?P<default>.*)\}$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _integer_default(token: str) -> int | str:
    """A numeric token is an int; an all-caps token names another constant."""
    if token.isdigit():
        return int(token)
    return token


def _product(expression: str) -> int:
    product = 1
    for factor in expression.split("*"):
        product *= int(factor.strip())
    return product


def _python_env_reads(text: str) -> dict[str, object]:
    """Every literal environment access, with its un-resolved default."""
    raw: dict[str, object] = {}

    # Specific idioms first so the generic string form cannot downgrade an int
    # or bool default to a string.
    for match in ENV_INT_RE.finditer(text):
        raw.setdefault(match.group("name"), _integer_default(match.group("default")))
    for match in ENV_BOOL_RE.finditer(text):
        raw.setdefault(match.group("name"), match.group("default") == "True")
    for match in INT_GETENV_RE.finditer(text):
        raw.setdefault(match.group("name"), int(match.group("default")))
    for match in INT_PRODUCT_RE.finditer(text):
        raw.setdefault(match.group("name"), _product(match.group("expression")))
    for match in STRING_GETENV_RE.finditer(text):
        raw.setdefault(match.group("name"), match.group("default"))

    return raw


def _shell_env_reads(text: str) -> dict[str, object]:
    return {match.group("name"): match.group("default") for match in SHELL_DEFAULT_RE.finditer(text)}


def _resolve_constants(raw: dict[str, object]) -> dict[str, object]:
    """Resolve a string default that names another constant, recursively."""
    resolved: dict[str, object] = {}

    def resolve(name: str, trail: set[str]) -> object:
        if name in resolved:
            return resolved[name]
        assert name not in trail, f"environment default constant cycle: {' -> '.join(sorted(trail | {name}))}"
        value = raw[name]
        if isinstance(value, str) and value in raw:
            value = resolve(value, trail | {name})
        resolved[name] = value
        return value

    for name in raw:
        resolve(name, set())
    return resolved


def _derive_by_file() -> dict[str, dict[str, object]]:
    derived: dict[str, dict[str, object]] = {}
    for filename in PYTHON_SOURCES:
        raw = _python_env_reads(_read_text(API_ROOT / filename))
        derived[filename] = _resolve_constants(raw)
    entrypoint_raw = _shell_env_reads(_read_text(API_ROOT / ENTRYPOINT_SOURCE))
    derived[ENTRYPOINT_SOURCE] = _resolve_constants(entrypoint_raw)
    return derived


def _derived_defaults() -> dict[str, object]:
    combined: dict[str, object] = {}
    for defaults in _derive_by_file().values():
        combined.update(defaults)
    return combined


def _passthrough_fallback(value: str) -> str | None:
    """The `:-` default of `${KEY:-default}`, or None for a literal value."""
    match = MANIFEST_PASSTHROUGH_RE.match(value)
    if match is None:
        return None
    return match.group("default")


def _manifest_environment() -> dict[str, str | None]:
    data = yaml.safe_load(_read_text(MANIFEST_PATH))
    environment = data["services"]["api"]["environment"]
    assert isinstance(environment, list), "docker-compose.deploy.yml api environment must be a list"
    values: dict[str, str | None] = {}
    for entry in environment:
        # The mapping form would silently hide keys from this guard.
        assert isinstance(entry, str), (
            "docker-compose.deploy.yml api environment entries must be KEY=value strings; "
            f"found {entry!r}"
        )
        key, separator, value = entry.partition("=")
        assert separator, f"docker-compose.deploy.yml api environment entry has no '=': {entry!r}"
        values[key] = _passthrough_fallback(value)
    return values


def _env_example_keys() -> set[str]:
    """Parse KEY=value assignments, skipping blanks and comments."""
    keys: set[str] = set()
    for raw in _read_text(API_ROOT / ".env.example").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, _ = line.partition("=")
        if not separator:
            continue
        keys.add(name.strip())
    return keys


def _configuration_rows() -> list[str]:
    """Every CONFIGURATION.md row whose first column is a backticked variable."""
    return [line for line in _read_text(CONFIGURATION_PATH).splitlines() if line.startswith("| `")]


def test_derivation_sentinels() -> None:
    by_file = _derive_by_file()
    all_keys: set[str] = set()
    for keys in by_file.values():
        all_keys |= set(keys)

    missing = REQUIRED_KEYS - all_keys
    assert not missing, f"environment derivation no longer finds these keys: {sorted(missing)}"

    # A cosmetic refactor that breaks an idiom can still find every sentinel
    # while silently dropping neighbour keys; the per-file counts catch that.
    for filename, minimum in MINIMUM_KEY_COUNTS.items():
        found = len(by_file[filename])
        assert found >= minimum, (
            f"environment derivation found only {found} keys in {filename}, expected at least {minimum}; "
            "an idiom regex probably stopped matching"
        )


@requires_manifest
def test_every_operator_tunable_api_key_is_forwarded() -> None:
    derived = set(_derived_defaults())
    manifest = _manifest_environment()

    missing = derived - EXCEPTIONS - set(manifest)
    assert not missing, (
        "docker-compose.deploy.yml api environment does not forward these code-read keys: "
        f"{sorted(missing)}"
    )


@requires_manifest
def test_auth_keys_forwarded_are_exactly_the_ones_auth_reads() -> None:
    expected = set(_derive_by_file()["auth.py"]) - {"AUTH_TOKEN_TTL"}
    forwarded = {key for key in _manifest_environment() if key.startswith("AUTH_")}

    assert forwarded == expected, (
        "AUTH_* forwarding drifted from auth.py: "
        f"manifest-only={sorted(forwarded - expected)}, missing={sorted(expected - forwarded)}"
    )


@requires_manifest
def test_deprecated_token_ttl_is_not_forwarded() -> None:
    assert "AUTH_TOKEN_TTL" not in _manifest_environment(), (
        "docker-compose.deploy.yml forwards AUTH_TOKEN_TTL, which is a deprecated no-op; "
        "an inert knob looks like it still configures token lifetime"
    )


@requires_manifest
def test_manifest_fallbacks_match_code_defaults() -> None:
    defaults = _derived_defaults()
    manifest = _manifest_environment()

    for key in sorted(NEW_KEYS):
        assert key in manifest, f"docker-compose.deploy.yml api environment does not forward {key}"
        fallback = manifest[key]
        code_default = defaults[key]

        if key == "ASSET_FILE_MAX_MB":
            # Empty is the point: env_int then falls through to IMPORT_MAX_MB.
            assert fallback in {"", str(code_default)}, (
                f"{key} fallback {fallback!r} must be empty or match the code default {code_default!r}"
            )
            if fallback == "":
                assert code_default == defaults["IMPORT_MAX_MB"], (
                    f"empty {key} must resolve to IMPORT_MAX_MB {defaults['IMPORT_MAX_MB']!r}, "
                    f"got {code_default!r}"
                )
            continue

        if key in {"MAKERWORLD_COOKIE", "THINGIVERSE_COOKIE"}:
            assert fallback == "", f"{key} fallback must be empty, got {fallback!r}"
            continue

        if isinstance(code_default, bool):
            assert fallback is not None and fallback.lower() == str(code_default).lower(), (
                f"{key} fallback {fallback!r} does not match code default {code_default!r}"
            )
        elif isinstance(code_default, int):
            assert fallback is not None and int(fallback) == code_default, (
                f"{key} fallback {fallback!r} does not match code default {code_default!r}"
            )
        else:
            assert fallback == code_default, (
                f"{key} fallback {fallback!r} does not match code default {code_default!r}"
            )


@requires_manifest
def test_manifest_api_keys_are_all_read_by_something() -> None:
    known = set(_derived_defaults()) | INDIRECT_READS | COMPOSE_ONLY_KEYS | EXCEPTIONS
    unknown = set(_manifest_environment()) - known

    assert not unknown, (
        "docker-compose.deploy.yml forwards keys nothing reads (an inert knob): "
        f"{sorted(unknown)}"
    )


def test_env_example_documents_new_keys() -> None:
    # Presence only: the sample values are deliberately pinned samples, so they
    # are not required to equal a code default here.
    missing = NEW_KEYS - _env_example_keys()
    assert not missing, f"makervault/api/.env.example does not document these keys: {sorted(missing)}"


@requires_docs
def test_configuration_docs_document_new_keys() -> None:
    rows = _configuration_rows()
    missing = sorted(key for key in NEW_KEYS if not any(row.startswith(f"| `{key}`") for row in rows))
    assert not missing, f"CONFIGURATION.md has no table row for these keys: {missing}"
