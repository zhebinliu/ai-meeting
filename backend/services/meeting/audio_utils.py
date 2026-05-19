"""音频格式工具:mp3/m4a/wav → 16kHz / 16-bit / mono PCM,以及 PCM → WAV 容器封装。

依赖:pydub(底层走 ffmpeg/libav 二进制,容器里 apt install ffmpeg)。

源自 meeting-ai 项目 services/asr/audio_utils.py(2026-05-12 合入 kb-system,
配合切片并发 ASR 实现长音频转写)。
"""
from __future__ import annotations

import io
import wave
import structlog

logger = structlog.get_logger()

# xiaomi mimo-v2-omni 推荐输入:16 kHz / 16-bit / mono PCM(再封 WAV)
REQUIRED_SAMPLE_RATE: int = 16_000
REQUIRED_CHANNELS: int = 1
REQUIRED_SAMPLE_WIDTH: int = 2  # 16-bit = 2 bytes / sample


def convert_to_pcm(audio_data: bytes, source_format: str = "wav") -> bytes:
    """将任意音频格式转成 16kHz / 16-bit / mono raw PCM。

    Args:
        audio_data: 原始音频 bytes。
        source_format: 源格式提示("mp3" / "wav" / "m4a" / "ogg" / "raw"),
                       "raw" 直通返回。

    Raises:
        RuntimeError: pydub 未装。
        ValueError: audio_data 为空。
    """
    if not audio_data:
        raise ValueError("audio_data 不能为空")

    # raw PCM 不转
    if source_format == "raw":
        return audio_data

    try:
        from pydub import AudioSegment  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "pydub 未装,无法转换非 PCM 音频。pip install pydub + apt install ffmpeg。"
        ) from exc

    seg: "AudioSegment" = AudioSegment.from_file(io.BytesIO(audio_data), format=source_format)
    seg = seg.set_frame_rate(REQUIRED_SAMPLE_RATE)
    seg = seg.set_channels(REQUIRED_CHANNELS)
    seg = seg.set_sample_width(REQUIRED_SAMPLE_WIDTH)

    pcm: bytes = seg.raw_data
    logger.info(
        "audio_converted_to_pcm",
        source_format=source_format,
        input_bytes=len(audio_data),
        pcm_bytes=len(pcm),
        sample_rate=REQUIRED_SAMPLE_RATE,
    )
    return pcm


def pcm_to_wav(pcm_data: bytes, sample_rate: int = REQUIRED_SAMPLE_RATE) -> bytes:
    """把 raw PCM 封到 WAV 容器(多模态模型一般需要标准音频容器)。"""
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(REQUIRED_CHANNELS)
            wav_file.setsampwidth(REQUIRED_SAMPLE_WIDTH)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()
