import os
import subprocess
import sys

import pytest

from security_config import (
    SecurityConfigurationError,
    load_and_validate_security_config,
)


SAFE_PRODUCTION = {
    "MAKERSVAULT_ENV": "production",
    "AUTH_USERNAME": "admin",
    "AUTH_PASSWORD": "a-long-unique-password",
    "AUTH_SECRET": "0123456789abcdef0123456789abcdef",
    "AUTH_TOKEN_TTL": "43200",
}


def test_production_config_accepts_explicit_safe_values() -> None:
    config = load_and_validate_security_config(SAFE_PRODUCTION)

    assert config.environment == "production"
    assert config.username == "admin"
    assert config.token_ttl == 43200


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"AUTH_PASSWORD": ""}, "AUTH_PASSWORD is required"),
        ({"AUTH_SECRET": ""}, "AUTH_SECRET is required"),
        ({"AUTH_PASSWORD": "super-secret"}, "published placeholder"),
        ({"AUTH_SECRET": "changeme-secret"}, "published placeholder"),
        ({"AUTH_SECRET": "too-short"}, "at least 32 bytes"),
        ({"AUTH_TOKEN_TTL": "0"}, "greater than zero"),
    ],
)
def test_production_config_fails_closed(overrides: dict[str, str], expected: str) -> None:
    values = {**SAFE_PRODUCTION, **overrides}

    with pytest.raises(SecurityConfigurationError, match=expected):
        load_and_validate_security_config(values)


def test_production_is_the_default_environment() -> None:
    values = {key: value for key, value in SAFE_PRODUCTION.items() if key != "MAKERSVAULT_ENV"}

    config = load_and_validate_security_config(values)

    assert config.environment == "production"


def test_explicit_test_environment_can_use_fixture_credentials() -> None:
    config = load_and_validate_security_config(
        {
            "MAKERSVAULT_ENV": "test",
            "AUTH_USERNAME": "admin",
            "AUTH_PASSWORD": "fixture",
            "AUTH_SECRET": "fixture",
        }
    )

    assert config.environment == "test"


def test_invalid_environment_is_rejected() -> None:
    values = {**SAFE_PRODUCTION, "MAKERSVAULT_ENV": "staging-ish"}

    with pytest.raises(SecurityConfigurationError, match="must be one of"):
        load_and_validate_security_config(values)


def test_api_startup_rejects_missing_production_secrets() -> None:
    environment = os.environ.copy()
    environment["MAKERSVAULT_ENV"] = "production"
    environment.pop("AUTH_PASSWORD", None)
    environment.pop("AUTH_SECRET", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi.testclient import TestClient; "
                "from main import app; "
                "TestClient(app).__enter__()"
            ),
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "AUTH_PASSWORD is required" in result.stderr
    assert "AUTH_SECRET is required" in result.stderr
