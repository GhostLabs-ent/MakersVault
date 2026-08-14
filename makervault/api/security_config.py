import os
from dataclasses import dataclass
from typing import Mapping, Optional


PRODUCTION_ENV = "production"
ALLOWED_ENVIRONMENTS = {PRODUCTION_ENV, "development", "test"}
MIN_PASSWORD_LENGTH = 12
MIN_SECRET_BYTES = 32

KNOWN_PASSWORD_PLACEHOLDERS = {
    "admin",
    "change-me",
    "changeme",
    "password",
    "replace-me",
    "super-secret",
}
KNOWN_SECRET_PLACEHOLDERS = {
    "change-me",
    "changeme",
    "changeme-secret",
    "replace-me",
    "replace-with-random-secret",
    "secret",
    "super-secret",
}


class SecurityConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityConfig:
    environment: str
    username: str
    password: str
    secret: str
    token_ttl: int


def load_security_config(environ: Optional[Mapping[str, str]] = None) -> SecurityConfig:
    source = os.environ if environ is None else environ
    environment = source.get("MAKERSVAULT_ENV", PRODUCTION_ENV).strip().lower()
    username = source.get("AUTH_USERNAME", "admin").strip()
    password = source.get("AUTH_PASSWORD", "")
    secret = source.get("AUTH_SECRET", "")
    raw_token_ttl = source.get("AUTH_TOKEN_TTL", "43200").strip()

    try:
        token_ttl = int(raw_token_ttl)
    except ValueError as exc:
        raise SecurityConfigurationError(
            "AUTH_TOKEN_TTL must be a positive integer number of seconds."
        ) from exc

    return SecurityConfig(
        environment=environment,
        username=username,
        password=password,
        secret=secret,
        token_ttl=token_ttl,
    )


def validate_security_config(config: SecurityConfig) -> None:
    errors = []

    if config.environment not in ALLOWED_ENVIRONMENTS:
        errors.append(
            "MAKERSVAULT_ENV must be one of: production, development, test."
        )
    if not config.username:
        errors.append("AUTH_USERNAME must not be empty.")
    if not config.password:
        errors.append("AUTH_PASSWORD is required.")
    if not config.secret:
        errors.append("AUTH_SECRET is required.")
    if config.token_ttl <= 0:
        errors.append("AUTH_TOKEN_TTL must be greater than zero.")

    if config.environment == PRODUCTION_ENV:
        if len(config.password) < MIN_PASSWORD_LENGTH:
            errors.append(
                f"AUTH_PASSWORD must contain at least {MIN_PASSWORD_LENGTH} characters."
            )
        if config.password.strip().lower() in KNOWN_PASSWORD_PLACEHOLDERS:
            errors.append("AUTH_PASSWORD uses a published placeholder value.")
        if len(config.secret.encode("utf-8")) < MIN_SECRET_BYTES:
            errors.append(
                f"AUTH_SECRET must contain at least {MIN_SECRET_BYTES} bytes."
            )
        if config.secret.strip().lower() in KNOWN_SECRET_PLACEHOLDERS:
            errors.append("AUTH_SECRET uses a published placeholder value.")
        if config.secret and config.secret == config.password:
            errors.append("AUTH_SECRET must not be the administrator password.")

    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise SecurityConfigurationError(
            "MakersVault security configuration is invalid:\n"
            f"{details}\n"
            "Run ./scripts/setup-env.sh from the makervault directory or update "
            "the deployment .env file, then restart."
        )


def load_and_validate_security_config(
    environ: Optional[Mapping[str, str]] = None,
) -> SecurityConfig:
    config = load_security_config(environ)
    validate_security_config(config)
    return config
