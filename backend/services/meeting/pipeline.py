"""会议纪要 AI pipeline 四阶段实现。

每个阶段都通过 kb-system 的 model_router 调用 LLM,自动 fallback。
对 JSON 输出阶段统一加 response_format 强制 + 解析容错。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog

from prompts.meeting import (
    POLISH_SYSTEM,
    POLISH_USER,
    MINUTES_SYSTEM,
    MINUTES_USER,
    REQUIREMENT_SYSTEM,
    REQUIREMENT_USER,
    STAKEHOLDER_SYSTEM,
    STAKEHOLDER_USER,
)
from services.model_router import model_router

logger = structlog.get_logger()


# ── JSON 解析容错 ────────────────────────────────────────────────────────

def _strip_code_fence(text: str) -> str:
    """剥 ```json ... ``` 围栏,留纯 JSON。"""
    s = text.strip()
    if s.startswith("```"):
        # 去掉第一行和最后一行
        lines = s.split("\n")
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            s = "\n".join(lines[1:-1]).strip()
        elif len(lines) >= 2:
            s = "\n".join(lines[1:]).strip()
            if s.endswith("```"):
                s = s[: s.rfind("```")].strip()
    return s


def _safe_json_loads(text: str, default: Any) -> Any:
    """容错 JSON 解析。失败返回 default,顺便记一条 warning。"""
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as e:
        # 尝试抓第一个 { 到最后一个 } 之间的 JSON
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning("meeting_json_parse_failed", error=str(e)[:80], raw=cleaned[:200])
        return default


# ── 阶段 1:润色 ─────────────────────────────────────────────────────────

async def polish_transcript(raw_transcript: str) -> str:
    """对 ASR 原始转写做语言润色。返回纯文本。"""
    if not raw_transcript or not raw_transcript.strip():
        return ""

    messages = [
        {"role": "system", "content": POLISH_SYSTEM},
        {"role": "user", "content": POLISH_USER.format(raw_transcript=raw_transcript)},
    ]
    content, model = await model_router.chat_with_routing(
        task="doc_generation",
        messages=messages,
        temperature=0.2,
        max_tokens=16000,
    )
    logger.info("polish_done", model=model, in_chars=len(raw_transcript), out_chars=len(content))
    return content.strip()


# ── 阶段 2:纪要 ─────────────────────────────────────────────────────────

_EMPTY_MINUTES = {
    # 元信息(2026-05-12 加,对齐纷享销客实施纪要模板表头字段)
    "meeting_title": "",
    "meeting_time": "",
    "meeting_location": "",
    "meeting_host": "",
    "meeting_recorder": "",
    "meeting_format": "",
    "organizer": "",
    # 正文内容
    "summary": "",
    "attendees": [],
    "key_points": [],
    "decisions": [],
    "action_items": [],
    "unresolved": [],
}


async def generate_minutes(transcript: str, meeting_title: str = "") -> dict:
    """从润色后的 transcript 生成结构化纪要。返回 dict。"""
    if not transcript or not transcript.strip():
        return dict(_EMPTY_MINUTES)

    messages = [
        {"role": "system", "content": MINUTES_SYSTEM},
        {
            "role": "user",
            "content": MINUTES_USER.format(
                meeting_title=meeting_title or "(未指定)",
                transcript=transcript,
            ),
        },
    ]
    content, model = await model_router.chat_with_routing(
        task="doc_generation",
        messages=messages,
        temperature=0.2,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    result = _safe_json_loads(content, dict(_EMPTY_MINUTES))
    logger.info(
        "minutes_done",
        model=model,
        keys=list(result.keys()) if isinstance(result, dict) else None,
    )
    return result


# ── 阶段 3:需求提取 ────────────────────────────────────────────────────

async def extract_requirements(transcript: str) -> list[dict]:
    """提取 CRM 实施需求。返回需求 dict 列表。"""
    if not transcript or not transcript.strip():
        return []

    messages = [
        {"role": "system", "content": REQUIREMENT_SYSTEM},
        {"role": "user", "content": REQUIREMENT_USER.format(transcript=transcript)},
    ]
    content, model = await model_router.chat_with_routing(
        task="doc_generation",
        messages=messages,
        temperature=0.2,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    result = _safe_json_loads(content, {"requirements": []})
    # 兼容模型直接吐数组的情况
    items = result.get("requirements", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
    # 字段兜底 + req_id 重编号
    cleaned: list[dict] = []
    for idx, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        cleaned.append({
            "req_id": raw.get("req_id") or f"REQ-{idx:03d}",
            "module": (raw.get("module") or "").strip(),
            "description": (raw.get("description") or "").strip(),
            "priority": raw.get("priority") or "P2",
            "source": (raw.get("source") or "").strip() or None,
            "speaker": (raw.get("speaker") or "").strip() or None,
            "status": "待确认",
        })
    logger.info("requirements_done", model=model, count=len(cleaned))
    return cleaned


# ── 阶段 4:干系人图谱 ─────────────────────────────────────────────────

_EMPTY_STAKEHOLDERS = {"stakeholders": [], "relations": []}


def _render_kb_docs(kb_docs: list[dict] | None) -> str:
    """把可选的 KB 文档渲染成 prompt 注入块。"""
    if not kb_docs:
        return "(无)"
    lines = []
    for d in kb_docs[:5]:  # 防止 prompt 过长
        title = d.get("filename") or d.get("name") or "未命名"
        summary = (d.get("summary") or d.get("markdown_content", "") or "")[:1200]
        lines.append(f"## 文档:{title}\n{summary}\n")
    return "\n".join(lines)


async def extract_stakeholders(
    meeting_id: int,
    meeting_title: str,
    transcript: str,
    minutes: dict | None = None,
    kb_docs: list[dict] | None = None,
) -> dict:
    """提取干系人图谱。返回 {stakeholders: [...], relations: [...]}。"""
    if not transcript or not transcript.strip():
        return dict(_EMPTY_STAKEHOLDERS)

    messages = [
        {"role": "system", "content": STAKEHOLDER_SYSTEM},
        {
            "role": "user",
            "content": STAKEHOLDER_USER.format(
                meeting_id=meeting_id,
                meeting_title=meeting_title or "(未指定)",
                transcript=transcript[:30000],  # 防超长
                minutes=json.dumps(minutes or {}, ensure_ascii=False),
                kb_docs=_render_kb_docs(kb_docs),
            ),
        },
    ]
    content, model = await model_router.chat_with_routing(
        task="doc_generation",
        messages=messages,
        temperature=0.2,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    result = _safe_json_loads(content, dict(_EMPTY_STAKEHOLDERS))
    if not isinstance(result, dict):
        result = dict(_EMPTY_STAKEHOLDERS)
    result.setdefault("stakeholders", [])
    result.setdefault("relations", [])
    logger.info(
        "stakeholders_done",
        model=model,
        count=len(result.get("stakeholders", [])),
        relations=len(result.get("relations", [])),
    )
    return result


# ── 全流程编排 ──────────────────────────────────────────────────────────

async def run_full_pipeline(
    raw_transcript: str,
    meeting_id: int,
    meeting_title: str = "",
    kb_docs: list[dict] | None = None,
) -> dict:
    """串行 + 并行编排:polish → (minutes ∥ requirements) → stakeholders。

    返回 {polished_transcript, meeting_minutes, requirements, stakeholder_map}。
    任何一阶段失败不阻断后续(降级为空结果),由调用方在 DB 里反映 status。
    """
    logger.info("pipeline_start", meeting_id=meeting_id, in_chars=len(raw_transcript))

    # Step 1: 润色
    try:
        polished = await polish_transcript(raw_transcript)
    except Exception as e:
        logger.exception("polish_failed", error=str(e)[:200])
        polished = raw_transcript  # 失败时直接用原文

    # Step 2 & 3: 并行
    minutes_task = asyncio.create_task(generate_minutes(polished, meeting_title))
    reqs_task = asyncio.create_task(extract_requirements(polished))
    minutes, requirements = await asyncio.gather(
        minutes_task, reqs_task, return_exceptions=True
    )
    if isinstance(minutes, Exception):
        logger.exception("minutes_failed", error=str(minutes)[:200])
        minutes = dict(_EMPTY_MINUTES)
    if isinstance(requirements, Exception):
        logger.exception("requirements_failed", error=str(requirements)[:200])
        requirements = []

    # Step 4: 干系人(可选,失败不阻断)
    stakeholder_map: dict = dict(_EMPTY_STAKEHOLDERS)
    try:
        stakeholder_map = await extract_stakeholders(
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            transcript=polished,
            minutes=minutes if isinstance(minutes, dict) else None,
            kb_docs=kb_docs,
        )
    except Exception as e:
        logger.exception("stakeholders_failed", error=str(e)[:200])

    logger.info(
        "pipeline_done",
        meeting_id=meeting_id,
        kp=len(minutes.get("key_points", [])) if isinstance(minutes, dict) else 0,
        reqs=len(requirements),
        stakeholders=len(stakeholder_map.get("stakeholders", [])),
    )
    return {
        "polished_transcript": polished,
        "meeting_minutes": minutes,
        "requirements": requirements,
        "stakeholder_map": stakeholder_map,
    }
