# Claude Code — kickoff prompt: Konimbo 301 redirect builder

Paste this as the opening message in Claude Code. Full detail lives in `docs/spec.md`.

## What we're building

A tool that turns any old site's URLs into a 301-redirect file for its Konimbo migration.
Input: a site URL + GA4 property + a manual Excel of Konimbo destinations.
Output: an Excel redirect file in the client format (sheet `מאוחד`, columns `כותרת` / `לינק מאתר קודם` / `לינק חדש`).

**Read `docs/spec.md` first — it is the source of truth.** All decisions below are locked there.

## Locked decisions

- Platform: **Windmill**, all-Python. Front-end: a static `web/index.html` hosted on Vercel.
- Sources: **GA4** (primary; `runReport`, pagePath + pageTitle + screenPageViews ≥ 5, 90 days). Sitemap = best-effort supplement. No Search Console.
- Destinations: provided **manually** as an uploaded Excel (title + URL). No Konimbo API.
- Rules are **per-site config with defaults**, not hardcoded (skill principle: detect, don't assume). Defaults: `/en`→homepage; products = `/product/`, `/products/`, `/catalog/product/`; keep `?srsltid=` variants; collapse literal duplicates; protocol normalized; homepage detected from data. Override per site via config: `product_segments`, `category_keep_substrings`, `language_rules` ({prefix, action: homepage|match}), `title_separators`/`brand`, `aliases`, `keep_query_variants`.
- Matching: a **normalized VLOOKUP by title** — clean both sides (strip brand suffix, trim, lowercase, apply aliases), exact match, else homepage. No fuzzy auto-matching.

## The proven core

`redirect_engine.py` already exists and is validated on a real client file (esspressobar). It is **site-agnostic and config-driven** — `run(source_rows, destinations, config)` takes a `config` dict (see `DEFAULT_CONFIG` in the file) so product patterns, language rules, brand/aliases, and variant policy change per site without editing code. **Reuse it as-is** — do not rewrite it, and do not bake any single client's values into it.

## Build order

1. **`destinations.py`** — read the uploaded Excel (any column order; identify by content: the `*.konimbo.co.il` column = URL, the text column = title). Build `[{title, url}]` + a small alias map (e.g. `בלוג`→`CoffeeBlog`).
2. **`autoconfig.py`** — already built. `detect_config(source_rows, overrides=None)` infers platform/product patterns, language prefixes, and brand from the data; explicit overrides win. Call it before `redirect_engine.run` so most sites need no manual config.
3. **`ga4.py`** — call GA4 Data API `runReport` with the params above (Google OAuth2). Return `[{title, url, pageviews}]`.
4. **`sitemap.py`** — fetch/parse sitemap candidates (`/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`, `/wp-sitemap.xml`), follow nested index, exclude products. Best-effort (may return empty).
5. **`build_xlsx.py`** — write the 3-column `מאוחד` sheet + a `דוח` (report) sheet with a match-status column + a `סיכום` sheet. RTL, Arial, frozen header.
6. **`build_301.py`** — the Windmill entry. See contract below. Orchestrates: ga4+sitemap → merge → `autoconfig.detect_config(rows)` → `redirect_engine.run(rows, destinations, config)` → build_xlsx → return base64.
7. Wire the front-end: paste the Windmill webhook URL into `web/index.html`'s field; deploy `web/` to Vercel.

## Data contract (front-end ⇄ Windmill) — already implemented in index.html

Request (JSON POST to the Windmill webhook):
```json
{ "site_url": "...", "ga4_property_id": "...", "destinations_b64": "<base64 xlsx>", "destinations_filename": "x.xlsx" }
```
So the Windmill entry must be:
```python
def main(site_url: str, ga4_property_id: str, destinations_b64: str, destinations_filename: str = "destinations.xlsx"):
    ...
    return {"file_b64": "<base64 of the output xlsx>", "filename": "301-redirects-<site>.xlsx"}
```
The page reads `file_b64` + `filename` and downloads.

## Acceptance test

Espressobar is **one fixture, not the target** — the tool must work for any site via config. Regression check with the *default* config against the espressobar inputs:
70 input rows → 2 products removed, 14 literal duplicates collapsed, 16 `/en/`→homepage → 54 output rows; non-`/en/` rows match the human file (only the `בלוג`/`CoffeeBlog` alias differs unless an alias is supplied). Also add a small test proving a different config (e.g. Magento `product_segments`, a `match` language rule) changes behavior without code edits.

## Notes

- GA4 titles carry a brand suffix (`פולי קפה - EspressoBar`); the cleaning step in `redirect_engine.py` strips it. This is only fully exercised on raw GA4 data.
- The destination Excel **must include titles** (not just URLs) for good match rates — see spec §11.
