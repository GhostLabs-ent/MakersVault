"""Strict, origin-bound WebAuthn configuration for Gate 11E."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from models import AuthenticatorPolicy, UserAccount
from security_config import PRODUCTION_ENV, load_security_config


RP_NAME_MAX_LENGTH = 64
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class PasskeyConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PasskeyConfig:
    enabled: bool
    rp_id: Optional[str]
    origin: Optional[str]
    rp_name: str


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _valid_rp_id(value: str) -> bool:
    if not value or len(value) > 253 or value != value.lower():
        return False
    if (
        ":" in value
        or "/" in value
        or _is_ip_address(value)
        or value.endswith(".local")
    ):
        return False
    if value == "localhost":
        return True
    labels = value.rstrip(".").split(".")
    return len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)


def _normalize_origin(value: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None, None, None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None, None, None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    default_port = 80 if scheme == "http" else 443
    authority = hostname if port in {None, default_port} else f"{hostname}:{port}"
    return f"{scheme}://{authority}", scheme, hostname


def load_passkey_config(
    environ: Optional[Mapping[str, str]] = None,
) -> PasskeyConfig:
    source = os.environ if environ is None else environ
    rp_id = source.get("WEBAUTHN_RP_ID", "").strip()
    origin = source.get("WEBAUTHN_ORIGIN", "").strip()
    rp_name = source.get("WEBAUTHN_RP_NAME", "MakersVault").strip()
    environment = load_security_config(source).environment

    if not rp_id and not origin:
        return PasskeyConfig(False, None, None, rp_name or "MakersVault")

    errors: list[str] = []
    if not rp_id or not origin:
        errors.append("WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN must be configured together.")
    if rp_id and not _valid_rp_id(rp_id):
        errors.append(
            "WEBAUTHN_RP_ID must be a lowercase DNS name without a scheme, port, or IP address."
        )
    normalized_origin, scheme, hostname = _normalize_origin(origin)
    if origin and normalized_origin is None:
        errors.append(
            "WEBAUTHN_ORIGIN must be one exact HTTP(S) origin without a non-root path."
        )
    if not rp_name or len(rp_name) > RP_NAME_MAX_LENGTH:
        errors.append("WEBAUTHN_RP_NAME must contain between 1 and 64 characters.")
    if rp_id == "localhost" and environment == PRODUCTION_ENV:
        errors.append("localhost WebAuthn is available only in development or test.")
    if scheme == "http" and not (
        hostname == "localhost" and environment != PRODUCTION_ENV
    ):
        errors.append("WebAuthn requires HTTPS; HTTP is allowed only for localhost development.")
    if hostname and rp_id and hostname != rp_id and not hostname.endswith(f".{rp_id}"):
        errors.append("WEBAUTHN_ORIGIN must use the RP ID hostname or one of its subdomains.")

    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise PasskeyConfigurationError(
            "MakersVault passkey configuration is invalid:\n" + details
        )
    return PasskeyConfig(True, rp_id, normalized_origin, rp_name)


def require_passkey_config(
    environ: Optional[Mapping[str, str]] = None,
) -> PasskeyConfig:
    config = load_passkey_config(environ)
    if not config.enabled:
        raise PasskeyConfigurationError(
            "Passkeys require WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN configuration."
        )
    return config


def validate_passkey_runtime(
    database_engine: Engine,
    environ: Optional[Mapping[str, str]] = None,
) -> PasskeyConfig:
    config = load_passkey_config(environ)
    if config.enabled:
        return config
    with Session(database_engine) as session:
        enrolled = session.exec(
            select(UserAccount.id).where(UserAccount.mfa_enabled.is_(True)).limit(1)
        ).first()
        policy = session.get(AuthenticatorPolicy, "global")
    if enrolled is not None or (policy is not None and policy.mode != "optional"):
        raise PasskeyConfigurationError(
            "Stored MFA state requires valid WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN configuration."
        )
    return config
