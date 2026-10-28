import os


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
