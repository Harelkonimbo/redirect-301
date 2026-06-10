# Integration Spec — Building 301 Redirects for Konimbo Migrations

> Working document. Version 0.1 — draft for approval.
> Goal: turn a ~3-hour manual task into a unified pipeline that produces a clean 301 redirect file.

---

## 1. Background & Goal

When a site migrates to the Konimbo platform, the old site's URLs change. To avoid losing traffic and SEO value, every old URL must be mapped to the correct new URL on Konimbo via a **301** (permanent) redirect.

**End goal:** a single, clean, validated 301 redirect file in which every old URL (that isn't a product) maps to exactly one destination URL on Konimbo — while maximizing coverage of the highest-value links.

**Core principle (301 = one-way function):** every source maps to **exactly one** destination. The reverse is fine — many sources can point to the same destination.

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| Homepage | **Products** — detected and removed from the file (handled separately) |
| Categories | |
| Content pages / articles / blog | |
| Info pages (about, terms, contact, etc.) | |

**Handling products:** products are handled separately via the `prev_url` field in Konimbo's product file (not part of this integration). Therefore the pipeline **detects** product URLs and **removes** them from the redirect file before output.

> Note: as a rule, the redirect Skill never deletes rows — it fixes the destination. This is a deliberate, intentional exception: product rows are deleted because they're covered by a different mechanism. Every such deletion is logged in the report for full transparency.

---

## 3. High-Level Architecture

Data flow in seven stages:

1. **Old-site URL sources** → GA4 analytics (primary, reliable) + sitemap (best-effort); Search Console optional for coverage.
2. **Normalize & merge** → one source table, deduplicated, with a priority per URL.
3. **Fetch destinations from Konimbo** → categories + pages via the API.
4. **Detect & remove products** → filter out product URLs from the source table.
5. **Matching engine** → match each source URL to the best destination on Konimbo.
6. **301 cleanup** → conflict detection, auto-fixes, manual decisions.
7. **Output** → 301 redirect file + summary report.

### Current state — what exists vs. what we build

An existing **n8n tool** (HTML form → webhook → workflow) covers part of the **front half**. In practice **only the GA4 path is reliable**; the sitemap path is best-effort and often returns empty:

| Built (n8n) | Stage | Status | Notes |
|---|---|---|---|
| GA4 `runReport` | C | ✅ **works — the reliable backbone** | `pagePath` + `pageTitle` + `screenPageViews`, last 90 days, **views ≥ 5**, top 10,000, desc. Gives URL **+ title + pageviews** |
| Sitemap fetch + parse | A | ⚠️ **built but unreliable** | Tries `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`, `/wp-sitemap.xml`; many old sites don't expose these → returns empty. Excludes products; titles empty when it does work |
| Multi-sheet Excel | D (partial) | ✅ | Sheets: `משיכת לינקים מהאתר`, `ANALYTICS`, `מאוחד` (**`כותרת` + `URL` only, no destination**) |

So in practice the input to our back half is **mostly GA4 rows** (URL + title + pageviews), with sitemap as an opportunistic supplement. What we build:

* **Stage E** — destination list (manual — pasted from Konimbo admin, no API)
* **Stage F (completion)** — apply the product filter to **GA4 rows too** (the sitemap-level filter doesn't cover them), plus the `/en/`→homepage rule
* **Stage G** — matching engine (fills the missing `לינק חדש` column; GA4 titles make title-matching viable)
* **Stage H** — 301 cleanup
* **Stage I** — final file in the esspressobar 3-column format

> **Coverage gap:** GA4 only captures pages with ≥ 5 views in 90 days; when the sitemap is also empty, low-traffic old URLs are missed entirely. This is the strongest argument for adding **Search Console** as a coverage source (see open question).



---

## 4. Data Model — The Unified Table

### Deliverable format (grounded in a real client file)

The final deliverable matches the exact format already in use: a **single sheet named `מאוחד`** ("Unified") with **exactly three columns**, identified by content (not by fixed name):

| Column (Hebrew) | Role | Example |
|---|---|---|
| `כותרת` | Title — the human label of the destination | `פולי קפה` |
| `לינק מאתר קודם` | Source — the old-site URL | `https://espressobar.com/product-category/coffee-beans` |
| `לינק חדש` | Destination — the Konimbo URL | `http://espressobar.konimbo.co.il/756788-...` |

The `כותרת` value is primarily the **destination's** name (the matched category/page), and serves as documentation. For unmatched rows it falls back to the old page's identity or a status flag (e.g. `לא נמצא מוצר כזה בקונימבו`).

### Internal working table (richer; collapses to the 3 columns above on export)

Internally we carry more columns to drive the logic, then project down to the deliverable's three:

| Column | Description | Source |
|---|---|---|
| `source_url` | Old URL, normalized (`http://`) | input |
| `title` | Title / H1 of the old page | input |
| `origin` | Which source it came from: `sitemap` / `gsc` / `analytics` | input |
| `traffic` | Visits/clicks — drives priority | analytics/GSC |
| `is_product` | Whether detected as a product (for filtering) | computed |
| `dest_url` | Destination URL on Konimbo (`https://`) | computed |
| `match_type` | `title-match` (VLOOKUP hit) / `homepage-fallback` / `en-rule` | computed |
| `clean_title` | Source title after brand-suffix stripping (the VLOOKUP key) | computed |

### Normalization rules (uniform across all sources)

There are **two distinct normalizations** — don't conflate them:

**(a) Matching key — used to *find* the destination.** Aggressive: strip query string, strip trailing `/`, `lowercase`, decode Hebrew. Folds `?srsltid=...`, slash, and case variants together so they all resolve to the same match.

**(b) Dedup key — used to decide which rows survive in the output.** Deliberately *keeps the query string*, because the policy is to **always keep `?srsltid=` variants** as their own rows. Only truly-identical rows (same literal source after slash+case normalization) are removed.

Other rules:

* **Protocol is per-client, detected from the data — not forced.** In the real example the source side is `https://` (espressobar.com), and the destination side is *mixed* (`http://` for categories, `https://` for `/pages/`). Identify source vs. destination by domain (`*.konimbo.co.il` = destination), then **normalize the destination protocol consistently** — this also collapses false "conflicts" (one source → same path under both `http` and `https`).
* The homepage is detected dynamically: the destination ending in `.konimbo.co.il/` with nothing after the slash (don't hard-code a subdomain).

### Routing overrides (per-site config, applied before matching)

These are **configurable rules**, not hardcoded — defaults below, override per site (see §11 config):

* **Language paths → homepage (default).** Each rule is `{prefix, action}`. Default: `/en` → homepage (espressobar has no English store). A different site might use `/eng`, or have a *real* translated store → set `action: match` so those URLs match normally instead of going to the homepage.
* **Aliases.** A per-site map of source-title → destination-title for renamed pages (e.g. `בלוג`→`CoffeeBlog`).

### Konimbo destination URL vocabulary (from the example)

The destinations come from your **manual list**; these are the shapes they take:

| Type | Pattern | Example |
|---|---|---|
| Homepage | `/` | `http://espressobar.konimbo.co.il/` |
| Category | `/{id}-{slug}` | `/756788-פולי-קפה` |
| Content page | `/pages/{id}-{slug}` | `/pages/55532-מדיניות-פרטיות` |
| System page | fixed slug | `/about`, `/contact`, `/contract` |

> Hebrew in destinations is URL-encoded (`%D7%...`) — handled in normalization.

---

## 5. Detailed Stages

### Stage A — Sitemap (built in n8n, best-effort)

The sitemap is an **opportunistic supplement**, not the backbone — in practice it often returns empty (old sites frequently don't expose a sitemap at the tried paths). When it does work, the tool: tries `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`, `/wp-sitemap.xml`; follows a nested `<sitemapindex>`; extracts `<loc>` URLs; **excludes products**; dedupes.

* **Titles come back empty** from the sitemap — only GA4 provides a title, so sitemap-only URLs match by slug/path, not title.
* Stage output (when available): `{title:'', url}`, `origin=sitemap`.

### Stage B — Google Search Console (not currently used)

Originally considered as the index source (instead of unreliable `site:` scraping), but the built tool covers index via the sitemap and traffic via GA4, so **GSC is not wired in**. Kept here as an optional future source (indexed URLs + clicks via the Search Console API) if coverage gaps appear. Decision pending — see open questions.

### Stage C — Analytics: GA4 (built in n8n)

The most valuable source for SEO: URLs with real traffic are exactly the ones that need a precise redirect, and the view count drives **priority**.

Concrete shape (from the workflow), via the GA4 Data API `properties/{id}:runReport`:

* Dimensions: `pagePath`, `pageTitle` · Metric: `screenPageViews`
* Date range: last 90 days · Filter: `screenPageViews >= 5` · Limit 10,000, ordered desc
* Auth: Google OAuth2 · Input: `siteUrl` + 9-digit `propertyId`
* Mapped to `{title: pageTitle, url: siteUrl + pagePath, pageviews}`, deduped by URL. `origin=analytics`, `traffic=pageviews`.

> **Gap to close in the back half:** GA4 rows are **not** product-filtered or `/en/`-filtered by the tool — we apply both downstream (Stage F).

### Stage D — Normalize & Merge

The n8n tool already produces the `מאוחד` sheet (sitemap ∪ GA4, columns `כותרת` + `URL`). Our back half consumes it and:

1. Applies the **matching-key** normalization to find destinations, and the **dedup-key** (keeps `?srsltid=`) to decide surviving rows (section 4).
2. When the same URL appears from both sitemap and GA4 — one row, carrying the GA4 `pageviews` as `traffic` and the GA4 `pageTitle` (sitemap titles are empty).
3. Keeps the best available title; sitemap-only URLs stay title-less and rely on slug/path matching.

### Stage E — Destination List (manual)

Instead of the Konimbo API, **you provide the destination list manually** — it's quick to copy the category/page URLs straight from the Konimbo admin, and it sidesteps the API's unknowns (content-page enumeration, URL construction, tokens).

The list is the universe of possible match targets:

* **Categories** — full URLs, e.g. `…konimbo.co.il/756788-פולי-קפה`
* **Content pages** — e.g. `…/pages/55532-מדיניות-פרטיות`
* **System pages** — `/about`, `/contact`, `/contract`
* The **homepage** (and its subdomain) is detected from these URLs — no hard-coding.

A title alongside each URL helps, but isn't required: the title can be derived from the slug (`/756788-פולי-קפה` → "פולי קפה") for matching against GA4 titles.

### Stage F — Detect & Remove Products

**Products never appear in a 301 redirect file** — they're handled entirely via `prev_url` in the product file. So every product URL is detected and removed, with no homepage fallback and no distinction between in-stock and discontinued.

Detection: product URLs use a distinct pattern — `/product/{slug}` (singular) — versus categories at `/product-category/{slug}`, so categories stay **in scope** and only true product pages are dropped. (With the API dropped, detection is by URL pattern; the manual destination list contains no products anyway.)

Everything filtered is flagged `is_product=true` and logged in the report (count only — products aren't expected in the input ideally, but real exports contain them).

### Stage G — The Matching Engine = a smarter VLOOKUP by title

This mirrors the manual method exactly: **VLOOKUP the source title against the Konimbo destination titles, return the URL.** It's an exact title lookup, not fuzzy matching.

**The lookup table:** built from the destination list. Each Konimbo URL yields a clean title from its slug (`/756788-פולי-קפה` → `פולי קפה`), giving `title → url`. (If the list already has a title column, use it.)

**Per source row:**

1. **Clean the title on both sides**, then exact-match. Cleaning is the whole game (a raw VLOOKUP fails without it):
   * Strip the brand suffix: `פולי קפה - EspressoBar` → `פולי קפה` (remove trailing `- {brand}` / `| {brand}`).
   * Trim whitespace, collapse double spaces, drop quotes.
2. **Match found** → that URL (`match_type=title-match`).
3. **No match** → homepage (`match_type=homepage-fallback`). You eyeball these.

So the model is essentially binary — matched title, or homepage — which removes the earlier confidence-threshold and manual-review machinery.

* **No fuzzy auto-matching.** Anything beyond a normalized-exact match is only ever surfaced as a *suggestion* for you to confirm, never auto-applied — because **a specific-but-wrong destination is worse than the homepage**.
* **Routing overrides still win first:** `/en/` → homepage before any lookup; products are already removed.

### Stage H — 301 Cleanup

Applies the Skill's logic to the merged table:

1. **Detect conflicts** — one source → multiple different destinations.
2. **Classify & fix:**
   * **Type A/B (homepage vs. real destination / query-string variant):** auto-fix — all rows to the real destination.
   * **Type C (two real destinations):** **your manual decision** — never guess.
3. **Remove exact duplicates** (same source+destination after fixes).

### Stage I — Output

* **Format = the existing client format**: a single sheet `מאוחד` with the three columns `כותרת` / `לינק מאתר קודם` / `לינק חדש`. Exported as `.xlsx`. (An optional second sheet can carry the richer working columns + the report for review.)
* Source and destination protocols normalized consistently (see section 4).
* **Variant policy (decided):** keep every `?srsltid=` query-string variant as its own row; collapse only truly-identical rows (same literal source after slash + case normalization). English `/en/` URLs are not kept as matches — they route to the homepage (see Routing overrides).
* **Summary report:**

| Action | Count |
|---|---|
| URLs collected (by source) | N |
| Products detected and removed | N |
| Auto matches (slug/path) | N |
| Title matches | N |
| Flagged for manual review | N |
| Fell back to homepage | N |
| Conflicts auto-fixed | N |
| Manual decisions applied | N |
| Final row count | N |

**End-state checks (mandatory):** zero sources with more than one destination · no exact duplicates · every row has a destination.

---

## 6. Key Business Rules

* 301 is one-way: source → single destination.
* Source `http`, destination `https` on `*.konimbo.co.il`.
* Homepage detected dynamically, not hard-coded.
* Query string is not a separate URL — `/foo` and `/foo?utm=x` go to the same destination.
* Case sensitivity neutralized in normalization.
* Real destination > homepage > specific-but-wrong destination.

---

## 7. Edge Cases to Handle

* **Missing / empty titles** — fall back to URL-only matching; if none, to the homepage.
* **Duplicate URLs across sources** — merged, max `traffic`.
* **Sources mistakenly using `https://`** — alert before fixing, wait for your approval (don't silently fix).
* **Broken Hebrew encoding / `U+FFFD` characters** — cleaned at ingestion.
* **Parent category with no products** — a legitimate destination.

---

## 8. Recommended Build Order

The front half (steps marked ✅) already exists in the n8n tool. We build the back half:

| Step | What we build | Status / Dependency |
|---|---|---|
| 1 | GA4 ingestion (URL + title + pageviews) | ✅ works (n8n) — backbone |
| 2 | Sitemap parser (excl. products) | ⚠️ built but unreliable |
| 3 | `מאוחד` sheet (source URLs) | ✅ built (n8n) |
| 4 | Load manual destination list (categories/pages) | your pasted list |
| 5 | Product + `/en/` filter on **all** rows (incl. GA4) | 3 + 4 |
| 6 | Matching engine (fills `לינק חדש`) | 4 + 5 |
| 7 | 301 cleanup + final 3-column file + report | 6 |

> A first build can run on the esspressobar example (input `מאוחד` + the known good output) to validate steps 5–7 before wiring the live Konimbo API.

---

## 9. Inputs Needed From You

- [ ] The Konimbo **destination list** (categories + content pages), copied from the admin — the one missing piece to go end-to-end
- [x] Analytics format — GA4 via n8n (`runReport`, views ≥ 5, 90 days)
- [x] Sitemap ingestion — built in n8n (best-effort)
- [ ] (Optional) Google Search Console access — only if we decide to add it for coverage
- [ ] A live test target — `hdhs.co.il` / `a-matata.co.il` appear in your config

---

## 10. Decisions — all resolved

* **Search Console** → skipped for now; kept as a future option if coverage gaps appear.
* **Where the back half runs** → a separate **Python** step that takes the exported Excel + the manual destination list; can be folded into n8n later for one-click.
* **Pages not to redirect** → only products (everything else gets a redirect; no-match → homepage).
* **Extra routing rules** → none beyond `/en/`→homepage; any unmatched URL → homepage.
* **Expected URL count** → unknowable up front (depends on the client's SEO footprint) → design for variable scale, no fixed cap.
* **GA4 window** → keep 90 days / ≥ 5 views as-is (do not widen).
* **Matching method** → a normalized VLOOKUP by title (clean both sides, exact match, else homepage) — mirrors the manual method. No fuzzy auto-matching.
* **Konimbo destinations** → provided manually (no API).
* **Discontinued products** → products never appear in 301 files at all; removed regardless of status (handled via `prev_url`).
* **Variant policy** → keep `?srsltid=` variants; `/en/` → homepage; collapse only literal duplicates.

---

## 11. Implementation (handoff to Claude Code)

### Platform — decided: Windmill, all-Python

Front-end: a single static `index.html` (RTL, matching the existing tool) hosted free on **Vercel**, posting JSON (file as base64) to the Windmill webhook.

| | n8n | Windmill |
|---|---|---|
| Python with pandas/openpyxl | Weak — Pyodide (cloud) blocks 3rd-party libs; self-hosted needs a custom runner image + per-lib allowlist; heavy Python usually runs as a separate FastAPI service called over HTTP | First-class — write a Python script, dependencies auto-handled |
| UI form | the existing HTML page → webhook | auto-generated from the function's typed params |
| Webhook / schedule / secrets | yes | yes (auto-generated webhooks, built-in secrets) |
| Fit for this project | great glue, wrong home for the pandas engine | natural home for the whole thing |

**Recommendation:** build one Python codebase on Windmill. The front half (GA4 = one HTTP call, sitemap = regex parse) ports trivially to Python, so splitting across two platforms/languages isn't worth it. n8n stays viable only if there's heavy existing investment there.

### Modules (all Python)

* `ga4.py` — GA4 Data API `runReport` (pagePath, pageTitle, screenPageViews ≥ 5, 90 days) → `{url, title, pageviews}`.
* `sitemap.py` — fetch + parse sitemap candidates, exclude products (best-effort).
* `destinations.py` — load the manual Konimbo list (title + url) → lookup table; small alias map (e.g. `בלוג`→`CoffeeBlog`).
* `autoconfig.py` — infer the per-site config from the source URLs/titles (platform → product patterns, language prefixes, brand). Output feeds `redirect_engine.run`; explicit overrides win. **(built and validated.)**
* `redirect_engine.py` — normalization (matching-key vs dedup-key), `/en/`→homepage, product removal, VLOOKUP-by-clean-title, homepage fallback, literal-dedup. **(POC built and validated.)**
* `build_xlsx.py` — write the 3-column `מאוחד` file + report sheet.
* `main.py` — Windmill entry `def main(site_url, ga4_property_id, destinations_xlsx, ...)`; the form + webhook are auto-generated from it.

### Front-end — a web page (per-site, reusable)

The tool runs on **any site** the user points it at. The page has **three inputs**:

1. Site URL
2. GA4 Property ID
3. **Destinations Excel upload** — the Konimbo category/page list (title + URL) for *that* site

→ POSTs `multipart/form-data` to the backend webhook → downloads the finished 301 file. A starter page (`build-301-form.html`, RTL, matching the existing tool's style) is built. Alternatively, Windmill auto-generates an equivalent form (including the file-upload param) for free. Either way, the destination list is supplied **per run**, so nothing is hard-coded to any one client — the esspressobar run was only a logic proof.

### Per-site configuration (dynamic — nothing hardcoded to one client)

Per the skill's "detect, don't assume" principle, anything that varies by site is **config with defaults**, not a code constant. The engine (`redirect_engine.py`) is site-agnostic; only this config changes between sites:

| Setting | What it controls | Default | Why per-site |
|---|---|---|---|
| `product_segments` | URL patterns that mark a product (removed) | `[["product"],["products"],["catalog","product"]]` | WooCommerce vs Magento vs Shopify vs custom differ |
| `category_keep_substrings` | paths never treated as product | `["product-category"]` | platform-specific category paths |
| `language_rules` | `{prefix, action}` — `homepage` or `match` | `[{"/en","homepage"}]` | some sites use `/eng`, or have a real translated store |
| `title_separators` / `brand` | brand-suffix stripping before VLOOKUP | separators set; brand auto | brand name + separator differ per site |
| `aliases` | source-title → dest-title for renamed pages | `{}` | e.g. `בלוג`→`CoffeeBlog` |
| `keep_query_variants` | keep `?srsltid=` rows vs collapse | `True` | client preference; skill default is collapse |
| GA4 window / threshold | lookback + min views | 90 days / ≥5 | tuning per site |

Validated: with the default config the engine reproduces the espressobar output exactly; switching `product_segments` to Magento makes `/product/` *not* a product and `/catalog/product/` a product, and switching a language rule to `match` keeps that language matching normally — all without touching code. **Espressobar is one test fixture, not the target.**

#### Auto-config (zero manual setup by default)

`autoconfig.py` infers the config from the source data before each run, so most sites need **no manual configuration**:

* **Platform** → from URL markers (`/product/` + `wp-json` = WooCommerce; `/products/` + `/collections/` = Shopify; `/catalog/product/` = Magento; …) → sets `product_segments` + `category_keep_substrings`.
* **Languages** → path prefixes that recur (`/en`, `/eng`, …) → `language_rules` (default action `homepage`; flip to `match` for a real translated store).
* **Brand** → the suffix that recurs across titles (` - Brand`) → `brand` for clean stripping.

Anything explicitly passed by the caller **overrides** the auto-detected value. Validated: on espressobar, auto-config alone (WooCommerce + `/en`) reproduces the 54-row result; synthetic Shopify/Magento sites are classified correctly.

What stays generic (never per-site): column identification by content, homepage detection, conflict types A/B/C, normalization, one-source-one-destination, wrong-but-specific-worse-than-homepage. All straight from the skill.

### Proof of concept (run on the esspressobar fixture)

70 input rows → 2 products removed, 14 literal duplicates collapsed, 16 `/en/`→homepage → **54 output rows**. Against the human-made file: ~all non-`/en/` rows reproduced; the 10 `/en/` differences are the intended new rule; with titles in the destination list only **2 real misses** remained (the `בלוג`/`CoffeeBlog` alias case).

**Key learning:** the Konimbo destination list must include **titles**, not just URLs — that alone lifts the auto-match rate sharply. A small per-client alias map handles the few renamed pages. Brand-suffix cleaning of GA4 titles is implemented but only fully testable on a raw GA4 export.
