from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Community(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "community"

    # URL path component (used in API as /communities/{key})
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    participants = relationship("Participant", back_populates="community", cascade="all, delete-orphan")
    memberships = relationship("Membership", back_populates="community", cascade="all, delete-orphan")
    sites = relationship("Site", back_populates="community", cascade="all, delete-orphan")
    meters = relationship("Meter", back_populates="community", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="community", cascade="all, delete-orphan")
    tariffs = relationship("Tariff", back_populates="community", cascade="all, delete-orphan")
    timeseries = relationship("TimeSeries", back_populates="community", cascade="all, delete-orphan")
    topology_edges = relationship("TopologyEdge", back_populates="community", cascade="all, delete-orphan")
