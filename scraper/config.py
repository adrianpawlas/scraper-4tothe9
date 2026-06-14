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

# ── Scraper tuning ──────────────────────────────────────────────────────────
BATCH_SIZE = 50
HF_DELAY_SECONDS = 0.5
SHOPIFY_DELAY_SECONDS = 0.75  # delay between Shopify JSON API calls to avoid 429 rate limits
MAX_RETRIES = 3
SCROLL_PAUSE_SECONDS = 2.0
MAX_SCROLL_ATTEMPTS = 30


# ── Validation ───────────────────────────────────────────────────────────────

REQUIRED_ENV_VARS = {
    "SUPABASE_URL": "Supabase project URL",
    "SUPABASE_KEY": "Supabase service role key",
}


def validate_config():
    """Raise ``ValueError`` if any required env var is missing or empty."""
    missing = []
    for var, description in REQUIRED_ENV_VARS.items():
        val = os.environ.get(var, "")
        if not val:
            missing.append(f"  {var}: {description}")
    if missing:
        raise ValueError(
            "Missing required environment variables:\n"
            + "\n".join(missing)
            + "\n\nSet these as GitHub Actions secrets or in a .env file."
        )
