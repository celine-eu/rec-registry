from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class TimeSeries(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "timeseries"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)
    observed_asset_id: Mapped[str | None] = mapped_column(ForeignKey("asset.id", ondelete="SET NULL"), nullable=True, index=True)

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    observed_entity_kind: Mapped[str] = mapped_column(String(50), nullable=False, default="asset")  # asset|community

    community = relationship("Community", back_populates="timeseries")
    observed_entity = relationship("Asset", back_populates="timeseries")
