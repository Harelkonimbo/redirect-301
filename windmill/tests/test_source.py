"""
Tests for source.load_source — reading OLD-site rows from the n8n export Excel.

Builds an in-memory workbook shaped exactly like the n8n tool's output
(sheets `משיכת לינקים מהאתר` / `ANALYTICS` / `מאוחד`) and asserts that
load_source recovers {title, url} records, prefers the merged sheet, dedupes,
and skips the header row.
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl
from source import load_source

BASE = "https://espressobar.com"


def _n8n_workbook(merged_rows, analytics_rows=None, sitemap_rows=None):
    """merged_rows: list of (title, url). Returns xlsx bytes."""
    wb = openpyxl.Workbook()
    sm = wb.active
    sm.title = "משיכת לינקים מהאתר"
    sm.append(["כותרת", "URL"])
    for t, u in (sitemap_rows or []):
        sm.append([t, u])

    an = wb.create_sheet("ANALYTICS")
    an.append(["כותרת", "URL", "Pageviews"])
    for t, u, pv in (analytics_rows or []):
        an.append([t, u, pv])

    mg = wb.create_sheet("מאוחד")
    mg.append(["כותרת", "URL"])
    for t, u in merged_rows:
        mg.append([t, u])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reads_merged_sheet_with_titles():
    data = _n8n_workbook([
        ("פולי קפה - EspressoBar", f"{BASE}/product-category/coffee-beans"),
        ("בלוג - EspressoBar", f"{BASE}/blog"),
    ])
    rows = load_source(data)
    assert rows == [
        {"title": "פולי קפה - EspressoBar", "url": f"{BASE}/product-category/coffee-beans"},
        {"title": "בלוג - EspressoBar", "url": f"{BASE}/blog"},
    ]


def test_header_row_is_skipped():
    data = _n8n_workbook([("דף הבית", f"{BASE}/")])
    rows = load_source(data)
    # the literal "URL" header must never become a record
    assert all(r["url"].startswith("http") for r in rows)
    assert rows == [{"title": "דף הבית", "url": f"{BASE}/"}]


def test_dedupes_by_url_first_wins():
    data = _n8n_workbook([
        ("כותרת אמיתית", f"{BASE}/page"),
        ("", f"{BASE}/page"),
    ])
    rows = load_source(data)
    assert rows == [{"title": "כותרת אמיתית", "url": f"{BASE}/page"}]


def test_falls_back_to_other_sheets_when_merged_empty():
    data = _n8n_workbook(
        merged_rows=[],
        analytics_rows=[("מכונות קפה", f"{BASE}/machines", 42)],
        sitemap_rows=[("", f"{BASE}/about")],
    )
    urls = {r["url"] for r in load_source(data)}
    assert f"{BASE}/machines" in urls
    assert f"{BASE}/about" in urls


def test_base64_input_accepted():
    import base64
    data = _n8n_workbook([("דף", f"{BASE}/x")])
    b64 = base64.b64encode(data).decode()
    assert load_source(b64) == [{"title": "דף", "url": f"{BASE}/x"}]


def test_csv_input():
    csv_text = "כותרת,URL\nפולי קפה,{0}/coffee\n".format(BASE).encode("utf-8-sig")
    rows = load_source(csv_text)
    assert rows == [{"title": "פולי קפה", "url": f"{BASE}/coffee"}]
