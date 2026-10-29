"""Guard the operator log hygiene contract (M3-7bb7) against config drift.

This is a config guard, not a behaviour test: it cannot start nginx or uvicorn,
so it pins the static files that make the runtime behaviour true. A signed file
grant is a bearer credential carried in the query string, so the nginx access
log format must log the request line without the query, uvicorn's own access log
must be off, and the container smoke test must keep proving both with a canary.
It also pins the retirement of the old `?token=` credential, so a later edit
cannot quietly bring the query-string bearer token back.

Pure pathlib with no imports from the API, consistent with the other config and
docs guards. The nginx config, the smoke script and the web sources live outside
the API directory, so the module skips itself in the container, where
`makervault/api` is the whole build context. Requiring every host-only path to be
missing keeps a half-deleted checkout failing loudly instead of skipping.
"""

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MAKERVAULT_ROOT = API_ROOT.parent

NGINX_CONF_PATH = MAKERVAULT_ROOT / "web" / "nginx.conf"
WEB_SRC_DIR = MAKERVAULT_ROOT / "web" / "src"
SMOKE_SCRIPT_PATH = MAKERVAULT_ROOT / "scripts" / "container-smoke.sh"
# Both of these are inside the API build context, so they exist in the image too
# and are deliberately not part of the skip decision below.
DOCKERFILE_PATH = API_ROOT / "Dockerfile"
AUTH_MODULE_PATH = API_ROOT / "auth.py"

# The host-only half of the guard: none of these paths can exist inside the API
# image, because the image builds from `makervault/api` alone.
HOST_ONLY_PATHS = (NGINX_CONF_PATH, WEB_SRC_DIR, SMOKE_SCRIPT_PATH)

if not any(path.exists() for path in HOST_ONLY_PATHS):
    pytest.skip(
        "log hygiene guard is host-only (the API image builds from makervault/api, so "
        "makervault/web/ and makervault/scripts/ are absent)",
        allow_module_level=True,
    )

LOG_FORMAT_NAME = "makervault"
# The request line must be rebuilt from these three variables. $uri is the
# normalised path with the query string already stripped.
REQUIRED_FORMAT_VARIABLES = ("$request_method", "$uri", "$server_protocol")
# Variables that carry the query string, mirror it, or carry the bearer token
# itself. None of them may appear anywhere in the config.
FORBIDDEN_VARIABLES = (
    "$request_uri",
    "$args",
    "$http_referer",
    "$http_authorization",
)
# `$request` is only forbidden as a whole variable: $request_method,
# $request_time and $request_id are all legitimate and must not trip this.
BARE_REQUEST_VARIABLE_RE = re.compile(r"\$request(?![A-Za-z0-9_])")

# Built from two halves so this guard never matches its own source text, which
# would make the "the retired alias is gone" test unable to pass.
RETIRED_QUERY_ALIASES = ('alias="to' 'ken"', "alias='to" "ken'")
RETIRED_QUERY_PARAMETER = "token_" + "param"
RETIRED_WEB_HELPER = "append" + "TokenToUrl"


def _read_guarded(path: Path) -> str:
    """Read a guarded file, failing loudly if it was renamed or removed."""
    assert path.exists(), f"guarded file {path} is missing; this guard must not pass silently"
    return path.read_text(encoding="utf-8")


def _nginx_conf() -> str:
    return _read_guarded(NGINX_CONF_PATH)


def _directives(text: str, directive: str) -> list[str]:
    """Every statement of `directive`, collapsed to one line each."""
    statements: list[str] = []
    for match in re.finditer(rf"^\s*{directive}\b([^;]*);", text, re.MULTILINE | re.DOTALL):
        statements.append(" ".join(match.group(1).split()))
    return statements


def _log_format_body(name: str) -> str:
    """The format string declared by `log_format name ...`."""
    for statement in _directives(_nginx_conf(), "log_format"):
        tokens = statement.split(maxsplit=1)
        if tokens and tokens[0] == name:
            return tokens[1]
    raise AssertionError(f"nginx.conf declares no log_format named {name!r}")


def _access_log_statements() -> list[str]:
    return _directives(_nginx_conf(), "access_log")


def _nginx_directives_text(text: str) -> str:
    """The config with whole-line `#` comments removed.

    Comments are documentation, not directives: the log_format comment in the
    config deliberately names the forbidden variables (that is what it explains),
    and nginx never expands a variable inside a comment.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _uvicorn_cmd_line() -> str:
    lines = [
        line.strip()
        for line in _read_guarded(DOCKERFILE_PATH).splitlines()
        if line.strip().startswith("CMD ") and "uvicorn" in line
    ]
    assert len(lines) == 1, (
        f"api/Dockerfile must hold exactly one CMD line running uvicorn, found: {lines}"
    )
    return lines[0]


def _smoke_script() -> str:
    return _read_guarded(SMOKE_SCRIPT_PATH)


def test_every_guarded_path_exists() -> None:
    for path in (*HOST_ONLY_PATHS, DOCKERFILE_PATH, AUTH_MODULE_PATH):
        assert path.exists(), f"guarded path {path} is missing"


def test_nginx_declares_the_query_free_log_format() -> None:
    body = _log_format_body(LOG_FORMAT_NAME)
    for variable in REQUIRED_FORMAT_VARIABLES:
        assert variable in body, (
            f"the {LOG_FORMAT_NAME} log_format does not use {variable}; the request line "
            "must be rebuilt from the method, the query-free $uri and the protocol"
        )


def test_nginx_access_log_is_bound_to_that_format() -> None:
    statements = _access_log_statements()
    assert statements, "nginx.conf declares no access_log directive"
    assert any(LOG_FORMAT_NAME in statement.split() for statement in statements), (
        f"no access_log names the {LOG_FORMAT_NAME} format, so nginx falls back to the "
        f"compiled-in `combined` format and logs \"$request\"; found {statements}"
    )


def test_nginx_never_references_a_query_bearing_variable() -> None:
    text = _nginx_directives_text(_nginx_conf())
    for variable in FORBIDDEN_VARIABLES:
        assert variable not in text, (
            f"nginx.conf references {variable}, which carries or mirrors the query string "
            "that holds the signed grant"
        )
    match = BARE_REQUEST_VARIABLE_RE.search(text)
    assert match is None, (
        "nginx.conf logs the bare $request variable, which includes the query string; "
        "log $request_method and $uri instead"
    )


def test_dockerfile_runtime_command_disables_the_uvicorn_access_log() -> None:
    line = _uvicorn_cmd_line()
    assert '"--no-access-log"' in line, (
        "the uvicorn CMD does not pass --no-access-log, so the full request line with its "
        f"signed grant query string reaches the container log: {line}"
    )


def test_smoke_script_sends_a_canary_grant_in_the_query_string() -> None:
    script = _smoke_script()
    assert "canary=" in script, "container-smoke.sh declares no canary value"
    assert "?token=$canary&sig=$canary" in script, (
        "container-smoke.sh does not send a canary through both the token and sig query "
        "parameters, so it cannot prove the grant stays out of the logs"
    )


def test_smoke_script_asserts_the_canary_is_absent_from_both_logs() -> None:
    script = _smoke_script()
    assert "for service in api web" in script, (
        "container-smoke.sh does not read both the api and the web container logs"
    )
    assert 'compose logs --no-color "$service"' in script, (
        "container-smoke.sh does not collect the per-service container log"
    )
    assert 'grep -qF "$canary"' in script, (
        "container-smoke.sh does not fixed-string grep the logs for the canary"
    )
    assert "the $service container log recorded the canary" in script, (
        "container-smoke.sh must fail loudly and name the offending service"
    )


def test_api_auth_module_no_longer_accepts_a_token_query_parameter() -> None:
    text = _read_guarded(AUTH_MODULE_PATH)
    for alias in RETIRED_QUERY_ALIASES:
        assert alias not in text, (
            f"api/auth.py still accepts the retired query-string credential ({alias}); a "
            "grant in the URL is a bearer token that server logs can capture"
        )
    assert RETIRED_QUERY_PARAMETER not in text, (
        "api/auth.py still has a token query parameter, so authentication can happen from "
        "the URL instead of the Authorization header"
    )


def test_web_sources_do_not_append_the_token_to_urls() -> None:
    assert WEB_SRC_DIR.is_dir(), f"{WEB_SRC_DIR} is missing; this guard must not pass silently"
    # Tests are excluded on purpose: a test that asserts the helper is gone has to
    # name it, and only shipped sources can leak a credential into a URL. The
    # scan must still see real sources, or the exclusion would make it vacuous.
    scanned = [
        path
        for pattern in ("*.ts", "*.tsx")
        for path in sorted(WEB_SRC_DIR.rglob(pattern))
        if not path.name.endswith((".test.ts", ".test.tsx"))
    ]
    assert scanned, f"no shipped web sources were scanned under {WEB_SRC_DIR}"
    offenders = [
        path.relative_to(MAKERVAULT_ROOT).as_posix()
        for path in scanned
        if RETIRED_WEB_HELPER in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"web sources still build URLs with {RETIRED_WEB_HELPER}: {offenders}; the token "
        "belongs in the Authorization header, not in a loggable query string"
    )
