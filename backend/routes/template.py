"""Template CRUD and evolution API routes.

Provides endpoints to list, create, activate templates and trigger
the template evolution process.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.template import MeetingTemplate
from backend.services.ai.template_evolver import TemplateEvolver, _template_to_dict
from backend.services.ai.llm_client import LLMClient
from backend.config import settings
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["templates"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TemplateCreate(BaseModel):
    """Payload for manually creating a template."""
    name: str = Field(default="自定义模板")
    description: str = Field(default="")
    schema_structure: str = Field(default="")
    format_requirements: str = Field(default="")
    style_preferences: str = Field(default="")
    change_log: str = Field(default="")


class TemplateOut(BaseModel):
    """Serialised template response."""
    id: int
    name: str
    description: str
    schema_structure: str
    format_requirements: str
    style_preferences: str
    version: int
    is_active: bool
    source_meeting_ids: list[int]
    source_kb_doc_refs: list[str]
    evolution_method: str
    change_log: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helper: get evolver instance
# ---------------------------------------------------------------------------


def _evolver() -> TemplateEvolver:
    llm = LLMClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
        base_url=settings.OPENAI_BASE_URL or None,
    )
    return TemplateEvolver(llm)


async def _run_evolve(method: str) -> None:
    """Background task to run template evolution."""
    try:
        evolver = _evolver()
        template = await evolver.evolve(method=method)
        logger.info(
            "Template evolution completed: v%s (id=%s)",
            template.version,
            template.id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Template evolution background task failed")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[dict])
async def list_templates(
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all templates, ordered by version descending."""
    result = await db.execute(
        select(MeetingTemplate).order_by(MeetingTemplate.version.desc())
    )
    templates = list(result.scalars().all())
    return [_template_to_dict(t) for t in templates]


@router.get("/active", response_model=dict)
async def get_active_template(
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Return the currently active template, or an empty dict."""
    result = await db.execute(
        select(MeetingTemplate)
        .where(MeetingTemplate.is_active == True)  # noqa: E712
        .limit(1)
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        return {}
    return _template_to_dict(tpl)


@router.get("/{template_id}", response_model=dict)
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Get a single template by ID."""
    tpl = await db.get(MeetingTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_dict(tpl)


@router.post("", response_model=dict, status_code=201)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Manually create a new template (does not auto-activate)."""
    # Determine next version
    latest_result = await db.execute(
        select(MeetingTemplate).order_by(MeetingTemplate.version.desc()).limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    template = MeetingTemplate(
        name=payload.name,
        description=payload.description,
        schema_structure=payload.schema_structure,
        format_requirements=payload.format_requirements,
        style_preferences=payload.style_preferences,
        version=next_version,
        is_active=False,
        source_meeting_ids="[]",
        source_kb_doc_refs="[]",
        evolution_method="manual",
        change_log=payload.change_log or "手动创建",
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    logger.info("Created template id=%s v%s", template.id, template.version)
    return _template_to_dict(template)


@router.post("/{template_id}/activate", response_model=dict)
async def activate_template(
    template_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Set a specific template as the active one (deactivates others)."""
    tpl = await db.get(MeetingTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Deactivate all, then activate the chosen one
    from sqlalchemy import text as _text
    await db.execute(
        _text("UPDATE meeting_templates SET is_active = 0 WHERE is_active = 1")
    )
    tpl.is_active = True
    await db.commit()
    await db.refresh(tpl)
    logger.info("Activated template id=%s v%s", tpl.id, tpl.version)
    return _template_to_dict(tpl)


@router.post("/evolve", response_model=dict)
async def evolve_template(
    background_tasks: BackgroundTasks,
    method: str = Query(
        default="combined",
        description="Evolution method: user_edit / kb_analysis / combined",
    ),
) -> dict:
    """Trigger template evolution in the background.

    The evolution process:
    1. Collects user-edited meetings and/or KB meeting documents.
    2. Sends an LLM analysis request to derive improved template settings.
    3. Creates a new template version and activates it.

    Returns immediately with a tracking message.
    """
    if method not in ("user_edit", "kb_analysis", "combined"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid method '{method}'. Must be one of: user_edit, kb_analysis, combined.",
        )
    background_tasks.add_task(_run_evolve, method)
    return {
        "status": "evolution_scheduled",
        "method": method,
        "message": "Template evolution started in the background. "
        "Poll GET /api/templates/active to see when a new version appears.",
    }
