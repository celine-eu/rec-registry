from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Meter(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "meter"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("site.id", ondelete="SET NULL"), nullable=True, index=True)

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    pod_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    community = relationship("Community", back_populates="meters")
    site = relationship("Site", back_populates="meters")
    assets = relationship("Asset", back_populates="meter")
