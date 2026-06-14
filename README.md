# 4tothe9 Product Scraper

Production-grade Shopify product scraper for the [4tothe9](https://4tothe9.com) fashion store. Scrapes every product, generates SigLIP image/text embeddings, and upserts into Finds' Supabase `products` table with smart diffing, batching, and stale cleanup.

## Features

- **Full catalog coverage** – scrapes across 9 collection pages (accessories, jeans, cargos, sweats, hoodies, sweaters, zip-ups, tees, shirts)
- **Shopify JSON API** – fetches structured product data natively (no fragile HTML parsing)
- **Playwright scrolling** – handles lazy-loaded/infinite-scroll category pages
- **SigLIP embeddings** – 768‑dim L2‑normalised image + text vectors via HuggingFace Inference Endpoint (`google/siglip-base-patch16-384`)
- **Smart upsert** – deep‑compares each product against the existing DB row; skips unchanged products entirely (no wasted HF calls or DB writes)
- **Batch upserts** – 50 products per Supabase request
- **Stale cleanup** – deletes products no longer found on the store
- **Error resilience** – per‑product error isolation, retry with exponential backoff, failed‑product log artifact
- **GitHub Actions schedule** – runs automatically every Wednesday at 7:30 AM UTC

## Architecture

```
scraper/
├── __init__.py
├── __main__.py          # python -m scraper
├── config.py            # Env‑based configuration
├── models.py            # ProductData dataclass + diff helpers
├── shopify_scraper.py   # Playwright page discovery + Shopify JSON parsing
├── embeddings.py        # HF SigLIP endpoint image/text embedding
├── db.py                # Supabase read / upsert / cleanup
└── run.py               # Orchestrator (entry point)
```

## Prerequisites

- Python 3.12+
- Playwright system dependencies (installed automatically in CI; for local: `playwright install chromium`)
- Supabase project with a `products` table (see schema below)
- HuggingFace Inference Endpoint serving `google/siglip-base-patch16-384`

## Setup

```bash
# Clone
git clone https://github.com/adrianpawlas/scraper-4tothe9.git
cd scraper-4tothe9

# Environment
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_KEY, HUGGING_FACE_ENDPOINT_URL, HUGGING_FACE_ACCESS_TOKEN

# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run
python -m scraper
```

### GitHub Secrets

For CI (`Settings → Secrets and variables → Actions`):

| Secret                        | Description                          |
|-------------------------------|--------------------------------------|
| `SUPABASE_URL`                | Supabase project URL                 |
| `SUPABASE_KEY`                | Supabase service‑role key            |
| `HUGGING_FACE_ENDPOINT_URL`   | HF Inference Endpoint URL            |
| `HUGGING_FACE_ACCESS_TOKEN`   | HF API token                         |

## Database Schema

The scraper writes to `public.products`. Key columns:

| Column               | Type              | Notes                                     |
|----------------------|-------------------|-------------------------------------------|
| `id`                 | `text PK`         | SHA‑256(source + product_url) → 32 chars  |
| `source`             | `text NOT NULL`   | `scraper-49`                              |
| `product_url`        | `text NOT NULL`   | Canonical product page URL                |
| `image_url`          | `text NOT NULL`   | Primary product image                     |
| `image_embedding`    | `vector(768)`     | SigLIP front‑image embedding              |
| `info_embedding`     | `vector(768)`     | SigLIP text embedding (title+desc+meta)   |
| `title` / `description` / `category` / `gender` / `price` / `sale` | ... | Standard product fields |
| `metadata`           | `text`            | JSON blob (sizes, SKU, composition, etc.) |
| `tags`               | `text[]`          | Shopify tags                              |
| `additional_images`  | `text`            | Comma‑separated gallery URLs              |

Unique constraint: `(source, product_url)`.

## Output

At the end of every run the scraper prints:

```
====================================================================
  RUN SUMMARY
====================================================================
  New products added:            X
  Products updated:              X
  Products unchanged (skipped):  X
  Front embeddings generated:    X
  Back embeddings generated:     0 (none — brand has no back shots)
  Text embeddings generated:     X
  Stale products deleted:        X
  Errors / failures:             X
  Total time:                    X.Xs
====================================================================
```

Failed products are logged to `logs/failed_products_<timestamp>.log` and uploaded as a CI artifact.
