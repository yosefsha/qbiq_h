"""SQLAlchemy ORM models for the catalogue schema.

These are persistence-layer models only — they intentionally do not import or
define the domain dataclasses (BE-02 owns those). Mapping between the two
layers belongs to the repository implementation (BE-04), not here.

Prices are stored as integer minor units (`price_minor`) plus a `currency`
code, never as a float or a numeric-with-scale column, per ADR-003.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Category(Base):
    """The kind of digital good a Product is. Every Product has exactly one."""

    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    """A digital good offered for sale — an e-book, a software licence, or an
    online course."""

    __tablename__ = "product"
    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="ck_product_price_minor_non_negative"),
        Index("ix_product_category_id", "category_id"),
        Index("ix_product_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Integer minor units (e.g. cents). Never a float or numeric-with-scale
    # column — see ADR-003.
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    short_description: Mapped[str] = mapped_column(String(300), nullable=False)
    long_description: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(String(500), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT"), nullable=False
    )

    category: Mapped["Category"] = relationship(back_populates="products")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class Review(Base):
    """A shopper's written verdict on a Product."""

    __tablename__ = "review"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating_range"),
        Index("ix_review_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["Product"] = relationship(back_populates="reviews")
