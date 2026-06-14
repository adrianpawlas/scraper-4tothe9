"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Brand constants ──────────────────────────────────────────────────────────
BRAND_NAME = "4tothe9"
SOURCE = "scraper-49"
BRAND_COLUMN = "4tothe9"
SECOND_HAND = False

# ── Category URLs to scrape ──────────────────────────────────────────────────
CATEGORY_URLS = [
    "https://4tothe9.com/collections/accessories",
    "https://4tothe9.com/collections/jeans",
    "https://4tothe9.com/collections/cargos-1",
    "https://4tothe9.com/collections/sweats",
    "https://4tothe9.com/collections/hoodies",
    "https://4tothe9.com/collections/sweaters",
    "https://4tothe9.com/collections/zip-ups-1",
    "https://4tothe9.com/collections/vintage-tees",
    "https://4tothe9.com/collections/shirts",
]

# Category label mapping (collection handle -> display category)
CATEGORY_MAP = {
    "accessories": "Accessories",
    "jeans": "Jeans",
    "cargos-1": "Cargos",
    "sweats": "Sweats",
    "hoodies": "Hoodies",
    "sweaters": "Sweaters",
    "zip-ups-1": "Zip-ups",
    "vintage-tees": "Vintage Tees",
    "shirts": "Shirts",
}

# ── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# ── HuggingFace Inference Endpoint ──────────────────────────────────────────
HF_ENDPOINT_URL = os.environ["HUGGING_FACE_ENDPOINT_URL"]
HF_ACCESS_TOKEN = os.environ["HUGGING_FACE_ACCESS_TOKEN"]

# ── Scraper tuning ──────────────────────────────────────────────────────────
BATCH_SIZE = 50
HF_DELAY_SECONDS = 0.5
MAX_RETRIES = 3
SCROLL_PAUSE_SECONDS = 2.0
MAX_SCROLL_ATTEMPTS = 30
