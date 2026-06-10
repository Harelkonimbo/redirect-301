# requirements:
# openpyxl>=3.1.0
# requests>=2.31.0
# google-auth>=2.23.0

"""
Konimbo 301 Redirect Builder — single-file Windmill script.

All helper modules are inlined here so no cross-script imports are needed.
The modular version (separate .py files) is used for local dev & testing.
"""

import base64
import csv
import io
import re
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import unquote, urlsplit

import openpyxl
import requests
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


# ═══════════════════════════════════════════════════════════════════════════════
# redirect_engine
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "product_segments": [
        ["product"], ["products"],
        ["catalog", "product"],
    ],
    "product_query_flags": ["post_type=product"],
    "category_keep_substrings": ["product-category", "product_category"],
    "language_rules": [{"prefix": "/en", "action": "homepage"}],
    "title_separators": ["-", "|", "–", "—", "·"],
    "brand": None,
    "aliases": {},
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
        for sep in cfg["title_separators"]:
            suf = f" {sep} {cfg['brand']}"
            if t.lower().endswith(suf.lower()):
                t = t[: -len(suf)]
                break
    else:
        seps = "".join(re.escape(s) for s in cfg["title_separators"])
        t = re.sub(rf"\s*[{seps}]\s*[^{seps}]+$", "", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return cfg["aliases"].get(t, t)


def is_product(url, cfg):
    cfg = _cfg(cfg)
    p = _path(url)
    segs = [s for s in p.split("/") if s]
    if any(k in p for k in cfg["category_keep_substrings"]):
        return False
    for pat in cfg["product_segments"]:
        if pat in (["product"], ["products"]):
            if len(segs) >= 2 and segs[0] == pat[0]:
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


def engine_run(source_rows, destinations, config=None):
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
            dest, mt = homepage, "lang-rule"
            stats["lang"] += 1
        else:
            ct = clean_title(title, cfg)
            if ct in lookup:
                dest, mt = lookup[ct], "title-match"
                stats["title_match"] += 1
            else:
                dest, mt = homepage, "homepage-fallback"
                stats["homepage"] += 1

        label = clean_title(title, cfg) or slug_title(dest)
        out.append({"כותרת": label, "לינק מאתר קודם": url,
                    "לינק חדש": dest, "_match": mt})
    stats["out"] = len(out)
    return out, stats


# ═══════════════════════════════════════════════════════════════════════════════
# autoconfig
# ═══════════════════════════════════════════════════════════════════════════════

_PLATFORM_SIGNATURES = {
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
_LANG_PREFIXES = ["en", "eng", "he", "ar", "ru", "fr", "es", "de", "it"]


def _ac_detect_platform(rows):
    blob = " ".join(str(r.get("url", "")).lower() for r in rows)
    scores = {p: sum(blob.count(m) for m in sig["markers"])
              for p, sig in _PLATFORM_SIGNATURES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def _ac_detect_languages(paths):
    first_segs = Counter()
    for p in paths:
        segs = [s for s in p.split("/") if s]
        if segs and segs[0] in _LANG_PREFIXES:
            first_segs[segs[0]] += 1
    return [f"/{seg}" for seg, n in first_segs.items() if n >= 2]


def _ac_detect_brand(rows):
    seps = re.compile(r"\s[-|–—·]\s")
    tail = Counter()
    for r in rows:
        t = str(r.get("title") or "").strip()
        parts = seps.split(t)
        if len(parts) >= 2 and parts[-1]:
            tail[parts[-1].strip()] += 1
    if tail:
        brand, n = tail.most_common(1)[0]
        if n >= 3:
            return brand
    return None


def detect_config(source_rows, overrides=None, default_lang_action="homepage"):
    paths = []
    for r in source_rows:
        try:
            paths.append(urlsplit(str(r["url"])).path.lower())
        except Exception:
            pass
    cfg, notes = {}, {}

    platform = _ac_detect_platform(source_rows)
    if platform:
        sig = _PLATFORM_SIGNATURES[platform]
        cfg["product_segments"] = sig["product_segments"]
        cfg["category_keep_substrings"] = sig["category_keep"]
        notes["platform"] = platform

    langs = _ac_detect_languages(paths)
    if langs:
        cfg["language_rules"] = [{"prefix": p, "action": default_lang_action} for p in langs]
        notes["languages"] = langs

    brand = _ac_detect_brand(source_rows)
    if brand:
        cfg["brand"] = brand
        notes["brand"] = brand

    if overrides:
        cfg.update(overrides)
    cfg["_autodetect"] = notes
    return cfg


# ═══════════════════════════════════════════════════════════════════════════════
# destinations
# ═══════════════════════════════════════════════════════════════════════════════

def _is_konimbo(val):
    return isinstance(val, str) and "konimbo.co.il" in val.lower()


def _detect_dest_cols(rows):
    if not rows:
        raise ValueError("קובץ היעדים ריק")
    ncols = max(len(r) for r in rows)
    scores = [0] * ncols
    for row in rows:
        for ci, cell in enumerate(row):
            if _is_konimbo(cell):
                scores[ci] += 1
    url_col = max(range(ncols), key=lambda i: scores[i])
    if scores[url_col] == 0:
        raise ValueError("לא נמצאה עמודת URL של קונימבו — ודא שהקובץ כולל כתובות konimbo.co.il")
    title_col = None
    for ci in range(ncols):
        if ci == url_col:
            continue
        for row in rows:
            cell = row[ci] if ci < len(row) else ""
            if isinstance(cell, str) and cell.strip() and not _is_konimbo(cell):
                title_col = ci
                break
        if title_col is not None:
            break
    return url_col, title_col


def load_destinations(data):
    if isinstance(data, str):
        if "," in data[:60]:
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)

    if data[:2] == b"PK":
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = [[str(c).strip() if c is not None else "" for c in row]
                for row in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = data.decode("utf-8-sig", errors="replace")
        rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]

    url_col, title_col = _detect_dest_cols(rows)
    destinations = []
    for row in rows:
        url = row[url_col] if url_col < len(row) else ""
        title = (row[title_col] if (title_col is not None and title_col < len(row)) else "")
        if not _is_konimbo(url):
            continue
        destinations.append({"url": url, "title": title})
    return destinations, {}


# ═══════════════════════════════════════════════════════════════════════════════
# ga4
# ═══════════════════════════════════════════════════════════════════════════════

_GA4_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"
_GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _ga4_token(credentials: dict) -> str:
    for key in ("token", "access_token"):
        if credentials.get(key):
            return credentials[key]
    if credentials.get("type") == "service_account":
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                credentials, scopes=_GA4_SCOPES)
            creds.refresh(Request())
            return creds.token
        except ImportError as exc:
            raise ImportError("google-auth is required for service-account creds") from exc
    raise ValueError("credentials must have 'token'/'access_token' or be a service-account JSON")


def ga4_run_report(property_id: str, site_url: str, credentials: dict) -> list:
    token = _ga4_token(credentials)
    base = site_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "dateRanges": [{"startDate": "90daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "metrics": [{"name": "screenPageViews"}],
        "metricFilter": {"filter": {
            "fieldName": "screenPageViews",
            "numericFilter": {"operation": "GREATER_THAN_OR_EQUAL",
                              "value": {"int64Value": "5"}},
        }},
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 10000,
    }
    resp = requests.post(_GA4_URL.format(pid=property_id), headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    rows, seen = [], set()
    for row in resp.json().get("rows", []):
        path = row["dimensionValues"][0]["value"]
        title = row["dimensionValues"][1]["value"]
        views = int(row["metricValues"][0]["value"])
        full_url = base + path
        if full_url not in seen:
            seen.add(full_url)
            rows.append({"url": full_url, "title": title, "pageviews": views})
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# sitemap
# ═══════════════════════════════════════════════════════════════════════════════

_SM_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/wp-sitemap.xml"]
_SM_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_SM_UA = {"User-Agent": "Mozilla/5.0 (compatible; Konimbo-301-bot/1.0)"}


def _sm_loc(elem):
    for tag in (f"{{{_SM_NS}}}loc", "loc"):
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return None


def _sm_parse(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], []
    local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local == "sitemapindex":
        return [], [_sm_loc(c) for c in root if _sm_loc(c)]
    urls = []
    for child in root:
        lc = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if lc == "url":
            loc = _sm_loc(child)
            if loc:
                urls.append(loc)
    return urls, []


def sitemap_fetch(site_url: str, config=None) -> list:
    cfg = config or DEFAULT_CONFIG
    base = site_url.rstrip("/")
    visited, queue, all_urls, found = set(), [base + p for p in _SM_PATHS], [], False
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            resp = requests.get(url, headers=_SM_UA, timeout=10, allow_redirects=True)
            if resp.status_code != 200 or not resp.content:
                continue
        except Exception:
            continue
        found = True
        pages, children = _sm_parse(resp.text)
        all_urls.extend(pages)
        queue.extend(c for c in children if c and c not in visited)
    if not found:
        return []
    seen: set = set()
    result = []
    for u in all_urls:
        if u not in seen:
            seen.add(u)
            if not is_product(u, cfg):
                result.append({"url": u, "title": ""})
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# build_xlsx
# ═══════════════════════════════════════════════════════════════════════════════

_HF = PatternFill("solid", fgColor="4F46E5")
_HN = Font(name="Arial", bold=True, color="FFFFFF", size=11)
_CF = Font(name="Arial", size=10)
_RA = Alignment(horizontal="right", vertical="center")
_CA = Alignment(horizontal="center", vertical="center")
_MF = {
    "title-match":       PatternFill("solid", fgColor="D1FAE5"),
    "lang-rule":         PatternFill("solid", fgColor="DBEAFE"),
    "homepage-fallback": PatternFill("solid", fgColor="FEF9C3"),
}


def _hdr(ws, cols):
    ws.sheet_view.rightToLeft = True
    for ci, col in enumerate(cols, 1):
        c = ws.cell(1, ci, col)
        c.font = _HN; c.fill = _HF; c.alignment = _RA
    ws.freeze_panes = ws.cell(2, 1)


def _wid(ws, widths):
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w


def build_xlsx(rows: list, stats: dict) -> bytes:
    wb = openpyxl.Workbook()
    MAIN = ["כותרת", "לינק מאתר קודם", "לינק חדש"]

    ws1 = wb.active
    ws1.title = "מאוחד"
    _hdr(ws1, MAIN)
    for ri, row in enumerate(rows, 2):
        for ci, key in enumerate(MAIN, 1):
            c = ws1.cell(ri, ci, row.get(key, ""))
            c.font = _CF; c.alignment = _RA
    _wid(ws1, [30, 62, 62])

    ws2 = wb.create_sheet("דוח")
    _hdr(ws2, MAIN + ["סוג התאמה"])
    for ri, row in enumerate(rows, 2):
        mt = row.get("_match", "")
        fill = _MF.get(mt)
        for ci, key in enumerate(MAIN, 1):
            c = ws2.cell(ri, ci, row.get(key, ""))
            c.font = _CF; c.alignment = _RA
            if fill:
                c.fill = fill
        c4 = ws2.cell(ri, 4, mt)
        c4.font = _CF; c4.alignment = _RA
        if fill:
            c4.fill = fill
    _wid(ws2, [30, 62, 62, 22])

    ws3 = wb.create_sheet("סיכום")
    ws3.sheet_view.rightToLeft = True
    for ci, h in enumerate(["פריט", "כמות"], 1):
        c = ws3.cell(1, ci, h); c.font = _HN; c.fill = _HF; c.alignment = _RA
    ws3.freeze_panes = ws3.cell(2, 1)
    for ri, (label, val) in enumerate([
        ("שורות קלט",              stats.get("in", 0)),
        ("מוצרים שהוסרו",           stats.get("products", 0)),
        ('כפילויות שקוּבּצו',        stats.get("dupes", 0)),
        ('נתב ע"פ שפה',             stats.get("lang", 0)),
        ("התאמה לפי כותרת",         stats.get("title_match", 0)),
        ("ברירת מחדל (דף הבית)",    stats.get("homepage", 0)),
        ("שורות פלט",               stats.get("out", 0)),
    ], 2):
        c1 = ws3.cell(ri, 1, label); c1.font = _CF; c1.alignment = _RA
        c2 = ws3.cell(ri, 2, val); c2.font = _CF; c2.alignment = _CA
    _wid(ws3, [32, 12])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# main — Windmill entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main(
    site_url: str,
    ga4_property_id: str,
    destinations_b64: str,
    destinations_filename: str = "destinations.xlsx",
    google_credentials: dict = None,
    config_overrides: dict = None,
) -> dict:
    """
    Build a 301-redirect Excel for a Konimbo migration.

    site_url          : Base URL of the OLD site  (e.g. https://espressobar.com)
    ga4_property_id   : GA4 numeric property ID   (9 digits, found in GA4 Admin)
    destinations_b64  : Base64-encoded .xlsx with Konimbo destination URLs + titles
    destinations_filename : Original filename (xlsx or csv)
    google_credentials: Windmill Google resource — OAuth2 token dict or service-account JSON
    config_overrides  : Optional per-site overrides (product_segments, aliases, language_rules…)
    """
    # 1. Destination list
    destinations, _ = load_destinations(destinations_b64)
    if not destinations:
        raise ValueError("קובץ היעדים ריק — לא זוהו עמודות konimbo.co.il")

    # 2. Source rows (GA4 primary, sitemap supplement)
    source_rows: list = []
    errors: list = []

    if google_credentials:
        try:
            source_rows.extend(ga4_run_report(ga4_property_id, site_url, google_credentials))
        except Exception as exc:
            errors.append(f"GA4: {exc}")

    try:
        sitemap_rows = sitemap_fetch(site_url)
        existing = {r["url"] for r in source_rows}
        source_rows.extend(sr for sr in sitemap_rows if sr["url"] not in existing)
    except Exception:
        pass  # sitemap is best-effort

    if not source_rows:
        hint = f" ({'; '.join(errors)})" if errors else ""
        raise ValueError(f"לא נמצאו שורות מקור — GA4 וסיטמאפ שניהם ריקים{hint}")

    # 3. Auto-detect config, apply overrides
    config = detect_config(source_rows, overrides=config_overrides)

    # 4. Run matching engine
    rows, stats = engine_run(source_rows, destinations, config)

    # 5. Build output Excel
    xlsx_bytes = build_xlsx(rows, stats)

    # 6. Return base64 + metadata
    slug = re.sub(r"https?://", "", site_url).rstrip("/")
    slug = re.sub(r"[^a-zA-Z0-9\-._]", "-", slug).strip("-")

    return {
        "file_b64": base64.b64encode(xlsx_bytes).decode(),
        "filename": f"301-redirects-{slug}.xlsx",
        "stats": stats,
        "autodetect": config.get("_autodetect", {}),
    }
