"""
Acceptance and unit tests for the Konimbo 301 redirect engine.

Synthetic espressobar fixture (70 rows):
  16  /en/ URLs                          → lang-rule  → homepage
   2  product URLs (/product/<slug>)     → removed
  14  duplicate extra rows               → collapsed
  38  unique regular pages               → title-match or homepage-fallback
  ─────────────────────────────────────────────────────────────────────
  70  total input rows  →  54 output rows
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from redirect_engine import (
    DEFAULT_CONFIG,
    clean_title,
    dedup_key,
    is_product,
    language_action,
    run,
    slug_title,
)


# ── helpers ──────────────────────────────────────────────────────────────────

BASE = "https://espressobar.com"
KONIMBO = "http://espressobar.konimbo.co.il"
# detect_homepage always normalises to https:// from the netloc
HOMEPAGE = "https://espressobar.konimbo.co.il/"


def _dest(slug, title):
    return {"url": f"{KONIMBO}/{slug}", "title": title}


def _src(path, title="", pageviews=10):
    return {"url": BASE + path, "title": title, "pageviews": pageviews}


# ── espressobar fixture ───────────────────────────────────────────────────────

# 38 regular pages (each matched to a destination, or homepage-fallback)
REGULAR_PAGES = [
    ("/product-category/coffee-beans",  "פולי קפה - EspressoBar"),
    ("/product-category/capsules",      "קפסולות - EspressoBar"),
    ("/product-category/accessories",   "אביזרים - EspressoBar"),
    ("/product-category/machines",      "מכונות קפה - EspressoBar"),
    ("/product-category/gift-sets",     "מארזי מתנה - EspressoBar"),
    ("/product-category/instant",       "קפה מיידי - EspressoBar"),
    ("/product-category/cold-brew",     "קולד ברו - EspressoBar"),
    ("/product-category/decaf",         "נטול קפאין - EspressoBar"),
    ("/product-category/organic",       "קפה אורגני - EspressoBar"),
    ("/product-category/filter",        "קפה לפילטר - EspressoBar"),
    ("/pages/about",                    "אודות - EspressoBar"),
    ("/pages/contact",                  "צור קשר - EspressoBar"),
    ("/pages/privacy",                  "מדיניות פרטיות - EspressoBar"),
    ("/pages/terms",                    "תנאי שימוש - EspressoBar"),
    ("/pages/shipping",                 "משלוחים - EspressoBar"),
    ("/pages/returns",                  "החזרות - EspressoBar"),
    ("/pages/faq",                      "שאלות נפוצות - EspressoBar"),
    ("/pages/gift-guide",               "מדריך מתנות - EspressoBar"),
    ("/pages/wholesale",                "סיטונאות - EspressoBar"),
    ("/pages/academy",                  "האקדמיה - EspressoBar"),
    ("/blog",                           "בלוג - EspressoBar"),
    ("/blog/how-to-brew",               "איך להכין קפה - EspressoBar"),
    ("/blog/espresso-guide",            "מדריך אספרסו - EspressoBar"),
    ("/blog/origin-stories",            "סיפורי מקור - EspressoBar"),
    ("/blog/recipes",                   "מתכונים - EspressoBar"),
    ("/blog/news",                      "חדשות - EspressoBar"),
    ("/product-category/subscriptions", "מנויים - EspressoBar"),
    ("/product-category/bundles",       "חבילות - EspressoBar"),
    ("/product-category/limited",       "מהדורות מוגבלות - EspressoBar"),
    ("/product-category/seasonal",      "עונתי - EspressoBar"),
    ("/pages/store-locator",            "מציאת חנות - EspressoBar"),
    ("/pages/loyalty",                  "מועדון נאמנות - EspressoBar"),
    ("/pages/careers",                  "קריירה - EspressoBar"),
    ("/pages/press",                    "עיתונות - EspressoBar"),
    ("/pages/sustainability",           "קיימות - EspressoBar"),
    ("/pages/events",                   "אירועים - EspressoBar"),
    ("/pages/corporate",                "מתנות לעסקים - EspressoBar"),
    ("/pages/newsletter",               "ניוזלטר - EspressoBar"),
]
assert len(REGULAR_PAGES) == 38

# Destinations — titles match the cleaned source titles for the first 20 pages
DESTINATIONS = [
    _dest("756788-פולי-קפה",           "פולי קפה"),
    _dest("756789-קפסולות",             "קפסולות"),
    _dest("756790-אביזרים",             "אביזרים"),
    _dest("756791-מכונות-קפה",          "מכונות קפה"),
    _dest("756792-מארזי-מתנה",          "מארזי מתנה"),
    _dest("756793-קפה-מיידי",           "קפה מיידי"),
    _dest("756794-קולד-ברו",            "קולד ברו"),
    _dest("756795-נטול-קפאין",          "נטול קפאין"),
    _dest("756796-קפה-אורגני",          "קפה אורגני"),
    _dest("756797-קפה-לפילטר",          "קפה לפילטר"),
    _dest("pages/55532-מדיניות-פרטיות", "מדיניות פרטיות"),
    _dest("pages/55533-תנאי-שימוש",     "תנאי שימוש"),
    _dest("pages/55534-משלוחים",        "משלוחים"),
    _dest("pages/55535-החזרות",         "החזרות"),
    _dest("pages/55536-שאלות-נפוצות",   "שאלות נפוצות"),
    _dest("pages/55537-מנויים",         "מנויים"),
    _dest("pages/55538-חבילות",         "חבילות"),
    _dest("pages/55539-מהדורות-מוגבלות","מהדורות מוגבלות"),
    _dest("pages/55540-עונתי",          "עונתי"),
    _dest("pages/55541-מועדון-נאמנות",  "מועדון נאמנות"),
    # homepage
    {"url": HOMEPAGE, "title": "EspressoBar"},
]


def _build_fixture():
    rows = []
    # 38 regular pages
    for path, title in REGULAR_PAGES:
        rows.append(_src(path, title))
    # 16 /en/ URLs
    for i in range(16):
        rows.append(_src(f"/en/page-{i}", f"English Page {i} - EspressoBar"))
    # 2 product URLs
    rows.append(_src("/product/yirgacheffe-250g",   "ירגצ'ף 250 גרם - EspressoBar"))
    rows.append(_src("/product/brazil-espresso-1kg", "ברזיל אספרסו 1 ק\"ג - EspressoBar"))
    # 14 duplicate rows (duplicating the first 14 regular pages)
    for i in range(14):
        path, title = REGULAR_PAGES[i]
        rows.append(_src(path, title))  # exact duplicate
    assert len(rows) == 70
    return rows


SOURCE_ROWS = _build_fixture()


# ── acceptance test ───────────────────────────────────────────────────────────

def test_espressobar_counts():
    rows, stats = run(SOURCE_ROWS, DESTINATIONS)
    assert stats["in"] == 70
    assert stats["products"] == 2,    f"expected 2 products, got {stats['products']}"
    assert stats["dupes"] == 14,      f"expected 14 dupes, got {stats['dupes']}"
    assert stats["lang"] == 16,       f"expected 16 lang-rule rows, got {stats['lang']}"
    assert stats["out"] == 54,        f"expected 54 output rows, got {stats['out']}"


def test_espressobar_lang_rules_go_to_homepage():
    rows, stats = run(SOURCE_ROWS, DESTINATIONS)
    lang_rows = [r for r in rows if r["_match"] == "lang-rule"]
    assert len(lang_rows) == 16
    for r in lang_rows:
        assert r["לינק חדש"] == HOMEPAGE


def test_espressobar_title_matches():
    rows, stats = run(SOURCE_ROWS, DESTINATIONS)
    # All pages with matching destinations should be title-matched
    title_rows = [r for r in rows if r["_match"] == "title-match"]
    assert len(title_rows) >= 10, "expected at least 10 title-match rows"


def test_espressobar_no_duplicates_in_output():
    rows, _ = run(SOURCE_ROWS, DESTINATIONS)
    sources = [r["לינק מאתר קודם"] for r in rows]
    assert len(sources) == len(set(sources)), "duplicate sources found in output"


def test_espressobar_every_row_has_destination():
    rows, _ = run(SOURCE_ROWS, DESTINATIONS)
    for r in rows:
        assert r.get("לינק חדש"), f"row missing destination: {r}"


def test_blog_alias():
    """With בלוג→CoffeeBlog alias the blog row matches; without it falls back to homepage."""
    blog_src = [_src("/blog", "בלוג - EspressoBar")]
    dests = [{"url": f"{KONIMBO}/pages/coffeeblog", "title": "CoffeeBlog"}, {"url": HOMEPAGE, "title": "EspressoBar"}]

    rows_no_alias, _ = run(blog_src, dests)
    assert rows_no_alias[0]["_match"] == "homepage-fallback"

    rows_alias, _ = run(blog_src, dests, {"aliases": {"בלוג": "coffeeblog"}})
    assert rows_alias[0]["_match"] == "title-match"


# ── config-change tests ───────────────────────────────────────────────────────

def test_magento_product_segments_change_behavior():
    """
    Shopify config only removes /products/, leaving /catalog/product/ alone.
    Magento config only removes /catalog/product/, leaving /products/ alone.
    Same engine code, different config → different behaviour.
    """
    shopify_product = _src("/products/some-bag",          "Some Bag")
    magento_product = _src("/catalog/product/some-item",  "Some Item")
    regular         = _src("/category/beans",             "פולי קפה - EspressoBar")
    dests = [{"url": HOMEPAGE, "title": "EspressoBar"}]
    all_rows = [shopify_product, magento_product, regular]

    # Shopify config: /products/ is a product; /catalog/product/ is NOT
    shopify_cfg = {
        "product_segments": [["products"]],
        "category_keep_substrings": ["collections"],
    }
    rows_s, stats_s = run(all_rows, dests, shopify_cfg)
    assert stats_s["products"] == 1, f"shopify config: expected 1 product removed, got {stats_s['products']}"
    assert any(r["לינק מאתר קודם"].endswith("/catalog/product/some-item") for r in rows_s), \
        "shopify config should keep /catalog/product/"
    assert not any(r["לינק מאתר קודם"].endswith("/products/some-bag") for r in rows_s), \
        "shopify config should remove /products/"

    # Magento config: /catalog/product/ is a product; /products/ is NOT
    magento_cfg = {
        "product_segments": [["catalog", "product"]],
        "category_keep_substrings": ["catalog/category"],
    }
    rows_m, stats_m = run(all_rows, dests, magento_cfg)
    assert stats_m["products"] == 1, f"magento config: expected 1 product removed, got {stats_m['products']}"
    assert any(r["לינק מאתר קודם"].endswith("/products/some-bag") for r in rows_m), \
        "magento config should keep /products/"
    assert not any(r["לינק מאתר קודם"].endswith("/catalog/product/some-item") for r in rows_m), \
        "magento config should remove /catalog/product/"


def test_language_rule_match_action():
    """
    Default: /en/ → homepage.
    With action='match': /en/ rows go through normal title lookup instead.
    """
    en_rows = [_src("/en/coffee-beans", "פולי קפה - Brand")]
    dests = [{"url": f"{KONIMBO}/beans", "title": "פולי קפה"}, {"url": HOMEPAGE, "title": "EspressoBar"}]

    # Default: /en/ → homepage
    rows_hp, _ = run(en_rows, dests)
    assert rows_hp[0]["לינק חדש"] == HOMEPAGE
    assert rows_hp[0]["_match"] == "lang-rule"

    # match action: /en/ treated normally → title-match
    match_cfg = {"language_rules": [{"prefix": "/en", "action": "match"}]}
    rows_match, _ = run(en_rows, dests, match_cfg)
    assert rows_match[0]["_match"] == "title-match"
    assert rows_match[0]["לינק חדש"] == f"{KONIMBO}/beans"


# ── unit tests ────────────────────────────────────────────────────────────────

def test_is_product_woocommerce():
    assert is_product(BASE + "/product/slug", None) is True
    assert is_product(BASE + "/product-category/beans", None) is False
    assert is_product(BASE + "/products/bag", None) is True


def test_is_product_query_flag():
    assert is_product(BASE + "/?post_type=product&p=123", None) is True


def test_dedup_key_trailing_slash():
    assert dedup_key(BASE + "/page/") == dedup_key(BASE + "/page")


def test_dedup_key_case():
    assert dedup_key(BASE + "/Page") == dedup_key(BASE + "/page")


def test_dedup_key_keeps_srsltid():
    url = BASE + "/page?srsltid=abc"
    assert dedup_key(url, keep_query=True) != dedup_key(BASE + "/page", keep_query=True)
    assert dedup_key(url, keep_query=False) == dedup_key(BASE + "/page", keep_query=False)


def test_clean_title_strips_brand_suffix():
    cfg = {"title_separators": ["-", "|"], "brand": "EspressoBar", "aliases": {}}
    assert clean_title("פולי קפה - EspressoBar", cfg) == "פולי קפה"
    assert clean_title("Coffee | EspressoBar", cfg) == "coffee"


def test_clean_title_strips_any_suffix_when_no_brand():
    cfg = {"title_separators": ["-", "|"], "brand": None, "aliases": {}}
    result = clean_title("Page Title - SomeSite", cfg)
    assert result == "page title"


def test_clean_title_applies_alias():
    cfg = {"title_separators": ["-"], "brand": None, "aliases": {"בלוג": "coffeeblog"}}
    assert clean_title("בלוג - Brand", cfg) == "coffeeblog"


def test_language_action_homepage():
    cfg = {"language_rules": [{"prefix": "/en", "action": "homepage"}]}
    assert language_action(BASE + "/en/page", cfg) == "homepage"
    assert language_action(BASE + "/en", cfg) == "homepage"
    assert language_action(BASE + "/he/page", cfg) is None


def test_slug_title():
    assert slug_title(KONIMBO + "/756788-פולי-קפה") == "פולי קפה"
    assert slug_title(KONIMBO + "/pages/55532-מדיניות-פרטיות") == "מדיניות פרטיות"
