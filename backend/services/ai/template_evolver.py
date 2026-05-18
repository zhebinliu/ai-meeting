"""Template evolution service.

Analyses user-edited minutes and KB project meeting documents to derive
improved meeting minutes templates that are injected into the AI prompt
during generation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session_factory
from backend.models.meeting import Meeting
from backend.models.template import MeetingTemplate
from backend.services.ai.llm_client import LLMClient
from backend.services.ai.prompts import MINUTES_SYSTEM

logger = logging.getLogger(__name__)

# How many user-edited meetings to consider for one evolution pass
_MAX_EDITED_SAMPLE = 20
# How many KB docs to fetch at most
_MAX_KB_SAMPLE = 30

# System prompt for the LLM template analysis
_TEMPLATE_ANALYSIS_SYSTEM = (
    "你是一位资深的文档格式分析专家，擅长从大量会议纪要样本中提炼出最佳模板结构。\n"
    "\n"
    "你的任务是比较用户手动编辑后的会议纪要（编辑版）与 AI 原始生成的会议纪要（原始版），\n"
    "同时参考知识库中其他项目的会议纪要文档格式，综合得出一个更优的会议纪要模板。\n"
    "\n"
    "## 分析要点\n"
    "1. **结构差异**：编辑版比原始版增加了哪些字段/章节？删减了什么？改变了顺序吗？\n"
    "2. **格式偏好**：用户是否倾向于更详细或更简洁的表述？使用了什么特殊格式？\n"
    "3. **风格特点**：语气是正式还是随意？是否更注重数据/时间/负责人等细节？\n"
    "4. **KB 参考**：知识库中的会议纪要文档采用了什么结构？有什么值得借鉴的格式规范？\n"
    "5. **通用模式**：哪些差异是编辑者个人的（不应纳入模板），哪些是普遍偏好（应纳入模板）？\n"
    "\n"
    "## 输出要求\n"
    "必须严格按以下 JSON 格式输出，仅输出 JSON 本身，不要包含任何其他文字或代码块标记：\n"
    "{\n"
    '  "change_log": "版本变更说明（50-200字，描述本版本与上一版的区别）",\n'
    '  "format_requirements": "自然语言描述的格式要求段落（将被注入 AI system prompt）",\n'
    '  "style_preferences": "自然语言描述的风格偏好段落（将被注入 AI system prompt）",\n'
    '  "schema_structure": {"字段定义描述字符串"},  // 期望的 JSON 输出结构的文本描述\n'
    '  "source_meeting_ids": [1, 2, 3],  // 贡献本模板的本地会议 ID 列表\n'
    '  "source_kb_doc_refs": ["kb_doc_id_1", "kb_doc_id_2"]  // 贡献本模板的 KB 文档引用列表\n'
    "}"
)

_USER_ANALYSIS_TEMPLATE = """## 原始 AI 生成版 vs 用户编辑版对比

以下展示了 {count} 个会议的 AI 原始生成版本与用户手动编辑版本的结构差异。
请分析用户编辑的共性趋势，提取出可纳入模板改进的模式。

{comparisons}

## 知识库会议纪要文档结构参考

以下展示了 {kb_count} 个知识库中其他项目的会议纪要文档的结构和格式特点，
可作为模板迭代的参考素材。

{kb_docs}

请综合以上信息，输出改进后的模板定义。"""


def _safe_json(val: str, default=None):
    """Parse JSON safely."""
    if not val:
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def _minutes_to_comparable(minutes_str: str) -> str:
    """Normalise a minutes JSON string into a comparable text block."""
    obj = _safe_json(minutes_str, {})
    if not isinstance(obj, dict):
        return str(obj)[:500]
    parts: list[str] = []
    for key in ("summary", "meeting_title", "meeting_date"):
        v = obj.get(key)
        if v:
            parts.append(f"[{key}] {v}")
    for key, label in (
        ("attendees", "参会人员"),
        ("key_points", "讨论要点"),
        ("decisions", "决策事项"),
        ("action_items", "待办事项"),
        ("unresolved", "未决问题"),
    ):
        items = obj.get(key)
        if not items:
            continue
        if isinstance(items, list) and items:
            parts.append(f"\n[{label}]")
            for item in items[:10]:
                if isinstance(item, dict):
                    text = json.dumps(item, ensure_ascii=False)[:200]
                elif isinstance(item, str):
                    text = item[:200]
                else:
                    text = str(item)[:200]
                parts.append(f"  - {text}")
    return "\n".join(parts)


def _format_comparison(
    meeting_id: int,
    title: str,
    original: str,
    edited: str,
) -> str:
    """Format a single comparison pair for the LLM."""
    o = _minutes_to_comparable(original)
    e = _minutes_to_comparable(edited)
    return (
        f"\n----- 会议 ID: {meeting_id} | 标题: {title} -----\n"
        f"[AI 原始版]:\n{o[:1000]}\n\n"
        f"[用户编辑版]:\n{e[:1000]}\n"
    )


class TemplateEvolutionError(RuntimeError):
    """Raised when template evolution fails."""


class TemplateEvolver:
    """Orchestrates template evolution from user edits and KB docs."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evolve(self, method: str = "combined") -> MeetingTemplate:
        """Run a full evolution cycle.

        Args:
            method: Evolution data source -- ``user_edit``, ``kb_analysis``,
                    or ``combined`` (default).

        Returns:
            The newly created (and activated) :class:`MeetingTemplate`.

        Raises:
            TemplateEvolutionError: If there is insufficient data to evolve,
                or the LLM analysis itself fails.
        """
        # 1. Collect data
        edited_meetings = await self._collect_edited_meetings()
        kb_docs = await self._fetch_kb_meeting_docs()

        use_edits = method in ("user_edit", "combined") and bool(edited_meetings)
        use_kb = method in ("kb_analysis", "combined") and bool(kb_docs)

        if not use_edits and not use_kb:
            raise TemplateEvolutionError(
                "No data available for evolution. Need at least one user-edited "
                "meeting or KB meeting documents."
            )

        # 2. Build analysis input
        analysis_input = self._build_analysis_input(
            edited_meetings if use_edits else [],
            kb_docs if use_kb else [],
        )

        # 3. Run LLM analysis
        llm_output = await self._analyze_with_llm(analysis_input)

        # 4. Create and persist new template
        template = await self._create_template_from_analysis(
            llm_output,
            method=method,
        )

        return template

    async def get_evolvable_system_prompt(self) -> str:
        """Return the MINUTES_SYSTEM augmented with the active template."""
        template_dict = await get_active_template_dict()
        return _build_system_prompt_from_dict(template_dict)

    async def get_active_template(self) -> Optional[MeetingTemplate]:
        """Return the currently active template, or None."""
        return await self._get_current_active_template()

    async def get_active_template_dict(self) -> dict[str, Any]:
        """Return active template as a dict (for API serialisation)."""
        return await get_active_template_dict()

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def _collect_edited_meetings(self) -> list[tuple[Meeting, dict]]:
        """Return (meeting, edited_dict) pairs where users edited the minutes."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(Meeting)
                .where(
                    and_(
                        Meeting.edited_minutes.isnot(None),
                        Meeting.edited_minutes != "",
                        Meeting.meeting_minutes.isnot(None),
                        Meeting.meeting_minutes != "",
                    )
                )
                .order_by(Meeting.created_at.desc())
                .limit(_MAX_EDITED_SAMPLE)
            )
            meetings: list[Meeting] = list(result.scalars().all())

        pairs: list[tuple[Meeting, dict]] = []
        for m in meetings:
            edited = _safe_json(m.edited_minutes, None)
            if edited and isinstance(edited, dict):
                pairs.append((m, edited))
        logger.info("TemplateEvolver: collected %d edited meetings", len(pairs))
        return pairs

    async def _fetch_kb_meeting_docs(self) -> list[dict[str, Any]]:
        """Fetch meeting-note documents from the KB across all projects.

        Best-effort -- returns empty list on any failure.
        """
        try:
            from backend.services.kb_client import KBClient, KBNotConfigured, KBError
            try:
                client = KBClient()
            except KBNotConfigured:
                return []

            projects = await client.list_projects()
            docs: list[dict[str, Any]] = []
            for project in projects[:5]:  # limit to 5 projects
                pid = project.get("id")
                if not pid:
                    continue
                try:
                    summaries = await client.list_project_documents(pid)
                except KBError:
                    continue
                for s in (summaries or [])[:_MAX_KB_SAMPLE // 5]:
                    doc_id = s.get("id")
                    if not doc_id:
                        continue
                    try:
                        detail = await client.get_document(doc_id)
                    except KBError:
                        continue
                    if not detail:
                        continue
                    # Only keep documents that look like meeting notes
                    filename = (detail.get("filename") or "").lower()
                    summary = (detail.get("summary") or "").lower()
                    is_meeting = (
                        "会议" in filename
                        or "meeting" in filename
                        or "会议" in summary
                    )
                    if is_meeting and (detail.get("markdown_content") or "").strip():
                        docs.append(detail)
                        if len(docs) >= _MAX_KB_SAMPLE:
                            break
                if len(docs) >= _MAX_KB_SAMPLE:
                    break
            logger.info(
                "TemplateEvolver: collected %d KB meeting docs", len(docs)
            )
            return docs
        except Exception:  # noqa: BLE001
            logger.exception("TemplateEvolver: KB fetch failed")
            return []

    # ------------------------------------------------------------------
    # LLM analysis
    # ------------------------------------------------------------------

    def _build_analysis_input(
        self,
        edited_meetings: list[tuple[Meeting, dict]],
        kb_docs: list[dict[str, Any]],
    ) -> str:
        """Assemble the user message for LLM analysis."""
        comparisons: list[str] = []
        for meeting, edited in edited_meetings[:12]:  # cap at 12 samples
            comparisons.append(
                _format_comparison(
                    meeting_id=meeting.id,
                    title=meeting.title,
                    original=meeting.meeting_minutes or "{}",
                    edited=json.dumps(edited, ensure_ascii=False),
                )
            )

        kb_texts: list[str] = []
        for doc in kb_docs[:15]:
            filename = doc.get("filename", "")
            content = (doc.get("markdown_content") or "")[:800]
            summary = (doc.get("summary") or "")[:300]
            kb_texts.append(
                f"\n----- KB 文档: {filename} -----\n"
                f"摘要: {summary}\n"
                f"内容片段: {content}\n"
            )

        return _USER_ANALYSIS_TEMPLATE.format(
            count=len(comparisons),
            comparisons="\n".join(comparisons),
            kb_count=len(kb_texts),
            kb_docs="\n".join(kb_texts),
        )

    async def _analyze_with_llm(self, analysis_input: str) -> dict[str, Any]:
        """Call the LLM to analyse samples and produce a template definition."""
        messages = [
            {"role": "system", "content": _TEMPLATE_ANALYSIS_SYSTEM},
            {"role": "user", "content": analysis_input},
        ]
        raw = await self._llm.chat(messages, temperature=0.4)
        return self._parse_analysis(raw)

    @staticmethod
    def _parse_analysis(raw: str) -> dict[str, Any]:
        """Parse the LLM JSON output."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else ""
        try:
            result = json.loads(text)
            logger.info("Template analysis parsed successfully")
            return result
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to parse template analysis: %s\nRaw: %s", exc, raw)
            raise TemplateEvolutionError(f"LLM output was not valid JSON: {exc}") from exc

    # ------------------------------------------------------------------
    # Template persistence
    # ------------------------------------------------------------------

    async def _create_template_from_analysis(
        self,
        analysis: dict[str, Any],
        method: str,
    ) -> MeetingTemplate:
        """Persist a new template version and activate it."""
        change_log = (analysis.get("change_log") or "").strip()
        format_req = (analysis.get("format_requirements") or "").strip()
        style_prefs = (analysis.get("style_preferences") or "").strip()
        schema_raw = analysis.get("schema_structure")
        source_meeting_ids = json.dumps(
            analysis.get("source_meeting_ids", []), ensure_ascii=False
        )
        source_kb_doc_refs = json.dumps(
            analysis.get("source_kb_doc_refs", []), ensure_ascii=False
        )

        schema_str: str = ""
        if isinstance(schema_raw, str):
            schema_str = schema_raw
        elif isinstance(schema_raw, dict):
            schema_str = json.dumps(schema_raw, ensure_ascii=False)
        elif schema_raw:
            schema_str = str(schema_raw)

        async with async_session_factory() as db:
            # Deactivate current active templates
            from sqlalchemy import text as _text
            await db.execute(
                _text("UPDATE meeting_templates SET is_active = 0 WHERE is_active = 1")
            )

            # Determine next version number
            latest_result = await db.execute(
                select(MeetingTemplate).order_by(MeetingTemplate.version.desc()).limit(1)
            )
            latest = latest_result.scalar_one_or_none()
            next_version = (latest.version + 1) if latest else 1

            template = MeetingTemplate(
                name=f"迭代模板 v{next_version}",
                description=f"由 AI 自动分析 {method} 数据后生成的模板。",
                schema_structure=schema_str,
                format_requirements=format_req,
                style_preferences=style_prefs,
                version=next_version,
                is_active=True,
                source_meeting_ids=source_meeting_ids,
                source_kb_doc_refs=source_kb_doc_refs,
                evolution_method=method,
                change_log=change_log or f"基于 {method} 数据自动演化",
            )
            db.add(template)
            await db.commit()
            await db.refresh(template)
            logger.info(
                "Template evolved to v%s (id=%s, method=%s)",
                next_version,
                template.id,
                method,
            )
            return template

    async def _get_current_active_template(self) -> Optional[MeetingTemplate]:
        """Fetch the currently active template from the database."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(MeetingTemplate)
                .where(MeetingTemplate.is_active == True)  # noqa: E712
                .limit(1)
            )
            return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Standalone helpers (usable without an LLMClient / TemplateEvolver instance)
# ---------------------------------------------------------------------------


async def get_active_template_dict() -> dict[str, Any]:
    """Fetch the currently active template as a plain dict.

    Can be called from route handlers without constructing an LLM client.
    Returns an empty dict if no active template exists.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            select(MeetingTemplate)
            .where(MeetingTemplate.is_active == True)  # noqa: E712
            .limit(1)
        )
        tpl = result.scalar_one_or_none()
        if tpl is None:
            return {}
        return _template_to_dict(tpl)


def _template_to_dict(tpl: MeetingTemplate) -> dict[str, Any]:
    """Convert a MeetingTemplate ORM row to a plain dict."""
    return {
        "id": tpl.id,
        "name": tpl.name,
        "description": tpl.description or "",
        "schema_structure": tpl.schema_structure or "",
        "format_requirements": tpl.format_requirements or "",
        "style_preferences": tpl.style_preferences or "",
        "version": tpl.version,
        "is_active": tpl.is_active,
        "source_meeting_ids": _safe_json(tpl.source_meeting_ids, []),
        "source_kb_doc_refs": _safe_json(tpl.source_kb_doc_refs, []),
        "evolution_method": tpl.evolution_method,
        "change_log": tpl.change_log or "",
        "created_at": tpl.created_at.isoformat() if tpl.created_at else "",
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else "",
    }


def _build_system_prompt_from_dict(template: Optional[dict]) -> str:
    """Augment the base MINUTES_SYSTEM with template preferences from a dict."""
    if not template:
        return MINUTES_SYSTEM
    parts = [MINUTES_SYSTEM]
    f = (template.get("format_requirements") or "").strip()
    s = (template.get("style_preferences") or "").strip()
    sc = (template.get("schema_structure") or "").strip()
    if f:
        parts.append(f"\n## 格式要求\n{f}\n")
    if s:
        parts.append(f"\n## 风格偏好\n{s}\n")
    if sc:
        parts.append(f"\n## 期望的输出结构\n{sc}\n")
    return "\n".join(parts)
