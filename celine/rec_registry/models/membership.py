from __future__ import annotations
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Membership(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "membership"

    community_id: Mapped[str] = mapped_column(
        ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participant.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(80), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_weight: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    community = relationship("Community", back_populates="memberships")
    participant = relationship("Participant", back_populates="memberships")
