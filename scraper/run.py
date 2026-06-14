"""Main scraper orchestrator."""

from __future__ import annotations

import os
import sys
import time
from io import BytesIO
from typing import Optional

import requests
from PIL import Image as PILImage

from scraper import db
from scraper.config import BATCH_SIZE, SOURCE
from scraper.embeddings import embed_image, embed_text
from scraper.models import ProductData
from scraper.shopify_scraper import (
    discover_product_urls,
    fetch_product_json,
    parse_product,
)
from scraper.shopify_scraper import _extract_handle


def _normalize_url(url: str) -> str:
    """Strip collection prefix to get canonical product URL."""
    handle = _extract_handle(url)
    if handle:
        return f"https://4tothe9.com/products/{handle}"
    return url


def main():
    start = time.time()
    print("=" * 60)
    print("  4tothe9 Product Scraper")
    print(f"  Source: {SOURCE}")
    print("=" * 60)

    # ── Validate configuration early ────────────────────────────────────────
    from scraper.config import validate_config
    try:
        validate_config()
    except ValueError as e:
        print(f"\n  [CONFIG ERROR] {e}")
        sys.exit(1)

    # ── Discover product URLs ────────────────────────────────────────────────
    print("\n[1/4] Discovering product URLs across categories ...")
    category_links = discover_product_urls()

    # Normalize to canonical URLs (strip collection prefix) and deduplicate
    canonical_urls: set[str] = set()
    product_categories: dict[str, set[str]] = {}
    for handle, urls in category_links.items():
        for url in urls:
            canonical = _normalize_url(url)
            canonical_urls.add(canonical)
            product_categories.setdefault(canonical, set()).add(handle)

    print(f"\n  Total unique product URLs: {len(canonical_urls)}")

    if not canonical_urls:
        print("\n  [ERROR] No products found. Aborting.")
        sys.exit(1)

    # ── Fetch existing DB rows for smart diffing ─────────────────────────────
    print("\n[2/4] Fetching existing products from Supabase ...")
    existing_map = db.fetch_all_existing()
    print(f"  Existing products in DB: {len(existing_map)}")

    # ── Process each product ─────────────────────────────────────────────────
    print("\n[3/4] Scraping, parsing, embedding, and upserting ...")

    pending_batch: list[ProductData] = []
    stats = {
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "front_embeddings": 0,
        "text_embeddings": 0,
        "errors": 0,
        "upserted": 0,
    }
    failed_ids: list[str] = []

    for idx, product_url in enumerate(sorted(canonical_urls), 1):
        print(f"\n  [{idx}/{len(canonical_urls)}] {product_url}")

        # Fetch Shopify JSON
        shopify_product = fetch_product_json(product_url)
        if not shopify_product:
            print("    [SKIP] Could not fetch product JSON")
            stats["errors"] += 1
            continue

        # Parse
        pd = parse_product(shopify_product, product_categories.get(product_url, set()))
        if not pd:
            print("    [SKIP] Could not parse product")
            stats["errors"] += 1
            continue

        # Determine action: NEW, UPDATE, or SKIP
        existing = existing_map.get(product_url)
        is_new = existing is None
        needs_image_embed = False
        needs_text_embed = False
        needs_update = False

        if is_new:
            needs_image_embed = True
            needs_text_embed = True
            needs_update = True
        else:
            if pd.image_url != existing.image_url:
                needs_image_embed = True
            if pd.text_fields_changed(existing):
                needs_text_embed = True
            if pd.scalar_fields_changed(existing):
                needs_update = True

        if not needs_update and not needs_image_embed and not needs_text_embed:
            stats["skipped"] += 1
            print("    [SKIP] No changes detected")
            continue

        # Generate image embedding (front only — no back shots for this brand)
        if needs_image_embed and pd.image_url:
            print("    → Embedding front image ...")
            pil_image = _download_image(pd.image_url)
            if pil_image:
                emb = embed_image(pil_image)
                if emb:
                    pd.image_embedding = emb
                    stats["front_embeddings"] += 1
                else:
                    print("    [WARN] Image embedding failed, continuing")
            else:
                print("    [WARN] Could not download image, skipping embedding")

        # Generate text embedding
        if needs_text_embed:
            info_text = pd.build_info_text()
            if info_text:
                print(f"    → Embedding product info text ({len(info_text)} chars) ...")
                emb = embed_text(info_text)
                if emb:
                    pd.info_embedding = emb
                    stats["text_embeddings"] += 1
                else:
                    print("    [WARN] Text embedding failed, continuing")

        # Track stats
        if is_new:
            stats["new"] += 1
        else:
            stats["updated"] += 1

        # Add to batch
        pending_batch.append(pd)

        # Flush when batch is full
        if len(pending_batch) >= BATCH_SIZE:
            _flush_batch(pending_batch, failed_ids)

    # ── Flush remaining batch ────────────────────────────────────────────────
    if pending_batch:
        _flush_batch(pending_batch, failed_ids)

    # ── Stale cleanup ────────────────────────────────────────────────────────
    print("\n[4/4] Cleaning up stale products ...")
    deleted = db.delete_stale_products(existing_map, canonical_urls)
    if deleted:
        print(f"  Deleted {deleted} stale product(s)")

    # ── Run summary ──────────────────────────────────────────────────────────
    elapsed = time.time() - start
    total_errors = stats["errors"] + len(failed_ids)

    print("\n" + "=" * 60)
    print("  RUN SUMMARY")
    print("=" * 60)
    print(f"  New products added:            {stats['new']}")
    print(f"  Products updated:              {stats['updated']}")
    print(f"  Products unchanged (skipped):  {stats['skipped']}")
    print(f"  Front embeddings generated:    {stats['front_embeddings']}")
    print(f"  Back embeddings generated:     0 (none — brand has no back shots)")
    print(f"  Text embeddings generated:     {stats['text_embeddings']}")
    print(f"  Stale products deleted:        {deleted}")
    print(f"  Errors / failures:             {total_errors}")
    print(f"  Total time:                    {elapsed:.1f}s")
    print("=" * 60)

    # ── Write failed log ─────────────────────────────────────────────────────
    if failed_ids:
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"failed_products_{int(start)}.log")
        with open(log_path, "w") as f:
            for fid in failed_ids:
                f.write(fid + "\n")
        print(f"\n  Failed product IDs written to {log_path}")

    if total_errors > 0:
        sys.exit(1)


# ── Batch flush helper ──────────────────────────────────────────────────────


def _flush_batch(batch: list[ProductData], failed_ids: list[str]) -> int:
    """Upsert a batch to Supabase. Clears the batch list after.

    Returns number of rows upserted (0 if complete failure).
    """
    if not batch:
        return 0

    print(f"\n    ── Upserting batch of {len(batch)} products ...")
    inserted = db.upsert_batch(batch)

    if inserted == 0:
        print("    [ERROR] Batch upsert failed entirely after retries")
        for p in batch:
            failed_ids.append(p.product_url)
    elif inserted < len(batch):
        print(f"    [WARN] Partial upsert: {inserted}/{len(batch)} rows")

    print(f"    → {inserted} rows affected")
    batch.clear()
    return inserted


# ── Image download helper ──────────────────────────────────────────────────


_session = requests.Session()


def _download_image(url: str) -> Optional[PILImage.Image]:
    """Download an image from a URL and return a PIL Image."""
    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        return PILImage.open(BytesIO(resp.content))
    except requests.RequestException as exc:
        print(f"    [WARN] Failed to download image {url[:80]}: {exc}")
        return None
    except Exception as exc:
        print(f"    [WARN] Failed to decode image {url[:80]}: {exc}")
        return None


if __name__ == "__main__":
    main()
