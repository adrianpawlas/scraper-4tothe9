"""Supabase read / upsert / cleanup operations.

Uses the Supabase REST API (PostgREST) directly.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from scraper.config import (
    SOURCE,
    SUPABASE_URL,
    SUPABASE_KEY,
    MAX_RETRIES,
)
from scraper.models import ProductData

_session = requests.Session()

TABLE = "products"
_HEADERS = {
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "apikey": SUPABASE_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

# ── Read existing products ──────────────────────────────────────────────────


def fetch_all_existing() -> dict[str, ProductData]:
    """Fetch every product for this source and return a dict keyed by product_url."""
    rows: list[dict] = []
    offset = 0
    limit = 1000

    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    params: dict = {
        "select": "*",
        "source": f"eq.{SOURCE}",
        "order": "id",
        "limit": limit,
        "offset": offset,
    }

    while True:
        try:
            resp = _session.get(url, headers=_HEADERS, params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            offset += limit
            params["offset"] = offset
        except requests.RequestException as exc:
            print(f"  [WARN] Failed to fetch existing at offset {offset}: {exc}")
            break

    result: dict[str, ProductData] = {}
    for r in rows:
        pu = r.get("product_url", "")
        if pu:
            result[pu] = ProductData.from_db_row(r)
    return result


# ── Upsert batching ─────────────────────────────────────────────────────────


def upsert_batch(products: list[ProductData]) -> int:
    """Upsert a batch of products. Returns number of rows sent (0 on failure)."""
    if not products:
        return 0

    rows = [p.to_upsert_dict() for p in products]
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    params = {"on_conflict": "source,product_url"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _session.post(
                url,
                headers=_HEADERS,
                params=params,
                json=rows,
                timeout=60,
            )
            resp.raise_for_status()
            return len(rows)
        except requests.RequestException as exc:
            print(f"    [RETRY {attempt}/{MAX_RETRIES}] Batch upsert failed: {exc}")
            # Log response body on 4xx errors to help diagnose schema mismatches
            if hasattr(exc, "response") and exc.response is not None:
                status = exc.response.status_code
                if 400 <= status < 500:
                    body = exc.response.text[:500]
                    print(f"      Response ({status}): {body}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)  # exponential backoff
    return 0


# ── Stale product cleanup ────────────────────────────────────────────────────


def delete_stale_products(
    existing_map: dict[str, ProductData],
    seen_urls: set[str],
) -> int:
    """Delete products in this source that were NOT seen this run.

    Uses the already-fetched ``existing_map`` to avoid an extra DB query.
    Returns the number of deleted rows.
    """
    stale_ids = [
        p.id
        for url, p in existing_map.items()
        if url not in seen_urls
    ]
    if not stale_ids:
        return 0

    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    delete_headers = {**_HEADERS, "Prefer": "return=minimal"}

    deleted_total = 0
    # Delete in batches of 100 (URL-length safe)
    for i in range(0, len(stale_ids), 100):
        batch = stale_ids[i:i + 100]
        # Use PostgREST `in` operator on the primary key
        in_list = ",".join(batch)
        params = {"id": f"in.({in_list})"}
        try:
            resp = _session.delete(url, headers=delete_headers, params=params, timeout=30)
            resp.raise_for_status()
            deleted_total += len(batch)
        except requests.RequestException as exc:
            print(f"  [WARN] Failed to delete stale batch: {exc}")

    return deleted_total
