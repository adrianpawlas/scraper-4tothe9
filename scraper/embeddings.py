"""Embedding generation using google/siglip-base-patch16-384 (local model).

Runs the SigLIP model locally via the ``transformers`` library — no external API calls.
Model is loaded once and reused across all products.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
import torch
from PIL import Image
from transformers import SiglipProcessor, SiglipModel

from scraper.config import HF_DELAY_SECONDS

MODEL_NAME = "google/siglip-base-patch16-384"
EMBEDDING_DIM = 768

_model: Optional[SiglipModel] = None
_processor: Optional[SiglipProcessor] = None
_device: str = "cpu"
_last_call: float = 0.0


def _lazy_init():
    """Load the model on first use (lazy initialisation)."""
    global _model, _processor, _device
    if _model is not None:
        return
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"    [INFO] Loading SigLIP model on {_device} ...")
    _processor = SiglipProcessor.from_pretrained(MODEL_NAME)
    _model = SiglipModel.from_pretrained(MODEL_NAME).to(_device)
    _model.eval()
    print(f"    [INFO] SigLIP model loaded successfully (device={_device}).")


def _rate_limit():
    """Enforce a minimum gap between consecutive calls to avoid overwhelming CPU/GPU."""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < HF_DELAY_SECONDS:
        time.sleep(HF_DELAY_SECONDS - elapsed)
    _last_call = time.time()


def embed_image(image: Image.Image) -> Optional[list[float]]:
    """Return a 768-dim L2-normalised image embedding.

    Parameters
    ----------
    image : PIL.Image.Image
        The already-opened image to embed.

    Returns
    -------
    list[float] or None
        768-dimensional L2-normalised embedding, or None on failure.
    """
    _lazy_init()
    _rate_limit()
    try:
        inputs = _processor(images=image, return_tensors="pt").to(_device)
        with torch.no_grad():
            outputs = _model.get_image_features(**inputs)
        if hasattr(outputs, "pooler_output"):
            emb_tensor = outputs.pooler_output
        else:
            emb_tensor = outputs[0]
        embedding = emb_tensor.cpu().numpy().flatten()
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        if len(embedding) == EMBEDDING_DIM:
            return embedding.tolist()
        print(f"    [WARN] Unexpected image embedding shape: {len(embedding)}")
        return None
    except Exception as exc:
        print(f"    [WARN] Image embedding failed: {exc}")
        return None


def embed_text(text: str) -> Optional[list[float]]:
    """Return a 768-dim L2-normalised text embedding.

    SigLIP text model has ``max_position_embeddings=64`` tokens, so input
    is truncated and padded accordingly.

    Parameters
    ----------
    text : str
        The text to embed.

    Returns
    -------
    list[float] or None
        768-dimensional L2-normalised embedding, or None on failure.
    """
    if not text.strip():
        return None

    _lazy_init()
    _rate_limit()
    try:
        inputs = _processor(
            text=text,
            padding="max_length",
            max_length=64,
            truncation=True,
            return_tensors="pt",
        ).to(_device)
        with torch.no_grad():
            outputs = _model.get_text_features(**inputs)
        if hasattr(outputs, "pooler_output"):
            emb_tensor = outputs.pooler_output
        else:
            emb_tensor = outputs[0]
        embedding = emb_tensor.cpu().numpy().flatten()
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        if len(embedding) == EMBEDDING_DIM:
            return embedding.tolist()
        print(f"    [WARN] Unexpected text embedding shape: {len(embedding)}")
        return None
    except Exception as exc:
        print(f"    [WARN] Text embedding failed: {exc}")
        return None
