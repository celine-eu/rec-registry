from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class Participant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "participant"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(50), nullable=True)  # person|organization|public_body
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(250), nullable=True)

    community = relationship("Community", back_populates="participants")
    memberships = relationship("Membership", back_populates="participant", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="owner")
