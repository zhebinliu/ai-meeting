"""会议同步到 kb-system 知识库 — 内部 service(2026-05-11)。

替代 meeting-ai 原 KBClient 的 HTTP 调用,直接构造 Document ORM 对象并写库。
两类同步:
1. sync_minutes:把 meeting_minutes(JSON)渲染成 markdown,作为 doc_type=meeting_notes 入库
2. sync_stakeholders:把 stakeholder_map(JSON)渲染成 markdown,作为 doc_type=stakeholder_map 入库
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document
from models.meeting import Meeting
from services._time import utcnow_naive as _utcnow

logger = structlog.get_logger()


# ── markdown 渲染 ──────────────────────────────────────────────────

def render_minutes_markdown(meeting: Meeting) -> str:
    """会议纪要 JSON → markdown。容错:任一字段缺失走默认。"""
    title = meeting.title or "未命名会议"
    minutes = meeting.meeting_minutes or {}
    if not isinstance(minutes, dict):
        minutes = {}

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if meeting.start_time:
        lines.append(f"_会议时间:{meeting.start_time.strftime('%Y-%m-%d %H:%M')}_")
        lines.append("")

    summary = minutes.get("summary") or ""
    if summary:
        lines.append("## 会议摘要")
        lines.append(summary.strip())
        lines.append("")

    attendees = minutes.get("attendees") or []
    if attendees:
        lines.append("## 参会人员")
        lines.append("、".join(str(a) for a in attendees))
        lines.append("")

    kps = minutes.get("key_points") or []
    if kps:
        lines.append("## 关键议题")
        for kp in kps:
            if isinstance(kp, dict):
                lines.append(f"- **{kp.get('topic', '议题')}**: {kp.get('content', '')}")
            else:
                lines.append(f"- {kp}")
        lines.append("")

    decisions = minutes.get("decisions") or []
    if decisions:
        lines.append("## 决议事项")
        for d in decisions:
            if isinstance(d, dict):
                owner = d.get("owner") or ""
                line = f"- {d.get('content', '')}"
                if owner:
                    line += f"(负责人:{owner})"
                lines.append(line)
            else:
                lines.append(f"- {d}")
        lines.append("")

    actions = minutes.get("action_items") or []
    if actions:
        lines.append("## 待办事项")
        for a in actions:
            if isinstance(a, dict):
                parts = [a.get("task", "")]
                if a.get("owner"):
                    parts.append(f"负责人:{a['owner']}")
                if a.get("deadline"):
                    parts.append(f"截止:{a['deadline']}")
                if a.get("priority"):
                    parts.append(f"优先级:{a['priority']}")
                lines.append("- " + " · ".join(p for p in parts if p))
            else:
                lines.append(f"- {a}")
        lines.append("")

    unresolved = minutes.get("unresolved") or []
    if unresolved:
        lines.append("## 未决问题")
        for u in unresolved:
            if isinstance(u, dict):
                line = f"- {u.get('issue', '')}"
                if u.get("reason"):
                    line += f"(原因:{u['reason']})"
                lines.append(line)
            else:
                lines.append(f"- {u}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_stakeholders_markdown(meeting: Meeting) -> str:
    """干系人图谱 JSON → markdown。"""
    title = meeting.title or "未命名会议"
    smap = meeting.stakeholder_map or {}
    if not isinstance(smap, dict):
        smap = {}

    lines: list[str] = []
    lines.append(f"# {title} · 干系人图谱")
    lines.append("")
    if meeting.start_time:
        lines.append(f"_会议时间:{meeting.start_time.strftime('%Y-%m-%d %H:%M')}_")
        lines.append("")

    holders = smap.get("stakeholders") or []
    if holders:
        lines.append("## 干系人")
        for h in holders:
            if not isinstance(h, dict):
                continue
            name = h.get("name") or "(未命名)"
            role = h.get("role") or ""
            org = h.get("organization") or ""
            side = h.get("side") or ""
            head = f"### {name}"
            tail_bits = [b for b in (role, org, side) if b]
            if tail_bits:
                head += "(" + " / ".join(tail_bits) + ")"
            lines.append(head)
            if h.get("aliases"):
                lines.append(f"- 别名:{', '.join(str(a) for a in h['aliases'])}")
            if h.get("responsibilities"):
                lines.append(f"- 职责:{', '.join(str(r) for r in h['responsibilities'])}")
            if h.get("key_points"):
                lines.append(f"- 关键观点:{', '.join(str(p) for p in h['key_points'])}")
            if h.get("contact"):
                lines.append(f"- 联系方式:{h['contact']}")
            lines.append("")
    else:
        lines.append("_(未识别出干系人)_")
        lines.append("")

    relations = smap.get("relations") or []
    if relations:
        lines.append("## 协作关系")
        for r in relations:
            if not isinstance(r, dict):
                continue
            line = f"- **{r.get('from', '?')}** → **{r.get('to', '?')}**"
            if r.get("type"):
                line += f"({r['type']})"
            if r.get("description"):
                line += f": {r['description']}"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ── 写入 Document 表 ──────────────────────────────────────────────

async def _create_kb_document(
    session: AsyncSession,
    filename: str,
    markdown: str,
    doc_type: str,
    project_id: Optional[str],
    uploader_id: Optional[str],
) -> Document:
    doc = Document(
        filename=filename,
        original_format="md",
        markdown_content=markdown,
        file_path=None,
        conversion_status="completed",
        uploader_id=uploader_id,
        project_id=project_id,
        doc_type=doc_type,
    )
    session.add(doc)
    await session.flush()  # 拿 id
    return doc


# ── 公开 API ──────────────────────────────────────────────────────

async def sync_minutes_to_kb(session: AsyncSession, meeting: Meeting, uploader_id: str) -> tuple[str, str]:
    """同步会议纪要到 KB。返回 (doc_id, frontend_url)。"""
    markdown = render_minutes_markdown(meeting)
    date_str = (meeting.start_time or _utcnow()).strftime("%Y%m%d")
    filename = f"会议纪要-{meeting.title or '未命名'}-{date_str}.md"
    doc = await _create_kb_document(
        session=session,
        filename=filename,
        markdown=markdown,
        doc_type="meeting_notes",
        project_id=meeting.project_id,
        uploader_id=uploader_id,
    )
    meeting.kb_doc_id = doc.id
    meeting.kb_url = f"/documents/{doc.id}"  # kb-system 前端路由
    meeting.kb_synced_at = _utcnow()
    logger.info("meeting_synced_to_kb", meeting_id=meeting.id, doc_id=doc.id)
    return doc.id, meeting.kb_url


async def sync_stakeholders_to_kb(session: AsyncSession, meeting: Meeting, uploader_id: str) -> tuple[str, str]:
    """同步干系人图谱到 KB。返回 (doc_id, frontend_url)。"""
    markdown = render_stakeholders_markdown(meeting)
    date_str = (meeting.start_time or _utcnow()).strftime("%Y%m%d")
    filename = f"干系人图谱-{meeting.title or '未命名'}-{date_str}.md"
    doc = await _create_kb_document(
        session=session,
        filename=filename,
        markdown=markdown,
        doc_type="stakeholder_map",
        project_id=meeting.project_id,
        uploader_id=uploader_id,
    )
    meeting.stakeholder_kb_doc_id = doc.id
    meeting.stakeholder_kb_url = f"/documents/{doc.id}"
    meeting.stakeholder_kb_synced_at = _utcnow()
    logger.info("meeting_stakeholders_synced_to_kb", meeting_id=meeting.id, doc_id=doc.id)
    return doc.id, meeting.stakeholder_kb_url
