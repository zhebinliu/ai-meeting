from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession


from backend.config import settings
from backend.database import get_session
from backend.models.meeting import Meeting
from backend.models.requirement import Requirement
from backend.services.ai.pipeline import MeetingAIPipeline
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MeetingCreate(BaseModel):
    """Payload for creating a new meeting."""
    title: str = Field(default="Untitled Meeting", max_length=256)


class MeetingFromTextCreate(BaseModel):
    """Payload for creating a meeting directly from pasted text.

    The transcript is taken as-is (no ASR required) and sent through the
    standard AI pipeline to produce polished transcript, structured
    minutes, extracted requirements, and a stakeholder graph.

    Optional ``kb_project_id`` ties the meeting to a KB project so that
    during the same pipeline run we fetch project documents and merge
    people mentioned there into the stakeholder graph.
    """
    title: str = Field(default="Untitled Meeting", max_length=256)
    transcript: str = Field(min_length=1, max_length=200000)
    kb_project_id: Optional[str] = Field(
        default=None,
        description="Optional KB project UUID; enables KB doc enrichment for stakeholders.",
    )
    kb_project_name: Optional[str] = Field(
        default=None,
        description="Optional display name; resolved from KB if omitted but id is set.",
    )


class MeetingUpdate(BaseModel):
    """Partial update payload for a meeting."""
    title: Optional[str] = None
    end_time: Optional[datetime] = None
    raw_transcript: Optional[str] = None
    polished_transcript: Optional[str] = None
    meeting_minutes: Optional[str] = None
    status: Optional[str] = None
    total_chunks: Optional[int] = None
    done_chunks: Optional[int] = None


class MeetingOut(BaseModel):
    """Serialised meeting response."""
    id: int
    title: str
    start_time: datetime
    end_time: Optional[datetime]
    raw_transcript: str
    polished_transcript: str
    meeting_minutes: str
    status: str
    total_chunks: int = 0
    done_chunks: int = 0
    feishu_url: Optional[str] = None
    bitable_url: Optional[str] = None
    kb_doc_id: Optional[str] = None
    kb_url: Optional[str] = None
    kb_synced_at: Optional[datetime] = None
    # Knowledge-Base project association + stakeholder graph sync state
    kb_project_id: Optional[str] = None
    kb_project_name: Optional[str] = None
    stakeholder_map: Optional[str] = None
    stakeholder_kb_doc_id: Optional[str] = None
    stakeholder_kb_url: Optional[str] = None
    stakeholder_kb_synced_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RequirementOut(BaseModel):
    """Serialised requirement response."""
    id: int
    meeting_id: int
    req_id: str
    module: str
    description: str
    priority: str
    source: str
    speaker: str
    status: str
    asr_engine: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    db: AsyncSession = Depends(get_session),
) -> Meeting:
    """Create a new meeting record."""
    meeting = Meeting(title=payload.title, start_time=datetime.utcnow())
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    logger.info("Created meeting id=%s title=%r", meeting.id, meeting.title)
    return meeting


async def run_text_to_minutes(meeting_id: int) -> None:
    """Background task: run full AI pipeline over a text-only meeting.

    Saves polished transcript, structured minutes, requirements and the
    stakeholder graph back to the DB. On failure, marks meeting status
    as ``failed``.
    """
    from backend.database import async_session_factory

    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or not (meeting.raw_transcript or "").strip():
            return

        # KB project docs, or — when no project — excerpts from other
        # completed meetings in this system for internal stakeholder context.
        kb_docs = await _stakeholder_reference_docs(
            meeting_id, meeting.kb_project_id, db
        )

        try:
            pipeline = MeetingAIPipeline(
                openai_api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                base_url=settings.OPENAI_BASE_URL or None,
            )
            result = await pipeline.process(
                raw_transcript=meeting.raw_transcript,
                meeting_title=meeting.title,
                meeting_id=meeting_id,
                kb_docs=kb_docs,
            )

            meeting.polished_transcript = result.get("polished_transcript", "")
            meeting.meeting_minutes = json.dumps(
                result.get("meeting_minutes", {}), ensure_ascii=False
            )
            meeting.stakeholder_map = json.dumps(
                result.get("stakeholder_map", {"stakeholders": [], "relations": []}),
                ensure_ascii=False,
            )
            meeting.end_time = meeting.end_time or datetime.utcnow()
            meeting.status = "completed"
            await db.commit()

            # Replace existing requirements (idempotent if user retriggers).
            await db.execute(
                sql_delete(Requirement).where(Requirement.meeting_id == meeting_id)
            )
            for idx, req in enumerate(result.get("requirements", [])):
                db.add(Requirement(
                    meeting_id=meeting_id,
                    req_id=req.get("id", f"REQ-{idx + 1:03d}"),
                    module=req.get("module", ""),
                    description=req.get("description", ""),
                    priority=req.get("priority", "P2"),
                    source=req.get("source", ""),
                    speaker=req.get("speaker", ""),
                    status="待确认",
                ))
            await db.commit()
            logger.info("Text-ingest meeting %s: pipeline complete", meeting_id)
        except Exception:
            logger.exception("Text-ingest pipeline failed for meeting %s", meeting_id)
            meeting.status = "failed"
            await db.commit()


@router.post(
    "/from-text",
    response_model=MeetingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_meeting_from_text(
    payload: MeetingFromTextCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> Meeting:
    """Create a meeting directly from pasted transcript text.

    The transcript is stored as ``raw_transcript`` and the AI pipeline is
    scheduled in the background.  The new meeting is returned immediately
    so the client can navigate to its detail page and poll progress.
    """
    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript must not be empty")

    kb_pid = (payload.kb_project_id or "").strip() or None
    kb_pname = (payload.kb_project_name or "").strip() or None
    if kb_pid and not kb_pname:
        try:
            from backend.services.kb_client import KBClient, KBNotConfigured, KBError

            try:
                for p in await KBClient().list_projects():
                    if p.get("id") == kb_pid:
                        kb_pname = p.get("name") or kb_pid
                        break
            except (KBNotConfigured, KBError):
                pass
        except Exception:  # noqa: BLE001
            pass
        if not kb_pname:
            kb_pname = kb_pid

    meeting = Meeting(
        title=payload.title or "Untitled Meeting",
        start_time=datetime.utcnow(),
        raw_transcript=transcript,
        status="processing",
        asr_engine="text",
        kb_project_id=kb_pid,
        kb_project_name=kb_pname,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)

    background_tasks.add_task(run_text_to_minutes, meeting.id)
    logger.info(
        "Created text-ingest meeting id=%s (%d chars)",
        meeting.id,
        len(transcript),
    )
    return meeting


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    db: AsyncSession = Depends(get_session),
) -> list[Meeting]:
    """Return all meetings ordered by creation time descending."""
    result = await db.execute(
        select(Meeting).order_by(Meeting.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve a single meeting by ID.

    Returns meeting data with ``meeting_minutes`` parsed from JSON string
    to a dict, and a ``minutes`` alias for frontend convenience.
    Also includes the related ``requirements`` list.
    """
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # --- Parse meeting_minutes JSON string to dict ---
    minutes_obj = None
    if meeting.meeting_minutes:
        try:
            minutes_obj = json.loads(meeting.meeting_minutes)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse meeting_minutes JSON for meeting %s", meeting_id
            )
            minutes_obj = None

    # --- Fetch related requirements ---
    result = await db.execute(
        select(Requirement)
        .where(Requirement.meeting_id == meeting_id)
        .order_by(Requirement.id)
    )
    requirements = [
        {
            "id": r.req_id,
            "module": r.module,
            "description": r.description,
            "priority": r.priority,
            "source": r.source,
            "speaker": r.speaker,
            "status": r.status,
        }
        for r in result.scalars().all()
    ]

    # --- Parse stakeholder graph JSON to dict ---
    stakeholder_obj = None
    if meeting.stakeholder_map:
        try:
            stakeholder_obj = json.loads(meeting.stakeholder_map)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse stakeholder_map JSON for meeting %s", meeting_id
            )
            stakeholder_obj = None

    return {
        "id": meeting.id,
        "title": meeting.title,
        "start_time": meeting.start_time,
        "end_time": meeting.end_time,
        "raw_transcript": meeting.raw_transcript or "",
        "polished_transcript": meeting.polished_transcript or "",
        "meeting_minutes": meeting.meeting_minutes or "",
        "minutes": minutes_obj,  # Parsed dict for frontend
        "status": meeting.status,
        "total_chunks": meeting.total_chunks,
        "done_chunks": meeting.done_chunks,
        "feishu_url": meeting.feishu_url,
        "bitable_url": f"https://feishu.cn/base/{meeting.bitable_app_token}" if meeting.bitable_app_token else None,
        "kb_doc_id": meeting.kb_doc_id,
        "kb_url": meeting.kb_url,
        "kb_synced_at": meeting.kb_synced_at,
        "kb_project_id": meeting.kb_project_id,
        "kb_project_name": meeting.kb_project_name,
        "stakeholders": stakeholder_obj,
        "stakeholder_map": meeting.stakeholder_map or "",
        "stakeholder_kb_doc_id": meeting.stakeholder_kb_doc_id,
        "stakeholder_kb_url": meeting.stakeholder_kb_url,
        "stakeholder_kb_synced_at": meeting.stakeholder_kb_synced_at,
        "created_at": meeting.created_at,
        "requirements": requirements,
    }


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: int,
    payload: MeetingUpdate,
    db: AsyncSession = Depends(get_session),
) -> Meeting:
    """Partially update a meeting record."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(meeting, field, value)

    await db.commit()
    await db.refresh(meeting)
    logger.info("Updated meeting id=%s fields=%s", meeting_id, list(update_data.keys()))
    return meeting


@router.get("/{meeting_id}/requirements", response_model=list[RequirementOut])
async def list_meeting_requirements(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> list[Requirement]:
    """List all requirements extracted from a specific meeting."""
    # Verify meeting exists
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    result = await db.execute(
        select(Requirement)
        .where(Requirement.meeting_id == meeting_id)
        .order_by(Requirement.id)
    )
    return list(result.scalars().all())


@router.post("/{meeting_id}/process", response_model=MeetingOut)
async def process_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> Meeting:
    """Trigger AI processing pipeline for a meeting.

    Runs transcript polishing, minutes generation, and requirement
    extraction.  Updates the meeting record with the results.
    """
    from backend.services.ai.pipeline import MeetingAIPipeline

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    raw_transcript = meeting.raw_transcript or ""
    if not raw_transcript.strip():
        raise HTTPException(
            status_code=400,
            detail="Cannot process: raw_transcript is empty",
        )

    try:
        pipeline = MeetingAIPipeline(
            openai_api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            base_url=settings.OPENAI_BASE_URL or None,
        )
        result = await pipeline.process(
            raw_transcript=raw_transcript,
            meeting_title=meeting.title,
        )
    except Exception as exc:
        logger.exception("Pipeline processing failed for meeting %s", meeting_id)
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {exc}",
        )

    # Update meeting with pipeline results
    meeting.polished_transcript = result.get("polished_transcript", "")
    meeting.meeting_minutes = json.dumps(
        result.get("meeting_minutes", {}), ensure_ascii=False
    )
    meeting.status = "completed"
    meeting.end_time = meeting.end_time or datetime.utcnow()

    await db.commit()

    # Extract and save requirements
    requirements = result.get("requirements", [])
    for idx, req in enumerate(requirements):
        db_req = Requirement(
            meeting_id=meeting_id,
            req_id=req.get("id", f"REQ-{idx + 1:03d}"),
            module=req.get("module", ""),
            description=req.get("description", ""),
            priority=req.get("priority", "P2"),
            source=req.get("source", ""),
            speaker=req.get("speaker", ""),
            status="待确认",
        )
        db.add(db_req)

    await db.commit()
    await db.refresh(meeting)
    logger.info(
        "Processed meeting id=%s: %d requirements extracted",
        meeting_id,
        len(requirements),
    )
    return meeting


@router.post("/{meeting_id}/export-feishu")
async def export_meeting_to_feishu(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Export meeting minutes to a Feishu document.

    Returns:
        {"url": "<feishu_doc_url>"}
    """
    from backend.services.feishu.auth import FeishuAuth
    from backend.services.feishu.doc_writer import FeishuDocWriter

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Build meeting_data dict for the doc writer
    meeting_data = {
        "title": meeting.title,
        "start_time": str(meeting.start_time) if meeting.start_time else "",
        "end_time": str(meeting.end_time) if meeting.end_time else "",
        "date": str(meeting.start_time.date()) if meeting.start_time else "",
        "full_transcript": meeting.raw_transcript or "",
    }

    # Parse meeting_minutes if available
    if meeting.meeting_minutes:
        try:
            minutes = json.loads(meeting.meeting_minutes)
            meeting_data.update(minutes)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse meeting_minutes JSON for meeting %s", meeting_id)

    try:
        auth = FeishuAuth(
            app_id=settings.FEISHU_APP_ID,
            app_secret=settings.FEISHU_APP_SECRET,
        )
        writer = FeishuDocWriter(auth)
        doc_url = await writer.create_meeting_doc(meeting_data)
        await writer.close()
        await auth.close()
    except Exception as exc:
        logger.exception("Feishu export failed for meeting %s", meeting_id)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {exc}",
        )

    logger.info("Exported meeting %s to Feishu: %s", meeting_id, doc_url)
    
    # Persist the URL to the database
    meeting.feishu_url = doc_url
    await db.commit()
    
    return {"status": "success", "url": doc_url}


def _build_minutes_markdown(meeting: Meeting) -> str:
    """Render a Markdown representation of a meeting's minutes.

    Mirrors the structure used by the frontend's ``minutes-export.js`` so
    KB content matches what users see in the UI: title, meta line, summary,
    discussion key points, decisions and action items.
    """
    title = (meeting.title or "未命名会议").strip() or "未命名会议"
    date = ""
    if meeting.start_time:
        try:
            date = meeting.start_time.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            date = str(meeting.start_time)

    minutes: dict = {}
    if meeting.meeting_minutes:
        try:
            minutes = json.loads(meeting.meeting_minutes) or {}
        except (json.JSONDecodeError, TypeError):
            minutes = {}

    def _flatten_key_point(p) -> str:
        if isinstance(p, str):
            return p.strip()
        if not isinstance(p, dict):
            return ""
        topic = (p.get("topic") or "").strip()
        content = (p.get("content") or "").strip()
        return f"{topic}：{content}" if topic else content

    def _flatten_decision(d) -> str:
        if isinstance(d, str):
            return d.strip()
        if not isinstance(d, dict):
            return ""
        content = (d.get("content") or "").strip()
        owner = (d.get("owner") or "").strip()
        return f"{content}（负责人：{owner}）" if owner else content

    def _flatten_action(a) -> str:
        if isinstance(a, str):
            return a.strip()
        if not isinstance(a, dict):
            return ""
        owner = (a.get("owner") or "").strip()
        task = (a.get("task") or a.get("content") or "").strip()
        deadline = (a.get("deadline") or "").strip()
        prefix = f"{owner}：" if owner else ""
        suffix = f"（截止：{deadline}）" if deadline else ""
        return f"{prefix}{task}{suffix}".strip()

    summary = (minutes.get("summary") or "").strip()
    key_points = [s for s in (_flatten_key_point(p) for p in (minutes.get("key_points") or [])) if s]
    decisions = [s for s in (_flatten_decision(d) for d in (minutes.get("decisions") or [])) if s]
    action_items = [s for s in (_flatten_action(a) for a in (minutes.get("action_items") or [])) if s]

    lines: list[str] = [f"# {title}", ""]
    if date:
        lines.append(f"> 会议日期：{date}")
        lines.append("")
    if summary:
        lines.append("## 会议摘要")
        lines.append("")
        lines.append(summary)
        lines.append("")
    if key_points:
        lines.append("## 讨论要点")
        lines.append("")
        for item in key_points:
            lines.append(f"- {item}")
        lines.append("")
    if decisions:
        lines.append("## 决策事项")
        lines.append("")
        for item in decisions:
            lines.append(f"- {item}")
        lines.append("")
    if action_items:
        lines.append("## 待办事项")
        lines.append("")
        for item in action_items:
            lines.append(f"- {item}")
        lines.append("")

    if not (summary or key_points or decisions or action_items):
        # Fall back to the polished/raw transcript so the KB document is never empty.
        body = (meeting.polished_transcript or meeting.raw_transcript or "").strip()
        if body:
            lines.append("## 会议转录")
            lines.append("")
            lines.append(body)
            lines.append("")

    return "\n".join(lines).strip() + "\n"


class KBSyncRequest(BaseModel):
    """Request body for syncing meeting minutes to the Knowledge Base."""

    project_id: Optional[str] = Field(
        default=None,
        description="UUID of the KB project to associate with. Optional.",
    )
    doc_type: Optional[str] = Field(
        default=None,
        description="KB doc_type override. Defaults to settings.KB_DEFAULT_DOC_TYPE.",
    )


class MeetingProjectUpdate(BaseModel):
    """Payload for associating (or clearing) a KB project to a meeting."""

    project_id: Optional[str] = Field(
        default=None,
        description="KB project UUID. Pass null/empty to clear the association.",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Optional human-readable project name for caching.",
    )
    rerun_stakeholders: bool = Field(
        default=True,
        description=(
            "If true (default), re-extract the stakeholder graph using the "
            "newly associated project's KB documents."
        ),
    )


class StakeholderMapPut(BaseModel):
    """Replace the meeting's stakeholder graph with user-edited JSON."""

    stakeholders: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stakeholder graph helpers
# ---------------------------------------------------------------------------


async def _fetch_project_kb_docs(project_id: str | None) -> list[dict]:
    """Return the full document detail (with markdown_content) for every
    file under ``project_id``.

    Best-effort: if KB is unconfigured or the call fails, return ``[]``
    so that callers can still proceed with a meeting-only extraction.
    Documents without textual content are filtered out — they would just
    waste tokens at the LLM step.
    """
    if not project_id:
        return []
    try:
        from backend.services.kb_client import KBClient, KBNotConfigured, KBError

        try:
            client = KBClient()
        except KBNotConfigured:
            return []

        summaries = await client.list_project_documents(project_id)
        if not summaries:
            return []

        # Hydrate each summary with its full body. Cap at 10 docs to keep
        # the AI step bounded; the most recent docs come first per KB.
        docs: list[dict] = []
        for s in summaries[:10]:
            doc_id = s.get("id")
            if not doc_id:
                continue
            try:
                detail = await client.get_document(doc_id)
            except KBError as exc:
                logger.warning(
                    "KB get_document(%s) failed (skipping): %s", doc_id, exc
                )
                continue
            if not detail:
                continue
            # Normalise: ensure id/filename are present even if KB drops them.
            detail.setdefault("id", doc_id)
            detail.setdefault("filename", s.get("filename", ""))
            if detail.get("markdown_content") or detail.get("summary"):
                docs.append(detail)
        return docs
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected failure while fetching project KB docs")
        return []


async def _fetch_internal_meeting_summaries(
    exclude_meeting_id: int,
    db: AsyncSession,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build pseudo-documents from other completed meetings in this DB.

    When a session is **not** linked to a KB project, internal stand-ups
    still benefit from names and roles that appeared in earlier company
    meetings. Each item matches the shape expected by
    :meth:`StakeholderExtractor.format_kb_docs` (plus ``source_kind``).
    """
    result = await db.execute(
        select(Meeting)
        .where(Meeting.id != exclude_meeting_id)
        .where(Meeting.status == "completed")
        .order_by(Meeting.created_at.desc())
        .limit(limit * 3)
    )
    rows = list(result.scalars().all())
    docs: list[dict[str, Any]] = []
    for m in rows:
        if len(docs) >= limit:
            break
        title = (m.title or f"会议-{m.id}").strip()
        date_s = ""
        if m.start_time:
            try:
                date_s = m.start_time.strftime("%Y-%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                date_s = str(m.start_time)

        summary_bits: list[str] = []
        if date_s:
            summary_bits.append(f"会议时间：{date_s}")
        summary_bits.append(f"系统会议 ID：{m.id}")

        body_extra: list[str] = []
        minutes_raw = (m.meeting_minutes or "").strip()
        if minutes_raw:
            try:
                mo = json.loads(minutes_raw)
                if isinstance(mo, dict):
                    if mo.get("summary"):
                        summary_bits.append(str(mo["summary"]))
                    att = mo.get("attendees")
                    if isinstance(att, list) and att:
                        names: list[str] = []
                        for a in att[:40]:
                            if isinstance(a, str):
                                names.append(a.strip())
                            elif isinstance(a, dict):
                                n = a.get("name") or a.get("label") or ""
                                if n:
                                    names.append(str(n).strip())
                        names = [x for x in names if x]
                        if names:
                            summary_bits.append("参会人员：" + "、".join(names))
                    for key, label in (
                        ("key_points", "关键议题"),
                        ("decisions", "决议"),
                    ):
                        items = mo.get(key) or []
                        if not isinstance(items, list) or not items:
                            continue
                        lines: list[str] = []
                        for it in items[:6]:
                            if isinstance(it, dict):
                                t = it.get("topic") or it.get("title") or ""
                                c = it.get("content") or it.get("description") or ""
                                chunk = f"{t} {c}".strip()
                                if chunk:
                                    lines.append("- " + chunk[:220])
                            elif isinstance(it, str) and it.strip():
                                lines.append("- " + it.strip()[:220])
                        if lines:
                            body_extra.append(f"【{label}】\n" + "\n".join(lines))
            except (json.JSONDecodeError, TypeError):
                body_extra.append(minutes_raw[:1600])

        transcript = (m.polished_transcript or m.raw_transcript or "").strip()
        if transcript:
            body_extra.append("【转写摘录】\n" + transcript[:1600])

        smap = (m.stakeholder_map or "").strip()
        if smap:
            try:
                sg = json.loads(smap)
                if isinstance(sg, dict):
                    peeps = sg.get("stakeholders") or []
                    if isinstance(peeps, list) and peeps:
                        pl = [
                            str(p.get("name", "")).strip()
                            for p in peeps
                            if isinstance(p, dict)
                        ]
                        pl = [x for x in pl if x][:30]
                        if pl:
                            summary_bits.append(
                                "历史干系人图谱中出现：" + "、".join(pl)
                            )
            except (json.JSONDecodeError, TypeError):
                pass

        summary = "\n".join(summary_bits)
        body = "\n\n".join([p for p in body_extra if p]).strip()
        if not summary.strip() and not body:
            continue

        docs.append(
            {
                "id": f"meeting-{m.id}",
                "filename": f"[内部历史会议] {title}",
                "summary": summary,
                "markdown_content": body or summary[:1200],
                "source_kind": "internal_meeting",
            }
        )

    if docs:
        logger.info(
            "Stakeholder context: %d internal meeting excerpts (no KB project)",
            len(docs),
        )
    return docs


async def _stakeholder_reference_docs(
    meeting_id: int,
    kb_project_id: str | None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """KB project documents if a project is set; else recent internal meetings."""
    if (kb_project_id or "").strip():
        return await _fetch_project_kb_docs(kb_project_id)
    return await _fetch_internal_meeting_summaries(meeting_id, db)


def _mermaid_escape_label(s: str) -> str:
    """Make a short safe Mermaid node label (inside double quotes)."""
    t = (s or "").strip().replace('"', "＂").replace("\n", " ").replace("\r", "")
    return (t[:100] + "…") if len(t) > 100 else t


def _stakeholder_mermaid_block(
    people: list[dict],
    relations: list[dict],
) -> str:
    """Build an optional Mermaid flowchart for KB / Markdown viewers."""
    lines_body: list[str] = []
    name_to_id: dict[str, str] = {}
    counter = 0

    def ensure_node(raw_name: str) -> str:
        nonlocal counter
        name = (raw_name or "").strip() or "（未具名）"
        key = name.lower()
        if key in name_to_id:
            return name_to_id[key]
        nid = f"n{counter}"
        counter += 1
        name_to_id[key] = nid
        lbl = _mermaid_escape_label(name)
        lines_body.append(f'    {nid}["{lbl}"]')
        return nid

    for p in people:
        if isinstance(p, dict) and (p.get("name") or "").strip():
            ensure_node(p.get("name", ""))

    edge_lines: list[str] = []
    for r in relations:
        if not isinstance(r, dict):
            continue
        f = (r.get("from") or "").strip()
        t = (r.get("to") or "").strip()
        if not (f and t):
            continue
        fid = ensure_node(f)
        tid = ensure_node(t)
        rtype = _mermaid_escape_label((r.get("type") or "").strip() or "关系")
        edge_lines.append(f'    {fid} -->|"{rtype}"| {tid}')

    if not lines_body and not edge_lines:
        return ""

    return (
        "## 四、关系图谱（Mermaid）\n\n"
        "_可在支持 Mermaid 的编辑器或知识库中渲染。_\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        + "\n".join(lines_body + edge_lines)
        + "\n```\n\n"
    )


def _stakeholders_from_meeting(meeting: Meeting) -> dict:
    """Decode meeting.stakeholder_map JSON, returning a normalised dict."""
    if not meeting.stakeholder_map:
        return {"stakeholders": [], "relations": []}
    try:
        data = json.loads(meeting.stakeholder_map)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Bad stakeholder_map JSON for meeting %s", meeting.id)
        return {"stakeholders": [], "relations": []}
    if not isinstance(data, dict):
        return {"stakeholders": [], "relations": []}
    data.setdefault("stakeholders", [])
    data.setdefault("relations", [])
    return data


def _build_stakeholder_markdown(meeting: Meeting) -> str:
    """Render a person-card style Markdown for the stakeholder graph.

    Output structure:
        # 干系人图谱 - <meeting title>
        > 项目: ...  / 会议日期: ...

        ## 一、人物概览
        | 姓名 | 角色 | 立场 | 来源 |
        ...

        ## 二、人物详情
        ### 张三
        - 角色: 项目经理
        - 组织: ...
        - 别名: ...
        - 关键发言:
          - ...
        - 来源:
          - 会议: ...
          - 知识库 (kb_doc:<id>): ...

        ## 三、关系
        - 张三 → 李四 (works_with): ...
    """
    graph = _stakeholders_from_meeting(meeting)
    people = graph.get("stakeholders", []) or []
    relations = graph.get("relations", []) or []

    title = (meeting.title or f"meeting-{meeting.id}").strip() or f"meeting-{meeting.id}"
    date_str = ""
    if meeting.start_time:
        try:
            date_str = meeting.start_time.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            date_str = str(meeting.start_time)

    side_label = {
        "internal": "我方",
        "customer": "客户",
        "vendor": "供应商",
        "unknown": "未知",
    }

    lines: list[str] = [f"# 干系人图谱 - {title}", ""]
    meta = []
    if meeting.kb_project_name or meeting.kb_project_id:
        meta.append(f"项目：{meeting.kb_project_name or meeting.kb_project_id}")
    if date_str:
        meta.append(f"会议日期：{date_str}")
    meta.append(f"共 {len(people)} 位干系人")
    if meta:
        lines.append("> " + " · ".join(meta))
        lines.append("")

    if not people:
        lines.append("_本次会议未识别到具名干系人。_")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    # Overview table
    lines.append("## 一、人物概览")
    lines.append("")
    lines.append("| 姓名 | 角色 | 组织 | 立场 | 来源数 |")
    lines.append("|------|------|------|------|--------|")
    for p in people:
        name = (p.get("name") or "").replace("|", "\\|")
        role = (p.get("role") or "").replace("|", "\\|")
        org = (p.get("organization") or "").replace("|", "\\|")
        side = side_label.get((p.get("side") or "unknown"), "未知")
        src_count = len(p.get("sources") or [])
        lines.append(f"| {name} | {role} | {org} | {side} | {src_count} |")
    lines.append("")

    # Per-person cards
    lines.append("## 二、人物详情")
    lines.append("")
    for p in people:
        name = (p.get("name") or "").strip() or "(未具名)"
        lines.append(f"### {name}")
        if p.get("role"):
            lines.append(f"- **角色**：{p['role']}")
        if p.get("organization"):
            lines.append(f"- **组织**：{p['organization']}")
        side_key = p.get("side") or "unknown"
        if side_key:
            lines.append(f"- **立场**：{side_label.get(side_key, side_key)}")
        if p.get("contact"):
            lines.append(f"- **联系方式**：{p['contact']}")
        aliases = [a for a in (p.get("aliases") or []) if a]
        if aliases:
            lines.append(f"- **别名**：{', '.join(aliases)}")
        responsibilities = [r for r in (p.get("responsibilities") or []) if r]
        if responsibilities:
            lines.append("- **职责**：")
            for r in responsibilities:
                lines.append(f"  - {r}")
        key_points = [k for k in (p.get("key_points") or []) if k]
        if key_points:
            lines.append("- **关键发言/观点**：")
            for k in key_points:
                lines.append(f"  - {k}")
        sources = p.get("sources") or []
        if sources:
            lines.append("- **来源**：")
            for s in sources:
                src_type = s.get("type", "")
                ref = s.get("ref", "")
                snippet = s.get("snippet", "")
                if src_type == "meeting":
                    label = f"会议「{ref}」" if ref else "本次会议"
                elif src_type == "kb_doc":
                    label = f"知识库文档 `{ref}`"
                else:
                    label = src_type or "来源"
                if snippet:
                    lines.append(f"  - {label}：「{snippet}」")
                else:
                    lines.append(f"  - {label}")
        lines.append("")

    # Relations
    if relations:
        lines.append("## 三、协作/关系")
        lines.append("")
        for r in relations:
            f = (r.get("from") or "").strip()
            t = (r.get("to") or "").strip()
            rtype = (r.get("type") or "works_with").strip()
            desc = (r.get("description") or "").strip()
            if not (f and t):
                continue
            arrow = f"{f} → {t}（{rtype}）"
            lines.append(f"- {arrow}：{desc}" if desc else f"- {arrow}")
        lines.append("")

    mermaid = _stakeholder_mermaid_block(people, relations)
    if mermaid:
        lines.append(mermaid)

    return "\n".join(lines).strip() + "\n"


@router.get("/kb/projects")
async def list_kb_projects() -> list[dict]:
    """Proxy KB project listing for the frontend project picker.

    The frontend doesn't talk to KB directly (no need to expose JWT to
    the browser, and avoids CORS), so we forward through the backend.
    """
    from backend.services.kb_client import KBClient, KBNotConfigured, KBError

    try:
        client = KBClient()
    except KBNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        projects = await client.list_projects()
    except KBError as exc:
        logger.warning("KB list_projects failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KB error: {exc}") from exc

    # Trim payload to what the picker actually needs.
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "customer": p.get("customer"),
            "industry": p.get("industry"),
            "document_count": p.get("document_count", 0),
        }
        for p in projects
        if p.get("id")
    ]


@router.post("/{meeting_id}/sync-kb")
async def sync_meeting_to_kb(
    meeting_id: int,
    payload: KBSyncRequest,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Sync a meeting's minutes (as Markdown) to the Knowledge Base.

    Returns the KB ``doc_id``, an in-app KB URL and the synced timestamp.
    Repeated calls re-upload (KB has no PUT semantics for documents);
    each call therefore creates a new document and updates the cached
    ``kb_doc_id`` / ``kb_url`` to the latest one.
    """
    from backend.services.kb_client import KBClient, KBNotConfigured, KBError

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status not in ("completed", "failed"):
        # Allow syncing even for "failed" — user might have manually
        # edited the minutes. Block only mid-pipeline states.
        if meeting.status in ("recording", "transcribing", "processing", "polishing"):
            raise HTTPException(
                status_code=409,
                detail="Meeting is still being processed; please wait until it completes.",
            )

    markdown = _build_minutes_markdown(meeting)
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="No minutes content to sync.")

    try:
        client = KBClient()
    except KBNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    safe_title = (meeting.title or f"meeting-{meeting.id}").strip() or f"meeting-{meeting.id}"
    filename = f"{safe_title}-{meeting.id}.md"

    # If this meeting was synced before, remove the old KB document first
    # so the user doesn't end up with stale duplicates piling up server-side.
    # Failures here are non-fatal: a missing/already-deleted doc shouldn't
    # block the new upload — we just log it.
    replaced_old_doc = False
    previous_doc_id = meeting.kb_doc_id
    if previous_doc_id:
        try:
            await client.delete_document(previous_doc_id)
            replaced_old_doc = True
            logger.info(
                "Meeting %s: deleted previous KB doc %s before re-sync",
                meeting_id, previous_doc_id,
            )
        except KBError as exc:
            logger.warning(
                "Meeting %s: failed to delete previous KB doc %s (continuing anyway): %s",
                meeting_id, previous_doc_id, exc,
            )

    try:
        result = await client.upload_markdown(
            filename=filename,
            content=markdown,
            project_id=payload.project_id,
            doc_type=payload.doc_type,
        )
    except KBError as exc:
        logger.warning("KB upload failed for meeting %s: %s", meeting_id, exc)
        raise HTTPException(status_code=502, detail=f"KB upload failed: {exc}") from exc

    doc_id = result.get("id")
    doc_url = result.get("url")
    if not doc_id:
        raise HTTPException(status_code=502, detail="KB returned no document id")

    meeting.kb_doc_id = doc_id
    meeting.kb_url = doc_url
    meeting.kb_synced_at = datetime.utcnow()
    await db.commit()

    logger.info("Meeting %s synced to KB doc %s", meeting_id, doc_id)
    return {
        "status": "success",
        "kb_doc_id": doc_id,
        "kb_url": doc_url,
        "kb_synced_at": meeting.kb_synced_at,
        "filename": result.get("filename"),
        "kb_status": result.get("status"),
        "replaced_old_doc": replaced_old_doc,
        "previous_kb_doc_id": previous_doc_id if replaced_old_doc else None,
    }


# ---------------------------------------------------------------------------
# Stakeholder graph: project association, re-extract, KB sync
# ---------------------------------------------------------------------------


@router.put("/{meeting_id}/project")
async def update_meeting_project(
    meeting_id: int,
    payload: MeetingProjectUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Associate (or unset) a KB project with this meeting.

    When ``rerun_stakeholders`` is ``True`` (default), the stakeholder
    graph is re-extracted in the background using the new project's KB
    documents, so people from project files get merged into the graph.
    """
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    new_project_id = (payload.project_id or "").strip() or None
    new_project_name = (payload.project_name or "").strip() or None

    # Look up the project name from KB if the caller didn't provide one.
    # Failing this lookup is non-fatal — we'll just store the id.
    if new_project_id and not new_project_name:
        try:
            from backend.services.kb_client import KBClient, KBNotConfigured, KBError
            try:
                projects = await KBClient().list_projects()
                for p in projects:
                    if p.get("id") == new_project_id:
                        new_project_name = p.get("name") or new_project_id
                        break
            except (KBNotConfigured, KBError):
                pass
        except Exception:  # noqa: BLE001
            pass

    meeting.kb_project_id = new_project_id
    meeting.kb_project_name = new_project_name
    await db.commit()
    logger.info(
        "Meeting %s: project association set to %r (%s)",
        meeting_id, new_project_name, new_project_id,
    )

    if payload.rerun_stakeholders and new_project_id and (meeting.raw_transcript or "").strip():
        background_tasks.add_task(run_extract_stakeholders, meeting_id)
        return {
            "status": "success",
            "kb_project_id": new_project_id,
            "kb_project_name": new_project_name,
            "stakeholder_extraction": "scheduled",
        }

    return {
        "status": "success",
        "kb_project_id": new_project_id,
        "kb_project_name": new_project_name,
        "stakeholder_extraction": "skipped",
    }


async def run_extract_stakeholders(meeting_id: int) -> None:
    """Background task: re-extract the stakeholder graph for a meeting.

    Uses the polished transcript (falling back to raw) plus the KB docs
    of the meeting's associated project. The freshly produced graph is
    merged with whatever was already stored, so previously-known people
    aren't lost when a project is added to an existing meeting.
    """
    from backend.database import async_session_factory
    from backend.services.ai.stakeholder_extractor import (
        StakeholderExtractor,
        merge_stakeholder_maps,
    )

    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            return
        transcript = (meeting.polished_transcript or meeting.raw_transcript or "").strip()
        if not transcript:
            logger.info("Meeting %s: no transcript yet, skip stakeholder extraction", meeting_id)
            return

        kb_docs = await _stakeholder_reference_docs(
            meeting_id, meeting.kb_project_id, db
        )

        # Parse minutes JSON if available so the extractor has structure.
        minutes_obj: dict | None = None
        if meeting.meeting_minutes:
            try:
                minutes_obj = json.loads(meeting.meeting_minutes)
            except (json.JSONDecodeError, TypeError):
                minutes_obj = None

        try:
            from backend.services.ai.llm_client import LLMClient
            llm = LLMClient(
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                base_url=settings.OPENAI_BASE_URL or None,
            )
            extractor = StakeholderExtractor(llm)
            new_graph = await extractor.extract(
                meeting_id=meeting_id,
                meeting_title=meeting.title,
                transcript=transcript,
                minutes=minutes_obj,
                kb_docs=kb_docs,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Re-extract stakeholders failed for meeting %s", meeting_id)
            return

        # Merge with existing graph so we keep prior known data points.
        prior = _stakeholders_from_meeting(meeting)
        merged = merge_stakeholder_maps(prior, new_graph)
        meeting.stakeholder_map = json.dumps(merged, ensure_ascii=False)
        await db.commit()
        logger.info(
            "Meeting %s: stakeholder graph updated (%d people, %d relations)",
            meeting_id,
            len(merged.get("stakeholders", [])),
            len(merged.get("relations", [])),
        )


@router.put("/{meeting_id}/stakeholder-map")
async def put_stakeholder_map(
    meeting_id: int,
    payload: StakeholderMapPut,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Persist a manually edited stakeholder graph (replaces stored JSON)."""
    from backend.services.ai.stakeholder_extractor import (
        _normalise_person,
        _normalise_relation,
    )

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if len(payload.stakeholders) > 200:
        raise HTTPException(status_code=400, detail="Too many stakeholders (max 200)")
    if len(payload.relations) > 500:
        raise HTTPException(status_code=400, detail="Too many relations (max 500)")

    norm_people: list[dict] = []
    for p in payload.stakeholders:
        if isinstance(p, dict):
            np = _normalise_person(p)
            if np.get("name"):
                norm_people.append(np)

    norm_rel: list[dict] = []
    for r in payload.relations:
        if isinstance(r, dict):
            nr = _normalise_relation(r)
            if nr["from"] and nr["to"]:
                norm_rel.append(nr)

    graph = {"stakeholders": norm_people, "relations": norm_rel}
    meeting.stakeholder_map = json.dumps(graph, ensure_ascii=False)
    await db.commit()
    logger.info(
        "Meeting %s: stakeholder_map saved manually (%d people, %d relations)",
        meeting_id,
        len(norm_people),
        len(norm_rel),
    )
    return {"status": "success", "stakeholders": graph}


@router.post("/{meeting_id}/actions/extract_stakeholders")
async def manual_extract_stakeholders(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Manually trigger (or re-trigger) stakeholder extraction.

    Re-runs the LLM with the current transcript + minutes + project KB
    docs. Useful after editing the polished transcript or after attaching
    a new project to an existing meeting.
    """
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not (meeting.raw_transcript or "").strip():
        raise HTTPException(status_code=400, detail="Meeting has no transcript yet.")
    background_tasks.add_task(run_extract_stakeholders, meeting_id)
    return {"status": "scheduled"}


@router.post("/{meeting_id}/sync-stakeholder-map-kb")
async def sync_stakeholder_map_to_kb(
    meeting_id: int,
    payload: KBSyncRequest,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Push the stakeholder graph (as Markdown) to the KB.

    Replaces a previously-uploaded stakeholder document for the same
    meeting (delete-then-upload), mirroring the meeting-minutes sync
    flow. The doc_type defaults to ``stakeholder_map`` so KB can group
    these separately from regular meeting notes.
    """
    from backend.services.kb_client import KBClient, KBNotConfigured, KBError

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    graph = _stakeholders_from_meeting(meeting)
    if not graph.get("stakeholders"):
        raise HTTPException(
            status_code=400,
            detail="Stakeholder graph is empty. Run extraction first.",
        )

    markdown = _build_stakeholder_markdown(meeting)

    try:
        client = KBClient()
    except KBNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    safe_title = (meeting.title or f"meeting-{meeting.id}").strip() or f"meeting-{meeting.id}"
    filename = f"{safe_title}-{meeting.id}-stakeholders.md"

    # Replace previously-synced stakeholder doc (if any) so we don't
    # litter the KB with stale copies on each refresh.
    replaced_old_doc = False
    previous_doc_id = meeting.stakeholder_kb_doc_id
    if previous_doc_id:
        try:
            await client.delete_document(previous_doc_id)
            replaced_old_doc = True
        except KBError as exc:
            logger.warning(
                "Meeting %s: failed to delete previous stakeholder KB doc %s (continuing): %s",
                meeting_id, previous_doc_id, exc,
            )

    # KB currently restricts doc_type to a fixed enum (requirement_research,
    # meeting_notes, solution_design, test_case, user_manual). The closest
    # match for a stakeholder graph is requirement_research — it's the bucket
    # KB uses for project discovery / people-related deliverables.
    doc_type = payload.doc_type or "requirement_research"
    project_id = payload.project_id or meeting.kb_project_id

    try:
        result = await client.upload_markdown(
            filename=filename,
            content=markdown,
            project_id=project_id,
            doc_type=doc_type,
        )
    except KBError as exc:
        raise HTTPException(status_code=502, detail=f"KB upload failed: {exc}") from exc

    doc_id = result.get("id")
    doc_url = result.get("url")
    if not doc_id:
        raise HTTPException(status_code=502, detail="KB returned no document id")

    meeting.stakeholder_kb_doc_id = doc_id
    meeting.stakeholder_kb_url = doc_url
    meeting.stakeholder_kb_synced_at = datetime.utcnow()
    # Persist project association if it came from the request body.
    if payload.project_id:
        meeting.kb_project_id = payload.project_id
    await db.commit()

    logger.info("Meeting %s: stakeholder map synced to KB doc %s", meeting_id, doc_id)
    return {
        "status": "success",
        "kb_doc_id": doc_id,
        "kb_url": doc_url,
        "kb_synced_at": meeting.stakeholder_kb_synced_at,
        "filename": result.get("filename"),
        "kb_status": result.get("status"),
        "replaced_old_doc": replaced_old_doc,
        "previous_kb_doc_id": previous_doc_id if replaced_old_doc else None,
    }


@router.post("/{meeting_id}/sync-requirements")
async def sync_requirements_to_feishu(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Sync extracted requirements to a Feishu Bitable.

    Returns:
        {"url": "<bitable_url>"}
    """
    from backend.services.feishu.auth import FeishuAuth
    from backend.services.feishu.bitable_writer import FeishuBitableWriter

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Fetch requirements from DB
    result = await db.execute(
        select(Requirement)
        .where(Requirement.meeting_id == meeting_id)
        .order_by(Requirement.id)
    )
    db_requirements = list(result.scalars().all())

    if not db_requirements:
        raise HTTPException(
            status_code=400,
            detail="No requirements to sync. Process the meeting first.",
        )

    # Convert to dict format
    requirements = [
        {
            "id": r.req_id,
            "module": r.module,
            "description": r.description,
            "priority": r.priority,
            "source": r.source,
            "speaker": r.speaker,
            "status": r.status,
        }
        for r in db_requirements
    ]

    try:
        auth = FeishuAuth(
            app_id=settings.FEISHU_APP_ID,
            app_secret=settings.FEISHU_APP_SECRET,
        )
        writer = FeishuBitableWriter(auth)

        # Reuse existing Bitable if we already created one
        app_token = meeting.bitable_app_token or ""
        bitable_url, new_app_token = await writer.sync_requirements(
            app_token=app_token,
            requirements=requirements,
        )

        # Persist the Bitable app_token on first creation
        if new_app_token and not meeting.bitable_app_token:
            meeting.bitable_app_token = new_app_token
            await db.commit()
            logger.info(
                "Saved bitable_app_token=%s for meeting %s",
                new_app_token, meeting_id,
            )

        await writer.close()
        await auth.close()
    except Exception as exc:
        logger.exception("Feishu Bitable sync failed for meeting %s", meeting_id)
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {exc}",
        )

    logger.info("Synced %d requirements for meeting %s to Bitable", len(requirements), meeting_id)
    return {"url": bitable_url}


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a meeting and its associated requirements."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    await db.execute(sql_delete(Requirement).where(Requirement.meeting_id == meeting_id))
    await db.delete(meeting)
    await db.commit()
    logger.info("Deleted meeting id=%s", meeting_id)
    return {}


@router.post("/upload", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    asr_engine: str = Form("whisper"),
    db: AsyncSession = Depends(get_session),
) -> Meeting:
    logger.info("Received audio upload. ASR Engine chosen: %s", asr_engine)
    title = file.filename or "New Meeting"
    meeting = Meeting(title=title, asr_engine=asr_engine, status="uploading")
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    
    from backend.services.asr.audio_utils import AudioUtils

    # Determine audio format from filename
    filename = file.filename or "audio.wav"
    ext = os.path.splitext(filename)[1].lstrip(".").lower() or "wav"

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Create meeting record immediately with 'transcribing' status
    meeting_title = title.strip() or filename
    meeting = Meeting(
        title=meeting_title, 
        start_time=datetime.utcnow(), 
        status="transcribing",
        asr_engine="whisper"
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    logger.info("Created meeting id=%s for upload %r (background task starting)", meeting.id, filename)

    # Convert to PCM synchronously (usually fast enough)
    try:
        try:
            pcm_data = AudioUtils.convert_to_pcm(audio_bytes, source_format=ext)
        except Exception as exc:
            logger.warning("PCM conversion failed for %r, trying wav: %s", ext, exc)
            pcm_data = AudioUtils.convert_to_pcm(audio_bytes, source_format="wav")
    except Exception as exc:
        meeting.status = "failed"
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Audio conversion failed: {exc}")

    # 3. Save PCM to disk for persistence/resume
    upload_path = os.path.join(settings.UPLOAD_DIR, f"{meeting.id}.pcm")
    try:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        with open(upload_path, "wb") as f:
            f.write(pcm_data)
        logger.info("Saved PCM for meeting %s to %s", meeting.id, upload_path)
    except Exception as exc:
        logger.error("Failed to save PCM for meeting %s: %s", meeting.id, exc)

    # Launch processing in background
    background_tasks.add_task(run_meeting_workflow, meeting.id, pcm_data)

    return meeting


async def run_meeting_workflow(meeting_id: int, pcm_data: bytes) -> None:
    """Background task to run ASR and AI pipeline with periodic DB updates."""
    from backend.database import async_session_factory
    from backend.services.asr.xiaomi_asr import XiaomiASRClient
    from backend.services.ai.pipeline import MeetingAIPipeline

    logger.info("Starting background workflow for meeting %s", meeting_id)
    
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            logger.error("Meeting %s not found in background task", meeting_id)
            return

        try:
            # 1. Transcribe with Selected ASR Engine
            from backend.services.asr.xiaomi_asr import XiaomiASRClient
            from backend.services.asr.whisper_asr import WhisperASRClient
            from backend.services.asr.xunfei_asr import XunfeiASRClient

            transcript_parts: list[str] = []
            
            # Select Client
            transcript_parts: list[str] = []
            
            # The ASR engine is now retrieved from the meeting record (set during upload)
            logger.info("Meeting %s: Using ASR Engine: %s", meeting_id, meeting.asr_engine)

            if meeting.asr_engine == "whisper":
                from backend.services.asr.whisper_asr import WhisperASRClient
                client = WhisperASRClient(model_size=settings.WHISPER_MODEL_SIZE)
            else:
                # Use Xiaomi as fallback or if explicitly chosen
                from backend.services.asr.xiaomi_asr import XiaomiASRClient
                client = XiaomiASRClient(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                    model=settings.XIAOMI_OMNI_MODEL,
                )

            # Pre-calculate chunks for progress bar and indexing
            chunk_seconds = 20 if meeting.asr_engine == "xiaomi" else 10
            chunk_size = 16000 * 2 * chunk_seconds
            total_chunks = (len(pcm_data) + chunk_size - 1) // chunk_size
            
            # Use pre-allocated list to handle concurrent results out of order
            transcript_parts: list[str] = [""] * total_chunks
            save_lock = asyncio.Lock()
            loop = asyncio.get_event_loop()
            
            async def on_asr_result(result):
                async with save_lock:
                    idx = getattr(result, 'index', 0)
                    if 0 <= idx < total_chunks:
                        transcript_parts[idx] = result.text
                    
                    # Update meeting status
                    async for db_retry in get_session():
                        try:
                            m = await db_retry.get(Meeting, meeting_id)
                            m.done_chunks += 1
                            # Join only non-empty parts, but in order
                            m.raw_transcript = " ".join([p for p in transcript_parts if p])
                            await db_retry.commit()
                            break
                        except Exception as e:
                            logger.error("DB Update Error during ASR callback: %s", e)
                            await db_retry.rollback()

            client.on_result(lambda r: loop.call_soon_threadsafe(
                lambda: asyncio.create_task(on_asr_result(r))
            ))
            meeting.total_chunks = total_chunks
            
            # ... (Existing breakpoint resume logic) ...
            start_chunk_idx = meeting.done_chunks
            if start_chunk_idx > 0 and start_chunk_idx < total_chunks:
                logger.info("Meeting %s: Resuming from chunk %d/%d", meeting_id, start_chunk_idx, total_chunks)
                start_byte = start_chunk_idx * chunk_size
                pcm_data_to_send = pcm_data[start_byte:]
                if meeting.raw_transcript:
                    transcript_parts = meeting.raw_transcript.split("\n")
            else:
                pcm_data_to_send = pcm_data
                meeting.done_chunks = 0
                await db.commit()

            async def save_progress(chunk_idx: int):
                """Helper to sync partial transcript and progress to DB."""
                try:
                    meeting.raw_transcript = "\n".join(transcript_parts)
                    meeting.done_chunks = min(chunk_idx + 1, total_chunks)
                    await db.commit()
                except Exception as e:
                    logger.error("Error saving progress for meeting %s: %s", meeting_id, e)
                    await db.rollback()

            # Transcribe audio (real-time segments will trigger on_result)
            await client.transcribe_full(pcm_data_to_send)

            # Final save and finish ASR stage
            meeting.raw_transcript = "\n".join(transcript_parts)
            meeting.done_chunks = total_chunks
            meeting.end_time = datetime.utcnow()
            await db.commit()

            raw_transcript = "\n".join(transcript_parts)

            if not raw_transcript.strip():
                meeting.status = "completed"
                await db.commit()
                logger.info("Meeting %s: ASR returned no text, ending.", meeting_id)
                return

            # 2. Run AI pipeline (using MiMo-V2-Pro)
            logger.info("Meeting %s: Starting AI pipeline (switching status to polishing)", meeting_id)
            meeting.status = "polishing"
            await db.commit()

            # Re-load row so ``kb_project_id`` set during transcription
            # (via PUT /project) is visible in this long-lived session.
            await db.refresh(meeting)

            # KB docs or internal meeting history for stakeholder enrichment.
            kb_docs = await _stakeholder_reference_docs(
                meeting_id, meeting.kb_project_id, db
            )

            pipeline = MeetingAIPipeline(
                openai_api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL, 
                base_url=settings.OPENAI_BASE_URL or None,
            )
            result = await pipeline.process(
                raw_transcript=raw_transcript,
                meeting_title=meeting.title,
                meeting_id=meeting_id,
                kb_docs=kb_docs,
            )

            meeting.polished_transcript = result.get("polished_transcript", "")
            meeting.meeting_minutes = json.dumps(result.get("meeting_minutes", {}), ensure_ascii=False)
            meeting.stakeholder_map = json.dumps(
                result.get("stakeholder_map", {"stakeholders": [], "relations": []}),
                ensure_ascii=False,
            )
            meeting.status = "completed"
            await db.commit()

            # 3. Save requirements
            for idx, req in enumerate(result.get("requirements", [])):
                db.add(Requirement(
                    meeting_id=meeting_id,
                    req_id=req.get("id", f"REQ-{idx + 1:03d}"),
                    module=req.get("module", ""),
                    description=req.get("description", ""),
                    priority=req.get("priority", "P2"),
                    source=req.get("source", ""),
                    speaker=req.get("speaker", ""),
                    status="待确认",
                ))
            await db.commit()
            logger.info("Meeting %s: Workflow complete", meeting_id)

        except Exception as exc:
            logger.exception("Background workflow failed for meeting %s", meeting_id)
            meeting.status = "failed"
            await db.commit()


@router.post("/{meeting_id}/resume")
async def resume_meeting(
    meeting_id: int, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session)
) -> dict:
    """Resume a failed or interrupted meeting from disk."""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    upload_path = os.path.join(settings.UPLOAD_DIR, f"{meeting.id}.pcm")
    if not os.path.exists(upload_path):
        raise HTTPException(status_code=400, detail="Audio file not found on disk. Cannot resume.")
    
    # Read PCM from disk
    try:
        with open(upload_path, "rb") as f:
            pcm_data = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read audio file: {e}")
    
    meeting.status = "transcribing"
    await db.commit()
    
    background_tasks.add_task(run_meeting_workflow, meeting.id, pcm_data)
    return {"status": "resuming", "done_chunks": meeting.done_chunks, "total_chunks": meeting.total_chunks}

async def run_manual_polish(meeting_id: int):
    from backend.database import async_session_factory
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting or not meeting.raw_transcript: return
        pipeline = MeetingAIPipeline(openai_api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL, base_url=settings.OPENAI_BASE_URL)
        result = await pipeline.process(raw_transcript=meeting.raw_transcript, meeting_title=meeting.title)
        meeting.polished_transcript = result.get("polished_transcript", "")
        meeting.status = "completed"
        await db.commit()

async def run_manual_summarize(meeting_id: int):
    from backend.database import async_session_factory
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting or not meeting.raw_transcript: return
        pipeline = MeetingAIPipeline(openai_api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL, base_url=settings.OPENAI_BASE_URL)
        result = await pipeline.process(raw_transcript=meeting.raw_transcript, meeting_title=meeting.title)
        meeting.meeting_minutes = json.dumps(result.get("meeting_minutes", {}), ensure_ascii=False)
        meeting.status = "completed"
        await db.commit()

async def run_manual_extract(meeting_id: int):
    from backend.database import async_session_factory
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting or not meeting.raw_transcript: return
        pipeline = MeetingAIPipeline(openai_api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL, base_url=settings.OPENAI_BASE_URL)
        result = await pipeline.process(raw_transcript=meeting.raw_transcript, meeting_title=meeting.title)
        await db.execute(sql_delete(Requirement).where(Requirement.meeting_id == meeting_id))
        for idx, req in enumerate(result.get("requirements", [])):
            db.add(Requirement(
                meeting_id=meeting_id,
                req_id=req.get("id", f"REQ-{idx + 1:03d}"),
                module=req.get("module", ""),
                description=req.get("description", ""),
                priority=req.get("priority", "P2"),
                source=req.get("source", ""),
                speaker=req.get("speaker", ""),
                status="待确认",
            ))
        meeting.status = "completed"
        await db.commit()

@router.post("/{meeting_id}/actions/polish")
async def manual_polish(
    meeting_id: int, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session)
) -> dict:
    """Manually trigger AI polishing in background."""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting or not meeting.raw_transcript:
        raise HTTPException(status_code=400, detail="Meeting or transcript not found")
    meeting.status = "polishing"
    await db.commit()
    background_tasks.add_task(run_manual_polish, meeting_id)
    return {"status": "processing"}

@router.post("/{meeting_id}/actions/summarize")
async def manual_summarize(
    meeting_id: int, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session)
) -> dict:
    """Manually trigger AI summarization in background."""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting or not meeting.raw_transcript:
        raise HTTPException(status_code=400, detail="Meeting or transcript not found")
    meeting.status = "processing"
    await db.commit()
    background_tasks.add_task(run_manual_summarize, meeting_id)
    return {"status": "processing"}

@router.post("/{meeting_id}/actions/extract_requirements")
async def manual_extract_requirements(
    meeting_id: int, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session)
) -> dict:
    """Manually trigger requirement extraction in background."""
    meeting = await db.get(Meeting, meeting_id)
    if not meeting or not meeting.raw_transcript:
        raise HTTPException(status_code=400, detail="Meeting or transcript not found")
    meeting.status = "processing"
    await db.commit()
    background_tasks.add_task(run_manual_extract, meeting_id)
    return {"status": "processing"}
