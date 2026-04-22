"""Audio format utilities for Xunfei ASR.

Handles PCM conversion, chunking, and format validation required
by the Xunfei real-time ASR API (16kHz, mono, 16-bit PCM).

Dependencies:
    pydub: For audio format conversion (optional, raw PCM passthrough works without it)
"""

from __future__ import annotations

import io
import logging
from typing import List

logger = logging.getLogger(__name__)

# Xunfei ASR required audio parameters
REQUIRED_SAMPLE_RATE: int = 16_000
REQUIRED_CHANNELS: int = 1
REQUIRED_SAMPLE_WIDTH: int = 2  # 16-bit = 2 bytes
MAX_CHUNK_SIZE: int = 1_280  # ~40ms of 16kHz 16-bit mono PCM


class AudioUtils:
    """Utilities for audio format conversion and chunking.

    All methods are stateless and safe to call from any async context.
    """

    @staticmethod
    def convert_to_pcm(
        audio_data: bytes,
        sample_rate: int = REQUIRED_SAMPLE_RATE,
        source_format: str = "wav",
    ) -> bytes:
        """Convert audio data to raw PCM format.

        If the input is already raw PCM at the correct sample rate,
        it is returned as-is. For other formats (wav, mp3, ogg, etc.),
        pydub is used for conversion.

        Args:
            audio_data: Raw audio bytes in the source format.
            sample_rate: Target sample rate in Hz (default: 16000).
            source_format: Hint for the source audio format
                           (e.g. "wav", "mp3", "ogg", "raw").

        Returns:
            Raw PCM bytes at the target sample rate, mono, 16-bit.

        Raises:
            RuntimeError: If pydub is required but not installed.
            ValueError: If audio_data is empty.
        """
        if not audio_data:
            raise ValueError("audio_data must not be empty")

        # Fast path: already raw PCM — return as-is
        if source_format == "raw":
            logger.debug("Audio already raw PCM, returning as-is (%d bytes)", len(audio_data))
            return audio_data

        try:
            from pydub import AudioSegment  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "pydub is required for non-PCM audio conversion. "
                "Install it with: pip install pydub"
            ) from exc

        # Load from the source format
        audio_segment: "AudioSegment" = AudioSegment.from_file(
            io.BytesIO(audio_data), format=source_format
        )

        # Convert to target parameters
        audio_segment = audio_segment.set_frame_rate(sample_rate)
        audio_segment = audio_segment.set_channels(REQUIRED_CHANNELS)
        audio_segment = audio_segment.set_sample_width(REQUIRED_SAMPLE_WIDTH)

        pcm_data: bytes = audio_segment.raw_data
        logger.info(
            "Converted %s audio: %d bytes -> %d bytes PCM (%d Hz, %d-bit mono)",
            source_format,
            len(audio_data),
            len(pcm_data),
            sample_rate,
            REQUIRED_SAMPLE_WIDTH * 8,
        )
        return pcm_data

    @staticmethod
    def chunk_audio(
        audio_data: bytes,
        chunk_size: int = MAX_CHUNK_SIZE,
    ) -> List[bytes]:
        """Split raw PCM audio into fixed-size chunks for streaming.

        The last chunk may be smaller than chunk_size if the total
        audio length is not evenly divisible.

        Args:
            audio_data: Raw PCM audio bytes.
            chunk_size: Maximum size of each chunk in bytes (default: 1280).

        Returns:
            List of byte chunks, each up to chunk_size bytes.

        Raises:
            ValueError: If audio_data is empty or chunk_size <= 0.
        """
        if not audio_data:
            raise ValueError("audio_data must not be empty")
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be > 0, got {chunk_size}")

        chunks: List[bytes] = [
            audio_data[i : i + chunk_size]
            for i in range(0, len(audio_data), chunk_size)
        ]
        logger.debug(
            "Chunked %d bytes into %d frames (chunk_size=%d)",
            len(audio_data),
            len(chunks),
            chunk_size,
        )
        return chunks

    @staticmethod
    def validate_pcm_format(
        sample_rate: int,
        channels: int,
        sample_width: int,
    ) -> bool:
        """Check whether audio parameters match Xunfei requirements.

        Args:
            sample_rate: Sample rate in Hz.
            channels: Number of audio channels.
            sample_width: Sample width in bytes (2 = 16-bit).

        Returns:
            True if all parameters match Xunfei ASR requirements.
        """
        return (
            sample_rate == REQUIRED_SAMPLE_RATE
            and channels == REQUIRED_CHANNELS
            and sample_width == REQUIRED_SAMPLE_WIDTH
        )
    @staticmethod
    def pcm_to_wav(pcm_data: bytes, sample_rate: int = REQUIRED_SAMPLE_RATE) -> bytes:
        """Wrap raw PCM data in a WAV container.
        
        Most multimodal models expect a standard audio format like WAV.
        """
        import wave
        
        with io.BytesIO() as wav_io:
            with wave.open(wav_io, "wb") as wav_file:
                wav_file.setnchannels(REQUIRED_CHANNELS)
                wav_file.setsampwidth(REQUIRED_SAMPLE_WIDTH)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm_data)
            return wav_io.getvalue()
