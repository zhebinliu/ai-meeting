"""Requirement SQLAlchemy model."""

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.database import Base


class Requirement(Base):
    """A single requirement extracted from a meeting transcript."""

    __tablename__ = "requirements"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id: int = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    req_id: str = Column(String(32), nullable=False, default="REQ-001")
    module: str = Column(String(128), nullable=False, default="")
    description: str = Column(Text, nullable=False, default="")
    priority: str = Column(String(8), nullable=False, default="P2")
    source: str = Column(Text, nullable=True, default="")
    speaker: str = Column(String(128), nullable=True, default="")
    status: str = Column(String(32), nullable=False, default="待确认")
    created_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} req_id={self.req_id!r} priority={self.priority!r}>"
