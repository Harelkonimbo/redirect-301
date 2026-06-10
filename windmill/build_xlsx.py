"""
build_xlsx.py — write the 3-sheet 301-redirect Excel deliverable.

Sheets
  מאוחד  — 3-column deliverable: כותרת / לינק מאתר קודם / לינק חדש
  דוח    — same rows + match-type column, colour-coded for review
  סיכום  — stats summary

Returns bytes (xlsx).
"""
import io

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="4F46E5")
_HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
_CELL_FONT = Font(name="Arial", size=10)
_RTL = Alignment(horizontal="right", vertical="center", wrap_text=False)
_CENTER = Alignment(horizontal="center", vertical="center")

# match-type → row background colour for the דוח sheet
_MATCH_FILL = {
    "title-match":       PatternFill("solid", fgColor="D1FAE5"),   # green
    "lang-rule":         PatternFill("solid", fgColor="DBEAFE"),   # blue
    "homepage-fallback": PatternFill("solid", fgColor="FEF9C3"),   # yellow
}


def _rtl(ws):
    ws.sheet_view.rightToLeft = True


def _write_header(ws, columns: list[str]):
    _rtl(ws)
    for ci, col in enumerate(columns, 1):
        cell = ws.cell(1, ci, col)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _RTL
    ws.freeze_panes = ws.cell(2, 1)


def _col_widths(ws, widths: list[float]):
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w


def build(rows: list, stats: dict) -> bytes:
    """
    rows  : [{כותרת, לינק מאתר קודם, לינק חדש, _match}]  — output of redirect_engine.run
    stats : {in, products, dupes, lang, title_match, homepage, out}

    Returns xlsx bytes.
    """
    wb = openpyxl.Workbook()

    # ── Sheet 1: מאוחד ──────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "מאוחד"
    MAIN_COLS = ["כותרת", "לינק מאתר קודם", "לינק חדש"]
    _write_header(ws1, MAIN_COLS)
    for ri, row in enumerate(rows, 2):
        for ci, key in enumerate(MAIN_COLS, 1):
            c = ws1.cell(ri, ci, row.get(key, ""))
            c.font = _CELL_FONT
            c.alignment = _RTL
    _col_widths(ws1, [30, 62, 62])

    # ── Sheet 2: דוח ────────────────────────────────────────────────────────
    ws2 = wb.create_sheet("דוח")
    REPORT_COLS = ["כותרת", "לינק מאתר קודם", "לינק חדש", "סוג התאמה"]
    _write_header(ws2, REPORT_COLS)
    for ri, row in enumerate(rows, 2):
        match_type = row.get("_match", "")
        fill = _MATCH_FILL.get(match_type)
        for ci, key in enumerate(["כותרת", "לינק מאתר קודם", "לינק חדש"], 1):
            c = ws2.cell(ri, ci, row.get(key, ""))
            c.font = _CELL_FONT
            c.alignment = _RTL
            if fill:
                c.fill = fill
        c4 = ws2.cell(ri, 4, match_type)
        c4.font = _CELL_FONT
        c4.alignment = _RTL
        if fill:
            c4.fill = fill
    _col_widths(ws2, [30, 62, 62, 22])

    # ── Sheet 3: סיכום ──────────────────────────────────────────────────────
    ws3 = wb.create_sheet("סיכום")
    _rtl(ws3)
    for ci, header in enumerate(["פריט", "כמות"], 1):
        c = ws3.cell(1, ci, header)
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.alignment = _RTL
    ws3.freeze_panes = ws3.cell(2, 1)

    summary = [
        ("שורות קלט",              stats.get("in", 0)),
        ("מוצרים שהוסרו",           stats.get("products", 0)),
        ('כפילויות שקוּבּצו',        stats.get("dupes", 0)),
        ('נתב ע"פ שפה',             stats.get("lang", 0)),
        ("התאמה לפי כותרת",         stats.get("title_match", 0)),
        ("ברירת מחדל (דף הבית)",    stats.get("homepage", 0)),
        ("שורות פלט",               stats.get("out", 0)),
    ]
    for ri, (label, val) in enumerate(summary, 2):
        c1 = ws3.cell(ri, 1, label)
        c1.font = _CELL_FONT
        c1.alignment = _RTL
        c2 = ws3.cell(ri, 2, val)
        c2.font = _CELL_FONT
        c2.alignment = _CENTER
    _col_widths(ws3, [32, 12])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
