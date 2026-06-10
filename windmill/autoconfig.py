"""
Auto-detect a per-site config from the source URLs (+ titles), so most sites
need zero manual setup. Everything inferred here is a DEFAULT — any explicit
config passed by the caller overrides it.

detect_config(source_rows, overrides=None) -> config dict for redirect_engine.run
"""
import re
from collections import Counter
from urllib.parse import urlsplit

# platform signature -> product URL segment patterns
PLATFORM_SIGNATURES = {
    "woocommerce": {
        "markers": ["/product/", "/product-category/", "wp-content", "wp-json", "?post_type=product"],
        "product_segments": [["product"]],
        "category_keep": ["product-category"],
    },
    "shopify": {
        "markers": ["/products/", "/collections/"],
        "product_segments": [["products"]],
        "category_keep": ["collections"],
    },
    "magento": {
        "markers": ["/catalog/product/", "catalog/category"],
        "product_segments": [["catalog", "product"]],
        "category_keep": ["catalog/category"],
    },
    "prestashop": {
        "markers": ["id_product=", "controller=product"],
        "product_segments": [["product"]],
        "category_keep": [],
    },
}

# common language path prefixes to look for
LANG_PREFIXES = ["en", "eng", "he", "ar", "ru", "fr", "es", "de", "it"]


def _paths(rows):
    out = []
    for r in rows:
        try:
            out.append(urlsplit(str(r["url"])).path.lower())
        except Exception:
            pass
    return out


def _detect_platform(rows):
    blob = " ".join(str(r.get("url", "")).lower() for r in rows)
    scores = {p: sum(blob.count(m) for m in sig["markers"]) for p, sig in PLATFORM_SIGNATURES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def _detect_languages(paths):
    first_segs = Counter()
    for p in paths:
        segs = [s for s in p.split("/") if s]
        if segs and segs[0] in LANG_PREFIXES:
            first_segs[segs[0]] += 1
    # a language prefix that appears on several URLs is a real language section
    return [f"/{seg}" for seg, n in first_segs.items() if n >= 2]


def _detect_brand(rows):
    # brand = the token most repeated as a trailing " - X" / " | X" suffix in titles
    seps = re.compile(r"\s[-|–—·]\s")
    tail = Counter()
    for r in rows:
        t = str(r.get("title") or "").strip()
        parts = seps.split(t)
        if len(parts) >= 2 and parts[-1]:
            tail[parts[-1].strip()] += 1
    if tail:
        brand, n = tail.most_common(1)[0]
        if n >= 3:               # only trust a suffix that recurs
            return brand
    return None


def detect_config(source_rows, overrides=None, default_lang_action="homepage"):
    paths = _paths(source_rows)
    cfg = {}
    notes = {}

    platform = _detect_platform(source_rows)
    if platform:
        sig = PLATFORM_SIGNATURES[platform]
        cfg["product_segments"] = sig["product_segments"]
        cfg["category_keep_substrings"] = sig["category_keep"]
        notes["platform"] = platform

    langs = _detect_languages(paths)
    if langs:
        cfg["language_rules"] = [{"prefix": p, "action": default_lang_action} for p in langs]
        notes["languages"] = langs

    brand = _detect_brand(source_rows)
    if brand:
        cfg["brand"] = brand
        notes["brand"] = brand

    if overrides:
        cfg.update(overrides)        # explicit config always wins
    cfg["_autodetect"] = notes
    return cfg
