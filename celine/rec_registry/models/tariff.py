from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Tariff(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tariff"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    community = relationship("Community", back_populates="tariffs")
