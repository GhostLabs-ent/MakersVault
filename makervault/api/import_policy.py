"""Which hosts may see a session cookie, and which URLs are paid or gated.

Two different questions live here, and they are deliberately not the same kind
of check.

*Which hosts may receive a session cookie* is a CLOSED enumerated set: the
credentialed public resolvers in :data:`CREDENTIALED_HOST_MATCHERS`. That set is
the security boundary. No other host - paid, free or otherwise - can ever
receive a cookie, because ``import_service.import_request_headers`` asks
:func:`credentialed_source_for` and attaches nothing when it answers ``None``.
Adding a third credentialed source must be a deliberate, reviewed edit here.

The *purchase-state URL check* is UX, not the boundary. It turns "we fetched a
checkout page and found nothing" into a clear message. Its storefront, path and
query lists are conservative and additive: being incomplete cannot leak
credentials, it only falls back to the generic "no download found" error.

The API never stores, requests or replays purchase state: ``ImportRequest`` has
no payment field, and this module only reads the URL string it is given.
"""

from typing import Optional
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from import_resolvers import is_makerworld_page_host, is_thingiverse_page_host

PAID_IMPORT_DETAIL = (
    "MakersVault does not download paid or account-gated files. "
    "Please supply these files yourself: download them from your account and upload the file or zip."
)

# makerworld matches its exact host plus subdomains; thingiverse is an exact set.
# The predicates - not a duplicated host list - are the single source of truth,
# so this registry and the resolvers cannot drift apart.
CREDENTIALED_HOST_MATCHERS = {
    "makerworld": is_makerworld_page_host,
    "thingiverse": is_thingiverse_page_host,
}

PAYMENT_STOREFRONT_HOSTS = frozenset(
    {"gumroad.com", "patreon.com", "ko-fi.com", "buymeacoffee.com", "etsy.com"}
)
PURCHASE_PATH_SEGMENTS = frozenset(
    {
        "checkout",
        "cart",
        "orders",
        "order",
        "payment",
        "payments",
        "purchase",
        "purchases",
        "billing",
        "subscriptions",
        "subscription",
        "redeem",
        "invoice",
        "invoices",
    }
)
PURCHASE_QUERY_KEYS = frozenset(
    {
        "checkout",
        "order",
        "order_id",
        "purchase",
        "purchase_token",
        "transaction_id",
        "receipt",
        "payment_intent",
        "license_key",
    }
)


def credentialed_source_for(host: str) -> Optional[str]:
    """The credentialed source this host belongs to, or None.

    This is the only gate that decides whether a session cookie may be attached.
    """
    host = (host or "").lower()
    for source, is_page_host in CREDENTIALED_HOST_MATCHERS.items():
        if is_page_host(host):
            return source
    return None


def purchase_state_reason(url: str) -> Optional[str]:
    """Why this URL is paid/purchase state, or None. URL-only: no I/O, no DNS."""
    value = (url or "").strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    for storefront in PAYMENT_STOREFRONT_HOSTS:
        if host == storefront or host.endswith(f".{storefront}"):
            return f"URL points at the storefront {storefront}"
    for segment in (parsed.path or "").lower().split("/"):
        if segment and segment in PURCHASE_PATH_SEGMENTS:
            return f"URL path contains {segment!r}"
    for key in parse_qs(parsed.query):
        if key.lower() in PURCHASE_QUERY_KEYS:
            return f"URL query contains {key!r}"
    return None


def refuse_paid_or_gated(url: str) -> None:
    """Raise 403 with PAID_IMPORT_DETAIL when `url` is paid or gated."""
    if purchase_state_reason(url):
        raise HTTPException(status_code=403, detail=PAID_IMPORT_DETAIL)
