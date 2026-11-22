"""
source.py — load the OLD-site source rows from the n8n-exported Excel.

This is the "front half handed off from n8n" path: instead of calling GA4 here,
we consume the multi-sheet workbook the existing n8n tool already produces
(sheets `משיכת לינקים מהאתר` / `ANALYTICS` / `מאוחד`). Column detection is by
content, not by header name or position:

  URL column   : the column whose cells look like http(s) URLs
  Title column : the first other column with non-empty, non-URL text

Sheet selection: prefer the merged `מאוחד` sheet; if it's missing or empty,
fall back to merging every sheet that carries URLs (ANALYTICS + sitemap).

Returns:
    load_source(data: bytes | str) -> list[dict]   # [{title, url}], deduped by url
"""
import base64
import csv
import io

import openpyxl

MERGED_SHEET = "מאוחד"


def _looks_like_url(val):
    if not isinstance(val, str):
        return False
    v = val.strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _detect_columns(rows):
    """Return (url_col_idx, title_col_idx|None) from a list of string-row lists."""
    ncols = max((len(r) for r in rows), default=0)
    if ncols == 0:
        return None, None

    url_scores = [0] * ncols
    for row in rows:
        for ci, cell in enumerate(row):
            if _looks_like_url(cell):
                url_scores[ci] += 1

    url_col = max(range(ncols), key=lambda i: url_scores[i])
    if url_scores[url_col] == 0:
        return None, None

    title_col = None
    for ci in range(ncols):
        if ci == url_col:
            continue
        for row in rows:
            cell = row[ci] if ci < len(row) else ""
            if isinstance(cell, str) and cell.strip() and not _looks_like_url(cell):
                title_col = ci
                break
        if title_col is not None:
            break

    return url_col, title_col


def _rows_to_records(rows):
    """Map detected (url, title) columns of a sheet to [{title, url}]."""
    url_col, title_col = _detect_columns(rows)
    if url_col is None:
        return []
    records = []
    for row in rows:
        url = row[url_col] if url_col < len(row) else ""
        if not _looks_like_url(url):
            continue  # skips header row and blanks
        title = (row[title_col] if (title_col is not None and title_col < len(row)) else "")
        records.append({"title": title, "url": url.strip()})
    return records


def _sheet_rows(ws):
    out = []
    for row in ws.iter_rows(values_only=True):
        out.append([str(c).strip() if c is not None else "" for c in row])
    return out


def _read_xlsx(data: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        # Prefer the merged sheet; fall back to merging all URL-bearing sheets.
        if MERGED_SHEET in wb.sheetnames:
            recs = _rows_to_records(_sheet_rows(wb[MERGED_SHEET]))
            if recs:
                return recs
        merged = []
        for name in wb.sheetnames:
            merged.extend(_rows_to_records(_sheet_rows(wb[name])))
        return merged
    finally:
        wb.close()


def _read_csv(data: bytes):
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [[cell.strip() for cell in row] for row in reader]
    return _rows_to_records(rows)


def load_source(data):
    """
    data: bytes or base64-encoded string (with or without data: prefix) of an
    xlsx (the n8n export) or csv.

    Returns [{title, url}] deduped by url, first occurrence wins (so the
    title-bearing `מאוחד`/ANALYTICS row beats an empty-title sitemap row).
    """
    if isinstance(data, str):
        if "," in data[:60]:          # strip "data:<mime>;base64," prefix
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)

    if data[:2] == b"PK":             # xlsx magic (PK zip header)
        records = _read_xlsx(data)
    else:
        try:
            records = _read_csv(data)
        except Exception:
            records = _read_xlsx(data)

    deduped, seen = [], set()
    for rec in records:
        if rec["url"] in seen:
            continue
        seen.add(rec["url"])
        deduped.append(rec)
    return deduped
