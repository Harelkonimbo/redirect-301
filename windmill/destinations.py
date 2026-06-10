"""
destinations.py — load the Konimbo destination list from an uploaded Excel or CSV.

Column detection is by content (not by column name or position):
  URL column:   the column where most cells contain 'konimbo.co.il'
  Title column: the first other column with non-empty text values

Returns:
    load_destinations(data: bytes | str) -> (destinations: list[dict], aliases: dict)
    destinations : [{url: str, title: str}]
    aliases      : {}  — aliases come from per-site config, not this file
"""
import base64
import csv
import io

import openpyxl


def _is_konimbo_url(val):
    return isinstance(val, str) and "konimbo.co.il" in val.lower()


def _detect_columns(rows):
    """Return (url_col_idx, title_col_idx) from a list of string-row lists."""
    if not rows:
        raise ValueError("קובץ היעדים ריק")

    ncols = max((len(r) for r in rows), default=0)
    if ncols == 0:
        raise ValueError("קובץ היעדים ריק")

    url_scores = [0] * ncols
    for row in rows:
        for ci, cell in enumerate(row):
            if _is_konimbo_url(cell):
                url_scores[ci] += 1

    url_col = max(range(ncols), key=lambda i: url_scores[i])
    if url_scores[url_col] == 0:
        raise ValueError(
            "לא נמצאה עמודת URL של קונימבו (konimbo.co.il) בקובץ — "
            "ודא שהקובץ כולל את כתובות היעד של קונימבו"
        )

    # Title column: first non-URL column that has non-empty, non-URL strings
    title_col = None
    for ci in range(ncols):
        if ci == url_col:
            continue
        for row in rows:
            cell = row[ci] if ci < len(row) else ""
            if isinstance(cell, str) and cell.strip() and not _is_konimbo_url(cell):
                title_col = ci
                break
        if title_col is not None:
            break

    return url_col, title_col


def _read_xlsx(data: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(c).strip() if c is not None else "" for c in row])
    wb.close()
    return rows


def _read_csv(data: bytes):
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [[cell.strip() for cell in row] for row in reader]


def load_destinations(data):
    """
    data: bytes or base64-encoded string (with or without data: prefix) of an xlsx/csv.

    Returns (destinations, aliases):
        destinations : [{url: str, title: str}]
        aliases      : {}
    """
    if isinstance(data, str):
        if "," in data[:60]:          # strip "data:<mime>;base64," prefix
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)

    # xlsx magic: PK zip header
    if data[:2] == b"PK":
        rows = _read_xlsx(data)
    else:
        try:
            rows = _read_csv(data)
        except Exception:
            rows = _read_xlsx(data)

    url_col, title_col = _detect_columns(rows)

    destinations = []
    for row in rows:
        url = row[url_col] if url_col < len(row) else ""
        title = (row[title_col] if (title_col is not None and title_col < len(row)) else "")

        if not _is_konimbo_url(url):
            continue

        destinations.append({"url": url, "title": title})

    return destinations, {}
