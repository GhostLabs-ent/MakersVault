import os
from typing import Optional


def env_int(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


IMPORT_ALLOWED_EXTS = {".stl", ".3mf", ".step", ".stp", ".lbrn", ".lbrn2", ".zip"}
IMPORT_EXT_PRIORITY = [".3mf", ".stl", ".step", ".stp", ".lbrn2", ".lbrn", ".zip"]
IMPORT_BLOCKED_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".jfif",
    ".tif",
    ".tiff",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".json",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}
IMPORT_TIMEOUT_SECONDS = env_int("IMPORT_TIMEOUT_SECONDS", 30)
IMPORT_MAX_REDIRECTS = env_int("IMPORT_MAX_REDIRECTS", 5)
IMPORT_MAX_MB = env_int("IMPORT_MAX_MB", 512)
IMPORT_MAX_BYTES = max(1, IMPORT_MAX_MB) * 1024 * 1024
IMPORT_ZIP_MAX_MB = env_int("IMPORT_ZIP_MAX_MB", 2048)
IMPORT_ZIP_MAX_BYTES = max(1, IMPORT_ZIP_MAX_MB) * 1024 * 1024
IMPORT_HTML_MAX_KB = env_int("IMPORT_HTML_MAX_KB", 4096)
IMPORT_HTML_MAX_BYTES = max(64, IMPORT_HTML_MAX_KB) * 1024

# Direct (non-import) upload cap. The reverse proxy in front of this API should
# enforce the same ceiling; nginx defaults to 1 MB unless configured otherwise.
# 0 disables the check (not recommended).
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 4096)
MAX_UPLOAD_BYTES = max(0, MAX_UPLOAD_MB) * 1024 * 1024

# Supporting-file caps. The per-file cap defaults to the import cap, so an
# existing deployment keeps refusing the bytes it refused before; the total and
# the count are new ceilings. 0 disables that check.
ASSET_FILE_MAX_MB = env_int("ASSET_FILE_MAX_MB", IMPORT_MAX_MB)
ASSET_FILE_MAX_BYTES = max(0, ASSET_FILE_MAX_MB) * 1024 * 1024
ASSET_FILE_TOTAL_MAX_MB = env_int("ASSET_FILE_TOTAL_MAX_MB", 2048)
ASSET_FILE_TOTAL_MAX_BYTES = max(0, ASSET_FILE_TOTAL_MAX_MB) * 1024 * 1024
ASSET_FILE_MAX_COUNT = max(0, env_int("ASSET_FILE_MAX_COUNT", 50))
IMPORT_USER_AGENT = "MakerVault/1.0"
IMPORT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

MOUNT_IMPORT_PATH = (os.getenv("IMPORT_MOUNT_PATH") or os.getenv("MOUNT_IMPORT_PATH") or "").strip()
MOUNT_IMPORT_EXTS_RAW = os.getenv("IMPORT_MOUNT_EXTS", "").strip()
MOUNT_IMPORT_INCLUDE_HIDDEN = env_bool("IMPORT_MOUNT_INCLUDE_HIDDEN", False)
MOUNT_IMPORT_ENABLED = env_bool("IMPORT_MOUNT_ON_STARTUP", True)
MOUNT_IMPORT_COPY = env_bool("IMPORT_MOUNT_COPY", True)
DEFAULT_MOUNT_IMPORT_EXTS = {
    ".stl",
    ".3mf",
    ".step",
    ".stp",
    ".obj",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".lbrn",
    ".lbrn2",
    ".zip",
}

# Login throttling: failures are counted per submitted username within the
# window; each repeated lockout strike doubles the lockout, capped at the max.
LOGIN_THROTTLE_ENABLED = env_bool("LOGIN_THROTTLE_ENABLED", True)
LOGIN_MAX_FAILURES = env_int("LOGIN_MAX_FAILURES", 5)
LOGIN_FAILURE_WINDOW_SECONDS = env_int("LOGIN_FAILURE_WINDOW_SECONDS", 900)
LOGIN_LOCKOUT_SECONDS = env_int("LOGIN_LOCKOUT_SECONDS", 300)
LOGIN_MAX_LOCKOUT_SECONDS = env_int("LOGIN_MAX_LOCKOUT_SECONDS", 3600)

# Pre-operation snapshots for the three destructive operations (S3). A policy is
# validated at import: a typo in a policy name must fail the boot, not silently
# turn a refusal into a proceed or the other way round. `warn` proceeds without
# a snapshot and says so; `strict` refuses only when SNAPSHOT_REQUIRE_CAPABILITY
# is set, because an advertised absence with no snapshot method is audited but
# not fatal (Empty trash must stay possible on ext4/tmpfs).
SNAPSHOT_POLICY_WARN = "warn"
SNAPSHOT_POLICY_STRICT = "strict"
SNAPSHOT_POLICIES = frozenset({SNAPSHOT_POLICY_WARN, SNAPSHOT_POLICY_STRICT})


def env_policy(name: str, raw: Optional[str], default: str) -> str:
    """One snapshot-policy value, validated at import: a typo must not be inert."""
    value = (raw or default).strip().lower()
    if value not in SNAPSHOT_POLICIES:
        raise ValueError(f"{name} must be one of {sorted(SNAPSHOT_POLICIES)}; got {value!r}")
    return value


SNAPSHOT_POLICY_PREDELETE = env_policy("SNAPSHOT_POLICY_PREDELETE", os.getenv("SNAPSHOT_POLICY_PREDELETE", "warn"), "warn")
SNAPSHOT_POLICY_PREPURGE = env_policy("SNAPSHOT_POLICY_PREPURGE", os.getenv("SNAPSHOT_POLICY_PREPURGE", "strict"), "strict")
SNAPSHOT_POLICY_PREBULK = env_policy("SNAPSHOT_POLICY_PREBULK", os.getenv("SNAPSHOT_POLICY_PREBULK", "strict"), "strict")
SNAPSHOT_REQUIRE_CAPABILITY = env_bool("SNAPSHOT_REQUIRE_CAPABILITY", False)

# Scheduled library snapshots (S8). The thread starts from `main.lifespan` only
# when this is true, so a deployment that never opted in takes no snapshot
# behind the operator's back. The defaults are the documented ones: daily, a
# five-minute due check, and a one-minute start delay that keeps the first tick
# clear of migrations and the boot guards.
SNAPSHOT_SCHEDULE_ENABLED = env_bool("SNAPSHOT_SCHEDULE_ENABLED", False)
SNAPSHOT_SCHEDULE_HOURS = env_int("SNAPSHOT_SCHEDULE_HOURS", 24)
SNAPSHOT_SCHEDULE_CHECK_SECONDS = env_int("SNAPSHOT_SCHEDULE_CHECK_SECONDS", 300)
SNAPSHOT_SCHEDULE_START_DELAY_SECONDS = env_int("SNAPSHOT_SCHEDULE_START_DELAY_SECONDS", 60)

# BTRFS snapshots are opt-in through a privileged sidecar: an empty URL means
# disabled (the default), never broken. The health probe runs inside every
# capability detection, so its timeout is a hardcoded budget rather than an
# operator-tunable environment key.
SNAPSHOT_BTRFS_SIDECAR_URL = os.getenv("SNAPSHOT_BTRFS_SIDECAR_URL", "")
SNAPSHOT_BTRFS_SIDECAR_TOKEN = os.getenv("SNAPSHOT_BTRFS_SIDECAR_TOKEN", "")
SNAPSHOT_BTRFS_TIMEOUT_SECONDS = 1

# External identity provider (OIDC / SSO, Mf-4c24). Opt-in: `OIDC_ENABLED`
# defaults to false and local password login keeps working either way. These are
# plain strings here and are parsed (CSV allow-lists, https-only issuer) by
# `oidc.validate_oidc_configuration()`, which refuses to boot on a partial or
# fail-open configuration. The redirect URI is derived from PUBLIC_URL rather
# than exposed as another knob, so the callback cannot drift from the origin the
# browser actually uses.
OIDC_ENABLED = env_bool("OIDC_ENABLED", False)
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip()
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
# Server-side only: it is never sent to the browser, never logged, and never
# written to an audit row.
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid profile email").strip()
OIDC_GROUPS_CLAIM = os.getenv("OIDC_GROUPS_CLAIM", "groups").strip()
# Allow-lists. Empty means "no restriction from this list", but the validator
# refuses to boot when BOTH are empty: an empty allow-list would admit every
# account the provider will authenticate. When both are set they compose with
# AND, so adding one can only narrow the door.
OIDC_ALLOWED_GROUPS = os.getenv("OIDC_ALLOWED_GROUPS", "").strip()
OIDC_ALLOWED_DOMAINS = os.getenv("OIDC_ALLOWED_DOMAINS", "").strip()
# The only escalation a claim may grant. `admin` has no slot: a group claim must
# never be able to mint an administrator, so `OIDC_ADMIN_GROUPS` exists only to
# be refused at boot rather than silently ignored.
OIDC_EDITOR_GROUPS = os.getenv("OIDC_EDITOR_GROUPS", "").strip()
OIDC_ADMIN_GROUPS = os.getenv("OIDC_ADMIN_GROUPS", "").strip()
