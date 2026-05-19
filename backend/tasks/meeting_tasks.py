"""会议纪要 Celery tasks:process_meeting + transcribe(Block C 接入)。

模式参考 output_tasks.py:同步 task 内用独立事件循环驱动 async 业务函数。
"""
import asyncio
from datetime import datetime

import structlog
from sqlalchemy import select, delete as sql_delete

from tasks.convert_task import celery_app

logger = structlog.get_logger()


def _run(coro):
    """同步运行异步函数。每次调用创建独立事件循环。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _process_meeting_async(meeting_id: int):
    """执行 AI pipeline 并写回 DB。状态机:processing → completed/failed。"""
    from models import async_session_maker
    from models.meeting import Meeting, Requirement
    from services._time import utcnow_naive
    from services.meeting import run_full_pipeline

    async with async_session_maker() as session:
        meeting = await session.get(Meeting, meeting_id)
        if not meeting:
            logger.error("meeting_not_found_for_processing", meeting_id=meeting_id)
            return
        if not meeting.raw_transcript or not meeting.raw_transcript.strip():
            logger.warning("meeting_skip_empty_transcript", meeting_id=meeting_id)
            meeting.status = "failed"
            await session.commit()
            return

        # 状态机进入 processing
        meeting.status = "processing"
        await session.commit()

        raw = meeting.raw_transcript
        title = meeting.title or ""

    # 跑 pipeline(脱离 session,避免 LLM 长时间持有连接)
    try:
        result = await run_full_pipeline(
            raw_transcript=raw,
            meeting_id=meeting_id,
            meeting_title=title,
            kb_docs=None,  # Block E 接 KB 联动后,这里读 project_id 拉 KB 文档
        )
    except Exception as e:
        logger.exception("meeting_pipeline_unhandled", meeting_id=meeting_id, error=str(e)[:200])
        async with async_session_maker() as session:
            m = await session.get(Meeting, meeting_id)
            if m:
                m.status = "failed"
                await session.commit()
        return

    # 写回 DB
    async with async_session_maker() as session:
        m = await session.get(Meeting, meeting_id)
        if not m:
            return
        m.polished_transcript = result.get("polished_transcript") or ""
        m.meeting_minutes = result.get("meeting_minutes") or {}
        m.stakeholder_map = result.get("stakeholder_map") or {}
        m.status = "completed"
        m.end_time = utcnow_naive()

        # 重建需求清单(覆盖式)
        await session.execute(sql_delete(Requirement).where(Requirement.meeting_id == meeting_id))
        for raw_req in result.get("requirements", []):
            session.add(Requirement(
                meeting_id=meeting_id,
                req_id=raw_req.get("req_id") or "REQ-001",
                module=raw_req.get("module") or "",
                description=raw_req.get("description") or "",
                priority=raw_req.get("priority") or "P2",
                source=raw_req.get("source"),
                speaker=raw_req.get("speaker"),
                status=raw_req.get("status") or "待确认",
            ))
        await session.commit()
        logger.info("meeting_processed", meeting_id=meeting_id, status="completed")


@celery_app.task(name="process_meeting", bind=True, max_retries=1, soft_time_limit=1500, time_limit=1800)
def process_meeting(self, meeting_id: int):
    """会议 AI pipeline:polish → minutes/requirements → stakeholders。"""
    _run(_process_meeting_async(meeting_id))


# ── ASR transcribe(Block C) ────────────────────────────────────────────

async def _transcribe_meeting_async(meeting_id: int):
    """MinIO 下载音频 → 切片并发 xiaomi ASR(边出边写 raw_transcript / done_chunks)
    → 全部完成自动触发 process。

    2026-05-12 改造:走 services.meeting.asr.transcribe_audio 切片版,每片完成
    后增量更新 DB,前端可实时看到流式输出。
    """
    from models import async_session_maker
    from models.meeting import Meeting
    from services.meeting.storage import download_audio
    from services.meeting.asr import transcribe_audio, CHUNK_SIZE_BYTES
    from services.meeting.audio_utils import convert_to_pcm
    from services.meeting.asr import _format_from_filename

    async with async_session_maker() as session:
        meeting = await session.get(Meeting, meeting_id)
        if not meeting:
            logger.error("meeting_not_found_for_transcribe", meeting_id=meeting_id)
            return
        if not meeting.audio_object_key:
            logger.warning("meeting_no_audio_key", meeting_id=meeting_id)
            meeting.status = "failed"
            await session.commit()
            return
        meeting.status = "processing"
        meeting.asr_engine = "xiaomi"
        meeting.done_chunks = 0
        meeting.total_chunks = 0
        meeting.raw_transcript = ""
        await session.commit()
        object_key = meeting.audio_object_key
        filename = object_key.split("/")[-1]

    try:
        audio_bytes = download_audio(object_key)

        # 先转 PCM + 算切片数,写 total_chunks(给前端 progress bar 用)
        pcm = convert_to_pcm(audio_bytes, source_format=_format_from_filename(filename))
        total_chunks = (len(pcm) + CHUNK_SIZE_BYTES - 1) // CHUNK_SIZE_BYTES
        async with async_session_maker() as session:
            m = await session.get(Meeting, meeting_id)
            if m:
                m.total_chunks = total_chunks
                await session.commit()
        logger.info("meeting_chunks_planned", meeting_id=meeting_id, total=total_chunks)

        # 每片完成时,按 index 落位 + 增量写 DB,前端轮询拿到流式 transcript
        parts: list[str] = [""] * total_chunks

        async def _on_chunk(idx: int, text: str) -> None:
            parts[idx] = text
            async with async_session_maker() as session:
                m = await session.get(Meeting, meeting_id)
                if not m:
                    return
                m.done_chunks = (m.done_chunks or 0) + 1
                # 按 index 顺序拼接(空片留空,保留顺序结构)
                m.raw_transcript = "\n".join(p for p in parts if p)
                await session.commit()

        # 注:transcribe_audio 内部会再转一次 PCM,小冗余;为了 total_chunks 提前
        # 拿到,这里先转一次。后续可优化让 transcribe_audio 接受 pcm bytes 直入。
        transcript = await transcribe_audio(audio_bytes, filename=filename, on_chunk=_on_chunk)
    except Exception as e:
        logger.exception("meeting_transcribe_failed", meeting_id=meeting_id, error=str(e)[:200])
        async with async_session_maker() as session:
            m = await session.get(Meeting, meeting_id)
            if m:
                m.status = "failed"
                await session.commit()
        return

    async with async_session_maker() as session:
        m = await session.get(Meeting, meeting_id)
        if not m:
            return
        # 用最终拼接结果做最后一次覆盖(避免片间隔时序问题)
        m.raw_transcript = transcript
        await session.commit()
        logger.info("meeting_transcribed", meeting_id=meeting_id, chars=len(transcript))

    # 自动触发后续 AI pipeline
    await _process_meeting_async(meeting_id)


@celery_app.task(name="transcribe_meeting", bind=True, max_retries=1, soft_time_limit=1800, time_limit=2100)
def transcribe_meeting(self, meeting_id: int):
    """ASR 转写 + 自动触发后续 AI pipeline。"""
    _run(_transcribe_meeting_async(meeting_id))
