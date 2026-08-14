import os


def env_int(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def env_limit_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


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
IMPORT_TIMEOUT_SECONDS = max(1, env_int("IMPORT_TIMEOUT_SECONDS", 30))
IMPORT_MAX_REDIRECTS = env_limit_int("IMPORT_MAX_REDIRECTS", 5, minimum=0)
IMPORT_MAX_MB = env_limit_int("IMPORT_MAX_MB", 512)
FILE_MAX_MB = env_limit_int("FILE_MAX_MB", IMPORT_MAX_MB)
FILE_MAX_BYTES = FILE_MAX_MB * 1024 * 1024
# Compatibility alias for existing import code and v5.0/v5.1 operator settings.
IMPORT_MAX_BYTES = FILE_MAX_BYTES
IMPORT_HTML_MAX_KB = env_int("IMPORT_HTML_MAX_KB", 4096)
IMPORT_HTML_MAX_BYTES = max(64, IMPORT_HTML_MAX_KB) * 1024
STORAGE_RESERVE_MB = env_limit_int("STORAGE_RESERVE_MB", 512, minimum=0)
STORAGE_RESERVE_BYTES = STORAGE_RESERVE_MB * 1024 * 1024
ARCHIVE_MAX_ENTRIES = env_limit_int("ARCHIVE_MAX_ENTRIES", 10000)
ARCHIVE_MAX_SELECTED = env_limit_int("ARCHIVE_MAX_SELECTED", 1000)
ARCHIVE_MAX_EXPANDED_MB = env_limit_int("ARCHIVE_MAX_EXPANDED_MB", 2048)
ARCHIVE_MAX_EXPANDED_BYTES = ARCHIVE_MAX_EXPANDED_MB * 1024 * 1024
ARCHIVE_MAX_RATIO = env_limit_int("ARCHIVE_MAX_RATIO", 200)
ARCHIVE_METADATA_MAX_MB = env_limit_int("ARCHIVE_METADATA_MAX_MB", 16)
ARCHIVE_METADATA_MAX_BYTES = ARCHIVE_METADATA_MAX_MB * 1024 * 1024
IMAGE_MAX_PIXELS = env_limit_int("IMAGE_MAX_PIXELS", 64_000_000)
GENERATED_THUMBNAIL_MAX_MB = env_limit_int("GENERATED_THUMBNAIL_MAX_MB", 8)
GENERATED_THUMBNAIL_MAX_BYTES = GENERATED_THUMBNAIL_MAX_MB * 1024 * 1024
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
