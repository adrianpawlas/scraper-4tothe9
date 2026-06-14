"""Pydantic-style data models for scraped product data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from scraper.config import SOURCE


@dataclass
class ProductData:
    """Normalised product record ready for DB upsert."""

    id: str
    source: str = SOURCE
    product_url: str = ""
    affiliate_url: Optional[str] = None
    image_url: str = ""
    back_image_url: Optional[str] = None
    brand: str = "4tothe9"
    title: str = ""
    description: Optional[str] = None
    category: Optional[str] = None
    gender: Optional[str] = None
    price: Optional[str] = None
    sale: Optional[str] = None
    metadata: Optional[str] = None
    size: Optional[str] = None
    second_hand: bool = False
    country: Optional[str] = None
    tags: Optional[list[str]] = None
    additional_images: Optional[str] = None
    other: Optional[str] = None
    image_embedding: Optional[list[float]] = None
    back_image_embedding: Optional[list[float]] = None
    info_embedding: Optional[list[float]] = None

    # Internal tracking (not sent to DB)
    seen_this_run: bool = True
    embedding_version: int = field(default=2, compare=False)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def compute_id(source: str, product_url: str) -> str:
        raw = f"{source}::{product_url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def to_upsert_dict(self) -> dict:
        """Return a flat dict for the Supabase upsert row."""
        d: dict = {
            "id": self.id,
            "source": self.source,
            "product_url": self.product_url,
            "affiliate_url": self.affiliate_url,
            "image_url": self.image_url,
            "back_image_url": self.back_image_url,
            "brand": self.brand,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "gender": self.gender,
            "price": self.price,
            "sale": self.sale,
            "metadata": self.metadata,
            "size": self.size,
            "second_hand": self.second_hand,
            "country": self.country,
            "tags": self.tags,
            "additional_images": self.additional_images,
            "other": self.other,
        }
        # Only include embeddings if they are set
        if self.image_embedding is not None:
            d["image_embedding"] = self.image_embedding
            d["embedding_version"] = self.embedding_version
        if self.back_image_embedding is not None:
            d["back_image_embedding"] = self.back_image_embedding
        if self.info_embedding is not None:
            d["info_embedding"] = self.info_embedding
        return d

    @staticmethod
    def from_db_row(row: dict) -> ProductData:
        """Reconstruct a ProductData from a DB row dict (for comparison)."""
        return ProductData(
            id=row.get("id", ""),
            source=row.get("source", SOURCE),
            product_url=row.get("product_url", ""),
            affiliate_url=row.get("affiliate_url"),
            image_url=row.get("image_url", ""),
            back_image_url=row.get("back_image_url"),
            brand=row.get("brand", "4tothe9"),
            title=row.get("title", ""),
            description=row.get("description"),
            category=row.get("category"),
            gender=row.get("gender"),
            price=row.get("price"),
            sale=row.get("sale"),
            metadata=row.get("metadata"),
            size=row.get("size"),
            second_hand=row.get("second_hand", False),
            country=row.get("country"),
            tags=row.get("tags"),
            additional_images=row.get("additional_images"),
            other=row.get("other"),
        )

    # ── Comparator ──────────────────────────────────────────────────────────

    TEXT_FIELDS = {"title", "description", "category", "gender", "price", "sale", "metadata"}

    def text_fields_changed(self, other: ProductData) -> bool:
        """Check whether any text fields that affect `info_embedding` differ."""
        for f in self.TEXT_FIELDS:
            if getattr(self, f) != getattr(other, f):
                return True
        return False

    def scalar_fields_changed(self, other: ProductData) -> bool:
        """Check whether any scraped (non-embedding, non-tracking) field differs."""
        compare_keys = {
            "affiliate_url", "image_url", "back_image_url", "title",
            "description", "category", "gender", "price", "sale",
            "metadata", "size", "country", "tags", "additional_images",
            "other", "brand", "second_hand",
        }
        for k in compare_keys:
            if getattr(self, k) != getattr(other, k):
                return True
        return False

    def build_info_text(self) -> str:
        """Build a rich text representation for info_embedding."""
        parts = [self.title or ""]
        if self.description:
            parts.append(self.description)
        if self.category:
            parts.append(f"Category: {self.category}")
        if self.gender:
            parts.append(f"Gender: {self.gender}")
        if self.price:
            parts.append(f"Price: {self.price}")
        if self.sale:
            parts.append(f"Sale: {self.sale}")
        if self.metadata:
            try:
                meta = json.loads(self.metadata)
                meta_str = "; ".join(
                    f"{k}: {v}" for k, v in meta.items() if v
                )
                if meta_str:
                    parts.append(meta_str)
            except (json.JSONDecodeError, TypeError):
                parts.append(str(self.metadata))
        if self.size:
            parts.append(f"Size: {self.size}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return " | ".join(p for p in parts if p)
