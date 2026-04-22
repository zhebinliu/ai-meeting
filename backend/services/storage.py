"""SQLite-backed storage service.

Provides a thin data-access layer over SQLAlchemy models so that route
handlers stay focused on HTTP concerns.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.meeting import Meeting
from backend.models.requirement import Requirement

logger = logging.getLogger(__name__)


class StorageService:
    """Repository-style helper for common database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    async def create_meeting(self, title: str = "Untitled Meeting") -> Meeting:
        """Insert a new meeting and return the persisted instance."""
        meeting = Meeting(title=title, start_time=datetime.utcnow())
        self._session.add(meeting)
        await self._session.commit()
        await self._session.refresh(meeting)
        logger.info("Storage: created meeting id=%s", meeting.id)
        return meeting

    async def get_meeting(self, meeting_id: int) -> Meeting | None:
        """Fetch a meeting by primary key."""
        return await self._session.get(Meeting, meeting_id)

    async def list_meetings(self, limit: int = 100, offset: int = 0) -> list[Meeting]:
        """Return meetings ordered by creation time descending."""
        result = await self._session.execute(
            select(Meeting).order_by(Meeting.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def update_meeting(self, meeting: Meeting, **fields: object) -> Meeting:
        """Apply *fields* to a meeting and commit."""
        for key, value in fields.items():
            setattr(meeting, key, value)
        await self._session.commit()
        await self._session.refresh(meeting)
        logger.info("Storage: updated meeting id=%s fields=%s", meeting.id, list(fields.keys()))
        return meeting

    # ------------------------------------------------------------------
    # Requirements
    # ------------------------------------------------------------------

    async def create_requirement(
        self,
        meeting_id: int,
        req_id: str,
        module: str,
        description: str,
        priority: str = "P2",
        source: str = "",
        speaker: str = "",
    ) -> Requirement:
        """Insert a new requirement linked to a meeting."""
        req = Requirement(
            meeting_id=meeting_id,
            req_id=req_id,
            module=module,
            description=description,
            priority=priority,
            source=source,
            speaker=speaker,
        )
        self._session.add(req)
        await self._session.commit()
        await self._session.refresh(req)
        logger.info("Storage: created requirement id=%s req_id=%s", req.id, req.req_id)
        return req

    async def list_requirements_for_meeting(self, meeting_id: int) -> list[Requirement]:
        """Return all requirements for a given meeting."""
        result = await self._session.execute(
            select(Requirement)
            .where(Requirement.meeting_id == meeting_id)
            .order_by(Requirement.id)
        )
        return list(result.scalars().all())
