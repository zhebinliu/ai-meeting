"""Meeting SQLAlchemy model."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.database import Base


class Meeting(Base):
    """Represents a single recorded meeting session."""

    __tablename__ = "meetings"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    title: str = Column(String(256), nullable=False, default="Untitled Meeting")
    start_time: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time: datetime | None = Column(DateTime, nullable=True)
    raw_transcript: str = Column(Text, nullable=True, default="")
    polished_transcript: str = Column(Text, nullable=True, default="")
    meeting_minutes: str = Column(Text, nullable=True, default="")
    status: str = Column(String(32), nullable=False, default="recording")
    asr_engine: str | None = Column(String(32), nullable=True, default=None)
    total_chunks: int = Column(Integer, nullable=False, default=0)
    done_chunks: int = Column(Integer, nullable=False, default=0)
    bitable_app_token: str | None = Column(String(128), nullable=True, default=None)
    feishu_url: str | None = Column(Text, nullable=True, default=None)
    created_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Meeting id={self.id} title={self.title!r} status={self.status!r}>"
