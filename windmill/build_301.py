"""
build_301.py — Windmill entry point for the Konimbo 301 redirect builder.

Front-end ↔ Windmill contract
  Request  : {site_url, ga4_property_id, destinations_b64, destinations_filename}
  Response : {file_b64: <base64 xlsx>, filename: "301-redirects-<site>.xlsx"}

google_credentials : Windmill resource (OAuth2 token dict or service-account JSON).
                     Optional — when absent, only sitemap rows are used (useful for testing).
config_overrides   : optional per-site config tweaks that override auto-detection.
"""
import base64
import re
import sys
import os

# When running locally (pytest / CLI), resolve sibling modules without install
sys.path.insert(0, os.path.dirname(__file__))


def main(
    site_url: str,
    ga4_property_id: str,
    destinations_b64: str,
    destinations_filename: str = "destinations.xlsx",
    google_credentials: dict = None,
    config_overrides: dict = None,
) -> dict:
    from destinations import load_destinations
    from ga4 import run_report
    from sitemap import fetch as fetch_sitemap
    from autoconfig import detect_config
    from redirect_engine import run
    from build_xlsx import build

    # ── 1. Load destination list ─────────────────────────────────────────────
    destinations, _aliases = load_destinations(destinations_b64)
    if not destinations:
        raise ValueError("קובץ היעדים ריק או שלא זוהו עמודות קונימבו")

    # ── 2. Fetch source rows ─────────────────────────────────────────────────
    source_rows: list = []
    errors: list = []

    if google_credentials:
        try:
            ga4_rows = run_report(ga4_property_id, site_url, google_credentials)
            source_rows.extend(ga4_rows)
        except Exception as exc:
            errors.append(f"GA4: {exc}")

    try:
        sitemap_rows = fetch_sitemap(site_url)
        existing = {r["url"] for r in source_rows}
        for sr in sitemap_rows:
            if sr["url"] not in existing:
                source_rows.append(sr)
    except Exception:
        pass  # sitemap is best-effort; never fatal

    if not source_rows:
        hint = f" (שגיאות: {'; '.join(errors)})" if errors else ""
        raise ValueError(f"לא נמצאו שורות מקור — GA4 וסיטמאפ שניהם ריקים{hint}")

    # ── 3. Auto-detect config, apply overrides ───────────────────────────────
    config = detect_config(source_rows, overrides=config_overrides)

    # ── 4. Run redirect engine ───────────────────────────────────────────────
    rows, stats = run(source_rows, destinations, config)

    # ── 5. Build xlsx ────────────────────────────────────────────────────────
    xlsx_bytes = build(rows, stats)

    # ── 6. Return base64 + filename ──────────────────────────────────────────
    slug = re.sub(r"https?://", "", site_url).rstrip("/")
    slug = re.sub(r"[^a-z0-9א-תA-Z\-._]", "-", slug).strip("-")
    filename = f"301-redirects-{slug}.xlsx"

    return {
        "file_b64": base64.b64encode(xlsx_bytes).decode(),
        "filename": filename,
    }
