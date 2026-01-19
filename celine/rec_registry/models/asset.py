from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Asset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "asset"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("site.id", ondelete="SET NULL"), nullable=True, index=True)
    meter_id: Mapped[str | None] = mapped_column(ForeignKey("meter.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("participant.id", ondelete="SET NULL"), nullable=True, index=True)

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PV|BATTERY|EVSE|LOAD|METER|...

    rated_power_kw: Mapped[object | None] = mapped_column(Numeric(14, 6), nullable=True)
    rated_energy_kwh: Mapped[object | None] = mapped_column(Numeric(14, 6), nullable=True)

    community = relationship("Community", back_populates="assets")
    site = relationship("Site", back_populates="assets")
    meter = relationship("Meter", back_populates="assets")
    owner = relationship("Participant", back_populates="assets")
    timeseries = relationship("TimeSeries", back_populates="observed_entity")
