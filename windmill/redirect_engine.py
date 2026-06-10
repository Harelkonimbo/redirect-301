"""
Konimbo 301 back-half engine — site-agnostic, config-driven.

Generic rules (from the Redirect-301 skill, apply to every site):
  - identify columns by content (*.konimbo.co.il = destination)
  - homepage detected from the data
  - http/https + trailing-slash + case normalization
  - one source -> one destination; wrong-but-specific is worse than homepage

Per-site behaviour lives in CONFIG (defaults below, override per run). Nothing
here is hard-coded to any single client.

Inputs:
  source_rows  : [{title, url}]            (the GA4/sitemap `מאוחד` rows)
  destinations : [{url, title?}]           (the manual Konimbo list)
  config       : dict (optional)           (see DEFAULT_CONFIG)
"""
import re
from urllib.parse import urlsplit, unquote

DEFAULT_CONFIG = {
    # URL path patterns that mark a PRODUCT page (removed from 301 files).
    # Segment-aware: matched against the lowercased path. Add per platform.
    "product_segments": [
        ["product"], ["products"],                 # WooCommerce / generic
        ["catalog", "product"],                    # Magento-style
    ],
    "product_query_flags": ["post_type=product"],
    # Paths that must NEVER be treated as products even if they contain "product".
    "category_keep_substrings": ["product-category", "product_category"],

    # Language routing. Each rule: {"prefix": "/en", "action": "homepage"|"match"}.
    # "homepage" -> force homepage; "match" -> treat normally (real translated store).
    "language_rules": [{"prefix": "/en", "action": "homepage"}],

    # Title cleaning before the VLOOKUP.
    "title_separators": ["-", "|", "–", "—", "·"],   # strip " <sep> <brand>"
    "brand": None,            # if set, only strip this exact trailing brand; else strip any trailing segment after a separator
    "aliases": {},            # {source_title_lower: dest_title_lower}

    # Variant handling. True = keep ?query= variants as separate rows (client pref);
    # False = collapse them (skill default for pure 301).
    "keep_query_variants": True,
}


def _cfg(config):
    c = dict(DEFAULT_CONFIG)
    if config:
        c.update(config)
    return c


def _path(url):
    try:
        return urlsplit(str(url)).path.lower()
    except Exception:
        return ""


def clean_title(t, cfg):
    cfg = _cfg(cfg)
    if not t:
        return ""
    t = unquote(str(t)).strip().strip('"\'')
    if cfg["brand"]:
        # strip a specific trailing brand after any configured separator
        for sep in cfg["title_separators"]:
            suf = f" {sep} {cfg['brand']}"
            if t.lower().endswith(suf.lower()):
                t = t[: -len(suf)]
                break
    else:
        seps = "".join(re.escape(s) for s in cfg["title_separators"])
        t = re.sub(rf"\s*[{seps}]\s*[^{seps}]+$", "", t)   # drop trailing " <sep> <x>"
    t = re.sub(r"\s+", " ", t).strip().lower()
    return cfg["aliases"].get(t, t)


def is_product(url, cfg):
    cfg = _cfg(cfg)
    p = _path(url)
    segs = [s for s in p.split("/") if s]
    if any(k in p for k in cfg["category_keep_substrings"]):
        return False
    for pat in cfg["product_segments"]:
        if pat == ["product"] or pat == ["products"]:
            if len(segs) >= 2 and segs[0] in (pat[0],):
                return True
            if len(segs) >= 2 and segs[-2] == pat[0]:
                return True
        elif all(s in segs for s in pat):
            return True
    return any(f in str(url).lower() for f in cfg["product_query_flags"])


def language_action(url, cfg):
    cfg = _cfg(cfg)
    p = _path(url).rstrip("/")
    for rule in cfg["language_rules"]:
        pre = rule["prefix"].rstrip("/")
        if p == pre or p.startswith(pre + "/"):
            return rule["action"]
    return None


def dedup_key(url, keep_query=True):
    s = urlsplit(str(url))
    q = ("?" + s.query) if (keep_query and s.query) else ""
    return (s.netloc + s.path.rstrip("/") + q).lower()


def _raw_path(url):
    try:
        return urlsplit(str(url)).path
    except Exception:
        return ""


def slug_title(url):
    seg = unquote(_raw_path(url)).rstrip("/").split("/")[-1]
    seg = re.sub(r"^\d+-", "", seg)
    return seg.replace("-", " ").strip().lower()


def detect_homepage(urls):
    for u in urls:
        s = urlsplit(str(u))
        if "konimbo.co.il" in s.netloc:
            return f"https://{s.netloc}/"
    return ""


def build_lookup(destinations, cfg):
    table = {}
    for d in destinations:
        url = d["url"]
        title = clean_title(d.get("title") or "", cfg) or slug_title(url)
        if title and title not in table:
            table[title] = url
    return table


def run(source_rows, destinations, config=None):
    cfg = _cfg(config)
    homepage = detect_homepage([d["url"] for d in destinations]) or \
               detect_homepage([r["url"] for r in source_rows])
    lookup = build_lookup(destinations, cfg)

    out, seen = [], set()
    stats = {"in": len(source_rows), "products": 0, "lang": 0,
             "title_match": 0, "homepage": 0, "dupes": 0}

    for r in source_rows:
        url, title = r["url"], r.get("title", "")
        if is_product(url, cfg):
            stats["products"] += 1
            continue

        k = dedup_key(url, cfg["keep_query_variants"])
        if k in seen:
            stats["dupes"] += 1
            continue
        seen.add(k)

        act = language_action(url, cfg)
        if act == "homepage":
            dest, mt = homepage, "lang-rule"; stats["lang"] += 1
        else:
            ct = clean_title(title, cfg)
            if ct in lookup:
                dest, mt = lookup[ct], "title-match"; stats["title_match"] += 1
            else:
                dest, mt = homepage, "homepage-fallback"; stats["homepage"] += 1

        label = clean_title(title, cfg) or slug_title(dest)
        out.append({"כותרת": label, "לינק מאתר קודם": url,
                    "לינק חדש": dest, "_match": mt})
    stats["out"] = len(out)
    return out, stats
