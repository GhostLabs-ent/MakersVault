"""Page metadata for an import: title, creator, licence and an explicit gate flag.

This module parses HTML/JSON already in hand. It performs no I/O and imports
nothing that can open a connection, so a project can be built from a page whose
files were never downloadable.

The gated rule is load-bearing: only an explicit *boolean* paid flag counts.
The presence of a `price` or `licenceType`/`license` key never does - a licence
identifier is not paid-ness, and treating it as gated would refuse free imports.
"""

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

from import_resolvers import (
    extract_next_data_json,
    is_makerworld_page_host,
    is_printables_page_host,
    is_thingiverse_page_host,
)

# The only keys that prove a page is paid. Each is a boolean flag the site
# itself sets on a model, so the page's own answer is the answer.
GATED_FLAGS = frozenset({"is_purchasable", "purchasable", "paid", "is_paid", "requires_purchase", "is_premium"})


@dataclass(frozen=True)
class PageMetadata:
    title: Optional[str] = None
    creator: Optional[str] = None
    licence: Optional[str] = None
    licence_url: Optional[str] = None
    gated: bool = False
    gated_reason: Optional[str] = None


class _PageParser(HTMLParser):
    """Collects the few tags this module needs; everything else is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title: Optional[str] = None
        self.twitter_title: Optional[str] = None
        self.title_parts: List[str] = []
        self.meta_author: Optional[str] = None
        self.license_links: List[Tuple[Optional[str], str]] = []
        self.json_ld: List[str] = []
        self._in_title = False
        self._in_ld_json = False
        self._ld_parts: List[str] = []
        self._license_href: Optional[str] = None
        self._license_text: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "meta":
            self._meta(attributes)
        elif tag == "title":
            self._in_title = True
        elif tag == "link":
            if self._has_license_rel(attributes):
                self.license_links.append((_clean(attributes.get("href")), ""))
        elif tag == "a":
            # One license anchor at a time; a nested one is not a licence tag.
            if self._license_href is None and self._has_license_rel(attributes):
                self._license_href = _clean(attributes.get("href"))
                self._license_text = []
        elif tag == "script":
            if (attributes.get("type") or "").lower() == "application/ld+json":
                self._in_ld_json = True
                self._ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._license_href is not None:
            self.license_links.append((self._license_href, _first_text("".join(self._license_text)) or ""))
            self._license_href = None
            self._license_text = []
        elif tag == "script" and self._in_ld_json:
            self._in_ld_json = False
            block = "".join(self._ld_parts).strip()
            if block:
                self.json_ld.append(block)
            self._ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_ld_json:
            self._ld_parts.append(data)
        elif self._license_href is not None:
            self._license_text.append(data)

    def _meta(self, attributes: dict) -> None:
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        content = _clean(attributes.get("content"))
        if not content:
            return
        if key == "og:title" and self.og_title is None:
            self.og_title = content
        elif key == "twitter:title" and self.twitter_title is None:
            self.twitter_title = content
        elif key == "author" and self.meta_author is None:
            self.meta_author = content

    @staticmethod
    def _has_license_rel(attributes: dict) -> bool:
        return "license" in (attributes.get("rel") or "").lower().split()


def _clean(value: Any) -> Optional[str]:
    """A non-empty trimmed string, or None; page text is whitespace-happy."""
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


def _dig(data: Any, *path: str) -> Any:
    """Follow dict keys, returning None at the first non-dict value."""
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _person_name(value: Any) -> Optional[str]:
    """The display name of a nested person object, or of a bare string."""
    if isinstance(value, str):
        return _clean(value)
    if not isinstance(value, dict):
        return None
    return _first_text(value.get("name"), value.get("displayName"), value.get("username"))


def _json_ld_objects(blocks: List[str]) -> List[dict]:
    """Every JSON-LD object in the page, flattening `@graph` and lists."""
    objects: List[dict] = []
    for block in blocks:
        try:
            parsed = json.loads(block)
        except ValueError:
            continue
        objects.extend(_flatten_json_ld(parsed))
    return objects


def _flatten_json_ld(data: Any) -> List[dict]:
    if isinstance(data, list):
        return [obj for item in data for obj in _flatten_json_ld(item)]
    if not isinstance(data, dict):
        return []
    graph = data.get("@graph")
    if isinstance(graph, (list, dict)):
        return _flatten_json_ld(graph)
    return [data]


def _json_ld_names(objects: List[dict]) -> List[str]:
    return [name for name in (_clean(obj.get("name")) for obj in objects) if name]


def _json_ld_author(objects: List[dict]) -> Optional[str]:
    for obj in objects:
        author = obj.get("author")
        if isinstance(author, list):
            for entry in author:
                name = _person_name(entry)
                if name:
                    return name
        name = _person_name(author)
        if name:
            return name
    return None


def _is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return bool(parsed.scheme and parsed.netloc)


def _json_ld_licence(objects: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """(licence text, licence url) from `license`/`usageInfo`, or (None, None)."""
    for obj in objects:
        for key in ("license", "usageInfo"):
            value = obj.get(key)
            if isinstance(value, dict):
                value = value.get("url") or value.get("name")
            cleaned = _clean(value)
            if not cleaned:
                continue
            if _is_url(cleaned):
                return None, cleaned
            return cleaned, None
    return None, None


def _html_licence(entries: List[Tuple[Optional[str], str]]) -> Tuple[Optional[str], Optional[str]]:
    """(licence text, licence url) from the page's `rel=license` tags."""
    licence: Optional[str] = None
    licence_url: Optional[str] = None
    for href, text in entries:
        if href and not licence_url:
            licence_url = href
        cleaned = _clean(text)
        if cleaned and not licence:
            licence = cleaned
    return licence, licence_url


def _next_data_overlay(data: Any, page_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Per-host (title, creator) from `__NEXT_DATA__`, or (None, None).

    A missing overlay - or one whose shape this does not know - returns nothing,
    so the generic values stay untouched; only a value this finds overrides one.
    """
    if not isinstance(data, (dict, list)):
        return None, None
    try:
        host = (urlparse(page_url).hostname or "").lower()
    except ValueError:
        return None, None
    if is_makerworld_page_host(host):
        design = _dig(data, "props", "pageProps", "design")
        title = _first_text(_dig(design, "name"), _dig(design, "title"))
        creator = _person_name(_dig(design, "creator")) or _person_name(_dig(design, "designCreator"))
        return title, creator
    if is_printables_page_host(host):
        model = _dig(data, "props", "pageProps", "model") or _dig(data, "props", "pageProps", "print")
        title = _first_text(_dig(model, "name"), _dig(model, "title"))
        creator = _person_name(_dig(model, "designer")) or _person_name(_dig(model, "creator"))
        return title, creator
    if is_thingiverse_page_host(host):
        thing = _dig(data, "props", "pageProps", "thing")
        title = _first_text(_dig(thing, "name"), _dig(thing, "title"))
        return title, _person_name(_dig(thing, "creator"))
    return None, None


def _gated_flag(data: Any) -> Optional[str]:
    """The first definitive paid flag that is literally True, else None.

    Only a JSON boolean counts. A string "true" or a non-empty `price` object is
    not proof, and refusing on it would turn a free import into a gated one.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = (key or "").lower()
            if lowered in GATED_FLAGS and value is True:
                return lowered
            found = _gated_flag(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _gated_flag(item)
            if found:
                return found
    return None


def parse_page_metadata(html: str, page_url: str) -> PageMetadata:
    """Title, creator, licence and gate state from one page's HTML.

    `page_url` selects the per-host overlay only; no URL here is ever fetched.
    """
    page = html or ""
    parser = _PageParser()
    parser.feed(page)
    parser.close()
    json_ld = _json_ld_objects(parser.json_ld)
    next_data = extract_next_data_json(page)

    overlay_title, overlay_creator = _next_data_overlay(next_data, page_url)
    licence, licence_url = _html_licence(parser.license_links)
    ld_licence, ld_licence_url = _json_ld_licence(json_ld)
    flag = _gated_flag(next_data) if isinstance(next_data, (dict, list)) else None
    if flag is None:
        flag = _gated_flag(json_ld)
    return PageMetadata(
        title=_first_text(overlay_title, parser.og_title, parser.twitter_title, " ".join("".join(parser.title_parts).split()), *_json_ld_names(json_ld)),
        creator=_first_text(overlay_creator, parser.meta_author, _json_ld_author(json_ld)),
        licence=licence or ld_licence,
        licence_url=licence_url or ld_licence_url,
        gated=flag is not None,
        gated_reason=f"page flag {flag!r} is true" if flag else None,
    )
