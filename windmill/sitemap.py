"""
sitemap.py — best-effort sitemap fetching for an old site.

Tries a fixed list of candidate paths; follows <sitemapindex> nesting one level deep;
filters out product URLs before returning.

Returns [{url: str, title: str}] — titles are always "" (sitemap has no titles).
Returns []                        if no sitemap is found or all parsing fails.
"""
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests

from redirect_engine import DEFAULT_CONFIG, is_product

CANDIDATE_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
]
# XML namespace used by most sitemaps
_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Konimbo-301-bot/1.0)"}
_TIMEOUT = 10


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200 and resp.content:
            return resp.text
    except Exception:
        pass
    return None


def _loc(elem):
    """Extract <loc> text, handling both namespaced and bare tags."""
    for tag in (f"{{{_NS}}}loc", "loc"):
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return None


def _parse(text: str):
    """
    Returns (page_urls: list[str], child_sitemap_urls: list[str]).
    Handles <urlset> and <sitemapindex>, with or without XML namespace.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []

    local = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if local == "sitemapindex":
        children = []
        for child in root:
            loc = _loc(child)
            if loc:
                children.append(loc)
        return [], children

    # urlset (or anything else — treat as urlset)
    urls = []
    for url_elem in root:
        local_child = url_elem.tag.split("}")[-1] if "}" in url_elem.tag else url_elem.tag
        if local_child == "url":
            loc = _loc(url_elem)
            if loc:
                urls.append(loc)
    return urls, []


def fetch(site_url: str, config: dict | None = None) -> list:
    """
    site_url : base URL of the old site (e.g. 'https://example.co.il')
    config   : redirect_engine config dict used for product detection

    Returns [{url: str, title: str}] with products filtered out.
    """
    cfg = config or DEFAULT_CONFIG
    base = site_url.rstrip("/")

    visited: set = set()
    queue = [base + p for p in CANDIDATE_PATHS]
    all_page_urls: list = []
    found_any = False

    while queue:
        sm_url = queue.pop(0)
        if sm_url in visited:
            continue
        visited.add(sm_url)

        text = _fetch(sm_url)
        if text is None:
            continue

        found_any = True
        page_urls, child_urls = _parse(text)
        all_page_urls.extend(page_urls)
        for c in child_urls:
            if c not in visited:
                queue.append(c)

    if not found_any:
        return []

    seen: set = set()
    result = []
    for u in all_page_urls:
        if u in seen:
            continue
        seen.add(u)
        if not is_product(u, cfg):
            result.append({"url": u, "title": ""})

    return result
