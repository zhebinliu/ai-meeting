"""Meeting template SQLAlchemy model.

Templates capture user-evolved preferences for meeting minutes structure,
formatting, and style. The active template is injected into the AI prompt
during minutes generation.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from backend.database import Base


class MeetingTemplate(Base):
    """A versioned template that encodes meeting minutes preferences."""

    __tablename__ = "meeting_templates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(256), nullable=False, default="默认模板")
    description: str = Column(Text, nullable=True, default="")
    # JSON: defines expected fields, types, order, required flags
    schema_structure: str = Column(Text, nullable=True, default="")
    # Natural-language formatting rules injected into the system prompt
    format_requirements: str = Column(Text, nullable=True, default="")
    # Style preferences (tone, detail level, focus areas)
    style_preferences: str = Column(Text, nullable=True, default="")
    # Version number, incremented on each evolution
    version: int = Column(Integer, nullable=False, default=1)
    # Whether this template is currently active
    is_active: bool = Column(Boolean, nullable=False, default=False)
    # JSON list of local meeting IDs that contributed to this template
    source_meeting_ids: str = Column(Text, nullable=True, default="[]")
    # JSON list of KB document refs that contributed to this template
    source_kb_doc_refs: str = Column(Text, nullable=True, default="[]")
    # How this template was created: initial / user_edit / kb_analysis / combined
    evolution_method: str = Column(String(64), nullable=False, default="initial")
    # LLM-generated changelog for this version
    change_log: str = Column(Text, nullable=True, default="")
    created_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<MeetingTemplate id={self.id} name={self.name!r} "
            f"version={self.version} active={self.is_active}>"
        )
