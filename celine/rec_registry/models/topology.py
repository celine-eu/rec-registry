from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class TopologyEdge(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "topology_edge"

    community_id: Mapped[str] = mapped_column(ForeignKey("community.id", ondelete="CASCADE"), nullable=False, index=True)

    src_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    src_type: Mapped[str] = mapped_column(String(50), nullable=False)  # community|participant|membership|site|meter|asset|tariff|timeseries
    predicate: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dst_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dst_type: Mapped[str] = mapped_column(String(50), nullable=False)

    community = relationship("Community", back_populates="topology_edges")
