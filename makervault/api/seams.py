"""The seam between the handlers and the names the frozen test suite patches.

The suite pins its fakes and path roots onto the `main` module -
`monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)`,
`monkeypatch.setattr(main, "start_scan", lambda: True)`, and so on - and
`setattr` runs with `raising=True`, so each name must pre-exist on `main`.
Mf-x9dx forbids test edits, so the routes moved and the patch surface stayed:
`main.py` keeps compatibility re-exports for exactly these names (see its
`__all__`), and the handlers ask this module for the value at call time instead
of holding a copy bound at import:

* the name is resolved against `sys.modules["main"]` when the handler runs, so
  a patch applied after import takes effect, exactly as it did while the handler
  lived in `main.py`;
* the production default is the fallback, so a handler still works when `main`
  is not importable (a service or router test that never builds the app).

`THUMBS` is deliberately NOT resolved here: the thumbnail helper, the thumb
route and `delete_asset_row_only` read `db.THUMBS` at call time instead, because
every storage fixture patches `db.THUMBS` too and the *db* binding is the one
every service already uses.

This module must not import `main` at module level: `main` imports the routers,
so that would be an import cycle - hence the `sys.modules` lookup.

`start_scan`/`scan_status` resolve against MAIN's copy rather than calling
`library_scan` directly, because `main` is the name the suite patches. That is
today's exact semantics, not an accident to be "fixed": a direct
`library_scan.start_scan()` call would silently stop honouring the patch.
"""

import sys

import config
import import_service
import library_scan
import url_utils

_MISSING = object()


def _on_main(name: str):
    """The attribute as `main` has it right now, or `_MISSING` when it has none."""
    module = sys.modules.get("main")
    if module is None:
        return _MISSING
    return getattr(module, name, _MISSING)


def _resolved(name: str, default):
    """`main`'s patched value when there is one, else the production default."""
    value = _on_main(name)
    return default if value is _MISSING else value


def max_upload_bytes() -> int:
    """The direct-upload cap in force now (`main.MAX_UPLOAD_BYTES`, else config)."""
    return _resolved("MAX_UPLOAD_BYTES", config.MAX_UPLOAD_BYTES)


def import_max_bytes() -> int:
    """The imported/supporting-file cap in force now (`main.IMPORT_MAX_BYTES`, else config)."""
    return _resolved("IMPORT_MAX_BYTES", config.IMPORT_MAX_BYTES)


def start_scan() -> bool:
    """Start a scan through `main.start_scan` (the suite's patch point)."""
    return _resolved("start_scan", library_scan.start_scan)()


def scan_status() -> dict:
    """Read scan status through `main.scan_status` (the suite's patch point)."""
    return _resolved("scan_status", library_scan.scan_status)()


def normalize_import_url(url: str) -> str:
    """Normalise an import URL through `main.normalize_import_url` (the patch point)."""
    return _resolved("normalize_import_url", url_utils.normalize_import_url)(url)


def import_asset_from_url(url: str, body):
    """Import a URL through `main.import_asset_from_url` (the suite's patch point)."""
    return _resolved("import_asset_from_url", import_service.import_asset_from_url)(url, body)


def open_import_response(url: str, body):
    """Open the remote response through `main.open_import_response` (the patch point)."""
    return _resolved("open_import_response", import_service.open_import_response)(url, body)


def download_import_to_temp(url: str, body):
    """Fetch an import to a temp file through `main.download_import_to_temp`."""
    return _resolved("download_import_to_temp", import_service.download_import_to_temp)(url, body)


def import_asset_attempt(url: str, body):
    """One single-file attempt through `main.import_asset_attempt` (patch point)."""
    return _resolved("import_asset_attempt", import_service.import_asset_attempt)(url, body)


def download_zip_attempt(url: str, body):
    """One zip attempt through `main.download_zip_attempt` (patch point)."""
    return _resolved("download_zip_attempt", import_service.download_zip_attempt)(url, body)
