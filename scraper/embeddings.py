"""Embedding generation via HuggingFace Inference Endpoint (SigLIP)."""

from __future__ import annotations

import io
import json
import time
from typing import Optional

import requests
from PIL import Image

from scraper.config import HF_ENDPOINT_URL, HF_ACCESS_TOKEN, HF_DELAY_SECONDS

_session = requests.Session()
_last_call: float = 0.0


def _rate_limit():
    """Enforce 0.5 s gap between consecutive HF API calls."""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < HF_DELAY_SECONDS:
        time.sleep(HF_DELAY_SECONDS - elapsed)
    _last_call = time.time()


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {HF_ACCESS_TOKEN}",
    }


def embed_image(image_url: str) -> Optional[list[float]]:
    """Download an image and return its 768-dim L2-normalised embedding.

    Returns None on any error so the caller can continue gracefully.
    """
    try:
        resp = _session.get(image_url, timeout=30)
        resp.raise_for_status()
        image_bytes = resp.content
    except requests.RequestException as exc:
        print(f"  [WARN] Failed to download image {image_url[:80]}: {exc}")
        return None

    _rate_limit()
    try:
        # The HF Endpoint for SigLIP expects raw image bytes.
        r = _session.post(
            HF_ENDPOINT_URL,
            headers={**_headers(), "Content-Type": "application/octet-stream"},
            data=image_bytes,
            timeout=60,
        )
        r.raise_for_status()
        emb = r.json()
        # HF sometimes wraps the vector in an extra array
        if isinstance(emb, list) and emb and isinstance(emb[0], list):
            emb = emb[0]
        if isinstance(emb, list) and len(emb) == 768:
            return _l2_normalize(emb)
        print(f"  [WARN] Unexpected embedding shape: {len(emb) if isinstance(emb, list) else type(emb)}")
        return None
    except requests.RequestException as exc:
        print(f"  [WARN] HF image embedding failed for {image_url[:80]}: {exc}")
        return None
    except (json.JSONDecodeError, TypeError, IndexError) as exc:
        print(f"  [WARN] HF image embedding parse error: {exc}")
        return None


def embed_text(text: str) -> Optional[list[float]]:
    """Return 768-dim L2-normalised text embedding via the same SigLIP endpoint.

    Returns None on error.
    """
    if not text.strip():
        return None

    _rate_limit()
    try:
        r = _session.post(
            HF_ENDPOINT_URL,
            headers={**_headers(), "Content-Type": "application/json"},
            json={"inputs": text},
            timeout=60,
        )
        r.raise_for_status()
        emb = r.json()
        if isinstance(emb, list) and emb and isinstance(emb[0], list):
            emb = emb[0]
        if isinstance(emb, list) and len(emb) == 768:
            return _l2_normalize(emb)
        print(f"  [WARN] Unexpected text embedding shape: {len(emb) if isinstance(emb, list) else type(emb)}")
        return None
    except requests.RequestException as exc:
        print(f"  [WARN] HF text embedding failed: {exc}")
        return None
    except (json.JSONDecodeError, TypeError, IndexError) as exc:
        print(f"  [WARN] HF text embedding parse error: {exc}")
        return None


def _l2_normalize(v: list[float]) -> list[float]:
    """L2-normalise a vector in-place."""
    norm = sum(x * x for x in v) ** 0.5
    if norm == 0:
        return v
    return [x / norm for x in v]
