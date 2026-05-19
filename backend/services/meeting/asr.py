"""会议音频 ASR 客户端 — xiaomi mimo-v2-omni 切片并发版(2026-05-12)。

设计同 meeting-ai 原项目:
1. 收完整音频(mp3/m4a/wav 等) → pydub/ffmpeg 转 16kHz 16bit mono PCM
2. 切 20 秒一片(640 000 字节/片)
3. 每片 PCM 封 WAV → base64 → 调 xiaomi `input_audio` chat.completions
4. asyncio.Semaphore 控制并发 8 路
5. 每片完成回调,把 (index, text) 写回 callback,调用方按 index 拼接
   并增量写 meeting.raw_transcript / done_chunks,前端轮询展示流式进度

代价比直传大(网络往返多 + 转 PCM),换来:
- 不再受 xiaomi 单次 inline 上限制约(20MB+ mp3 直传会 WriteTimeout)
- 流式输出:用户在前端能看到一段段出来
"""
from __future__ import annotations

import asyncio
import base64
import os
import structlog
from typing import Awaitable, Callable, Optional

import httpx

from config import settings
from services.meeting.audio_utils import convert_to_pcm, pcm_to_wav, REQUIRED_SAMPLE_RATE

logger = structlog.get_logger()


_XIAOMI_API_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
_DEFAULT_MODEL = "mimo-v2-omni"
_DEFAULT_PROMPT = (
    "你是一个会议记录员。请精确地将这段会议语音转写为文本,保持原始口吻。"
    "只输出转写后的文本内容,不要有任何开场白或解释。"
)

# 20 秒一片(meeting-ai 实测对 mimo-v2-omni 又快又稳的粒度)
CHUNK_SECONDS = 20
CHUNK_SIZE_BYTES = REQUIRED_SAMPLE_RATE * 2 * CHUNK_SECONDS  # = 640 000

# xiaomi 并发上限 8(每个 chunk 网络往返 + 模型推理 5-15s,8 路并发对 30 分钟会议
# 是 30/20=90 chunks → ceil(90/8)*10s ≈ 110s,可接受)
DEFAULT_CONCURRENCY = 8

# 单片 timeout 90s(xiaomi 单片正常 5-15s,留 6x 富余)
_PER_CHUNK_TIMEOUT = 90.0


def _format_from_filename(filename: str) -> str:
    """从文件名推断源音频格式,供 pydub.from_file 用。"""
    ext = os.path.splitext((filename or "").lower())[1].lstrip(".")
    # pydub 接受 mp3 / m4a / wav / ogg / webm / flac 等
    if ext in {"mp3", "m4a", "wav", "ogg", "webm", "flac", "aac"}:
        return "mp3" if ext == "aac" else ext  # aac 当 mp3 走 ffmpeg
    return "wav"  # 兜底


async def _transcribe_pcm_chunk(
    client: httpx.AsyncClient,
    api_key: str,
    pcm: bytes,
    idx: int,
    total: int,
) -> str:
    """单片 PCM → xiaomi 转写,返回文本。失败返回空字符串(不中断整体)。"""
    wav = pcm_to_wav(pcm)
    b64 = base64.b64encode(wav).decode("ascii")
    payload = {
        "model": _DEFAULT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _DEFAULT_PROMPT},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    }
    try:
        resp = await client.post(
            f"{_XIAOMI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_PER_CHUNK_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.error("xiaomi_chunk_failed", idx=idx, total=total,
                         status=resp.status_code, body=resp.text[:200])
            return ""
        text = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        logger.info("xiaomi_chunk_done", idx=idx + 1, total=total, chars=len(text))
        return text
    except Exception as e:
        logger.exception("xiaomi_chunk_exception", idx=idx, total=total, error=str(e)[:200])
        return ""


# (index, text) 回调,供调用方按 index 写回进度
OnChunkResult = Callable[[int, str], Awaitable[None]]


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "",
    on_chunk: Optional[OnChunkResult] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> str:
    """对整段音频做切片并发转写,边出边回调,返回拼接后的全文。

    - audio_bytes: 完整原始音频(mp3/m4a/wav 等)
    - filename: 用于推断格式(扩展名)
    - on_chunk: 每片完成时调用 `await on_chunk(index, text)`,调用方可借此
      增量更新 DB(`meeting.raw_transcript / done_chunks`,前端轮询展示进度)
    - 返回值:所有片段按顺序拼接的全文
    """
    if not audio_bytes:
        return ""

    api_key = settings.xiaomi_api_key
    if not api_key:
        raise RuntimeError("缺少 XIAOMI_API_KEY,无法走 mimo-v2-omni ASR")

    # 1. 转 PCM 16kHz/16bit/mono
    source_format = _format_from_filename(filename)
    pcm = convert_to_pcm(audio_bytes, source_format=source_format)

    # 2. 切片
    chunks = [pcm[i:i + CHUNK_SIZE_BYTES] for i in range(0, len(pcm), CHUNK_SIZE_BYTES)]
    total = len(chunks)
    logger.info("xiaomi_asr_start",
                bytes=len(audio_bytes),
                pcm_bytes=len(pcm),
                chunks=total,
                concurrency=concurrency)

    # 3. 并发转写,结果按 index 落位
    parts: list[str] = [""] * total
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=httpx.Timeout(_PER_CHUNK_TIMEOUT)) as client:
        async def _run_chunk(i: int, c: bytes) -> None:
            async with sem:
                text = await _transcribe_pcm_chunk(client, api_key, c, i, total)
                parts[i] = text
                if on_chunk:
                    try:
                        await on_chunk(i, text)
                    except Exception:
                        logger.warning("on_chunk_callback_failed", idx=i)

        await asyncio.gather(*(_run_chunk(i, c) for i, c in enumerate(chunks)))

    full_text = "\n".join(p for p in parts if p)
    logger.info("xiaomi_asr_done", total_chunks=total, full_chars=len(full_text))
    return full_text
