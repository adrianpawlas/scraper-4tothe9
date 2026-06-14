"""Scrape 4tothe9 — a Shopify store.

Strategy
--------
1. For each category URL use Playwright to scroll-and-collect every product link
   (handles lazy-loading / infinite scroll).
2. Deduplicate all product URLs across categories.
3. Fetch structured JSON for each product via Shopify's ``/products/<handle>.json``
   endpoint (no rendering needed — pure server-side JSON).
"""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

from scraper.config import (
    CATEGORY_URLS,
    CATEGORY_MAP,
    MAX_SCROLL_ATTEMPTS,
    SCROLL_PAUSE_SECONDS,
)
from scraper.models import ProductData

_session = requests.Session()

# ── public API ───────────────────────────────────────────────────────────────


def discover_product_urls() -> dict[str, set[str]]:
    """Return ``{category_handle: {product_url, ...}}`` for every category."""
    result: dict[str, set[str]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        for url in CATEGORY_URLS:
            handle = url.strip("/").rsplit("/", 1)[-1]
            print(f"\n  Category: {CATEGORY_MAP.get(handle, handle)}")
            urls = _scroll_and_collect_links(page, url)
            result[handle] = urls
            print(f"    -> {len(urls)} products found")
        browser.close()
    return result


def fetch_product_json(product_url: str) -> Optional[dict]:
    """Fetch Shopify JSON for a single product via ``/products/<handle>.json``."""
    handle = _extract_handle(product_url)
    if not handle:
        return None
    json_url = f"https://4tothe9.com/products/{handle}.json"
    try:
        resp = _session.get(json_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("product")
    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        print(f"    [WARN] Failed JSON for {product_url}: {exc}")
        return None


def parse_product(
    product: dict,
    category_handles: set[str],
) -> Optional[ProductData]:
    """Convert a Shopify JSON product dict into a normalised ``ProductData``."""
    if not product:
        return None

    handle: str = product.get("handle", "")
    title: str = product.get("title", "").strip()
    if not title:
        return None

    product_url = f"https://4tothe9.com/products/{handle}"

    # ── Images ───────────────────────────────────────────────────────────────
    images = product.get("images", [])
    image_url = ""
    additional_urls: list[str] = []
    if images:
        first = images[0].get("src", "") if isinstance(images[0], dict) else ""
        image_url = _largest_shopify_image(first)
        for img in images[1:]:
            src = img.get("src", "") if isinstance(img, dict) else ""
            if src:
                additional_urls.append(_largest_shopify_image(src))

    additional_images = " , ".join(additional_urls) if additional_urls else None

    # ── Variants ─────────────────────────────────────────────────────────────
    variants = product.get("variants", [])
    prices: set[str] = set()
    sale_prices: set[str] = set()
    sizes: list[str] = []
    skus: list[str] = []
    currency = "EUR"  # Default for this brand; "prefer EUR then USD"

    # Determine option names from product-level options
    option_names: list[str] = []
    for opt in (product.get("options") or []):
        if isinstance(opt, dict):
            option_names.append(str(opt.get("name", "")))

    for v in variants:
        if not isinstance(v, dict):
            continue

        price_str = str(v.get("price", ""))

        # Shopify: compare_at_price is None / "" / "0.00" when not on sale
        compare_raw = v.get("compare_at_price")
        has_sale = False
        if compare_raw is not None:
            cs = str(compare_raw).strip()
            if cs not in ("", "0", "0.0", "0.00", "None"):
                has_sale = True

        if has_sale:
            # On sale: compare_at_price = original price, price = sale price
            prices.add(str(compare_raw))   # original -> `price` column
            sale_prices.add(price_str)     # sale -> `sale` column
        else:
            if price_str:
                prices.add(price_str)      # regular price

        # Extract size from option1 (first option, which is "Size" for this brand)
        if option_names and option_names[0].lower() in ("size", "size:"):
            opt_val = str(v.get("option1", "")).strip()
            if opt_val:
                sizes.append(opt_val)
        else:
            v_title = v.get("title", "")
            if v_title and v_title not in ("Default Title", "Default"):
                sizes.append(v_title)

        # SKU
        sku = v.get("sku", "")
        if sku:
            skus.append(sku)

    on_sale = bool(sale_prices)

    # ── Format prices with currency ──────────────────────────────────────────
    def _fmt_price(vals: set[str]) -> str:
        """Sort numerically, deduplicate, append currency."""
        deduped = sorted(set(vals), key=lambda x: float(x) if _is_numeric(x) else 0.0)
        return ", ".join(f"{p}{currency}" for p in deduped)

    price_str: Optional[str] = None
    sale_str: Optional[str] = None

    if prices:
        price_str = _fmt_price(prices)

    if on_sale and sale_prices:
        sale_str = _fmt_price(sale_prices)

    # ── Category ─────────────────────────────────────────────────────────────
    categories = [
        CATEGORY_MAP.get(ch, ch.replace("-", " ").title())
        for ch in category_handles
    ]
    category_str = ", ".join(sorted(set(categories)))

    product_type = product.get("product_type", "").strip()
    if product_type and product_type not in category_str:
        category_str = f"{product_type}, {category_str}" if category_str else product_type

    # ── Description ──────────────────────────────────────────────────────────
    desc_html = product.get("body_html", "") or ""
    desc_text = re.sub(r"<[^>]+>", " ", desc_html).strip()
    desc_text = re.sub(r"\s+", " ", desc_text)

    # ── Gender ───────────────────────────────────────────────────────────────
    gender = _infer_gender(title, desc_text, product.get("tags", ""))

    # ── Tags ─────────────────────────────────────────────────────────────────
    tags_raw = product.get("tags", [])
    tags: list[str] = []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if t]

    # ── Metadata ─────────────────────────────────────────────────────────────
    metadata_dict: dict = {
        "shopify_id": product.get("id"),
        "handle": handle,
        "vendor": product.get("vendor"),
        "product_type": product_type,
        "skus": skus,
        "variants_count": len(variants),
        "currency": currency,
    }
    if sizes:
        metadata_dict["sizes"] = sizes

    extra = _extract_structured_info(desc_text)
    metadata_dict.update(extra)

    metadata_json = json.dumps(metadata_dict, ensure_ascii=False)

    # ── Size (display column) ────────────────────────────────────────────────
    size_display = sizes[0] if sizes else None

    # ── Build ProductData ────────────────────────────────────────────────────
    return ProductData(
        id=ProductData.compute_id("scraper-49", product_url),
        product_url=product_url,
        image_url=image_url,
        back_image_url=None,
        back_image_embedding=None,
        title=title,
        description=desc_text or None,
        category=category_str or None,
        gender=gender,
        price=price_str,
        sale=sale_str if on_sale else None,
        metadata=metadata_json,
        size=size_display,
        tags=tags if tags else None,
        additional_images=additional_images,
    )


# ── internal helpers ─────────────────────────────────────────────────────────


def _scroll_and_collect_links(page, url: str) -> set[str]:
    """Scroll through a Shopify collection page and collect all product links."""
    try:
        page.goto(url, wait_until="networkidle", timeout=60_000)
    except Exception as exc:
        print(f"    [WARN] Navigation failed for {url}: {exc}")
        return set()

    # Wait for at least one product link to appear (confirms products are loaded)
    try:
        page.wait_for_selector("a[href*='/products/']", timeout=15_000)
    except Exception:
        # No product links found even after waiting — category might be empty
        print(f"    [INFO] No product links found on {url} after waiting")
        return set()

    links: set[str] = set()
    prev_count = -1
    stalled = 0

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        new_links = page.eval_on_selector_all(
            "a[href*='/products/']",
            "els => els.map(el => el.href.split('?')[0])",
        )
        for href in new_links:
            if "/products/" in href and "4tothe9.com" in href:
                links.add(href)

        if len(links) == prev_count:
            stalled += 1
            # Break after 3 stalls total, or immediately if we have 0 links
            if stalled >= 3:
                break
        else:
            stalled = 0
        prev_count = len(links)

        page.evaluate("window.scrollBy(0, 1500)")
        page.wait_for_timeout(SCROLL_PAUSE_SECONDS * 1000)

        page.evaluate("""
            const cont = document.querySelector(
                '.collection__products, .product-grid, main'
            );
            if (cont) cont.scrollBy(0, 1500);
        """)
        page.wait_for_timeout(500)

    return links


def _extract_handle(product_url: str) -> Optional[str]:
    """Extract the Shopify handle from a product URL."""
    parsed = urlparse(product_url)
    path = parsed.path.rstrip("/")
    m = re.search(r"/products/([^/]+)", path)
    return m.group(1) if m else None


def _largest_shopify_image(src: str) -> str:
    """Strip Shopify image size suffixes so the CDN returns the original."""
    if not src:
        return ""
    cleaned = re.sub(
        r"_(?:\d+x\d+|small|medium|large|compact|thumbnail|master)",
        "",
        src,
    )
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    return cleaned


def _infer_gender(title: str, description: str, tags_raw) -> Optional[str]:
    """Guess gender from title, description, and tags."""
    if isinstance(tags_raw, str):
        tags_text = tags_raw
    elif isinstance(tags_raw, list):
        tags_text = " ".join(str(t) for t in tags_raw)
    else:
        tags_text = ""

    text = f"{title} {description} {tags_text}".lower()
    if any(w in text for w in ("woman", "women", "female", "girl", "womens", "ladies")):
        return "woman"
    if any(w in text for w in ("man", "men", "male", "boy", "mens", "gentleman")):
        return "man"
    return None


def _extract_structured_info(description: str) -> dict:
    """Extract composition, care, and material info from description text."""
    info: dict = {}
    lines = description.split("\n")
    current_section: Optional[str] = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(w in lower for w in ("composition", "fabric", "material", "content")):
            current_section = "composition"
            info["composition"] = line.split(":", 1)[-1].strip() if ":" in line else line
        elif any(w in lower for w in ("care", "washing", "wash", "dry clean")):
            current_section = "care"
            info["care"] = line.split(":", 1)[-1].strip() if ":" in line else line
        elif any(w in lower for w in ("features", "details", "fit")):
            current_section = line.split(":", 1)[0].strip().lower()
            val = line.split(":", 1)[-1].strip() if ":" in line else ""
            if val:
                info[current_section] = val
        elif current_section and line and not line.startswith("<"):
            existing = info.get(current_section, "")
            if existing:
                info[current_section] = f"{existing} {line}"
    return info


def _is_numeric(s: str) -> bool:
    """Check if string can be parsed as a float."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
