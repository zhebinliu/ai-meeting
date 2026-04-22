"""Xunfei (iFlytek) streaming ASR integration module.

Provides real-time speech recognition via Xunfei's WebSocket-based
streaming ASR API. Supports PCM audio at 16kHz mono 16-bit.

Modules:
    xunfei_asr:       High-level ASR client with callback-based results
    websocket_client: Low-level WebSocket protocol handling & auth
    audio_utils:      Audio format conversion and chunking utilities
"""

from .xunfei_asr import XunfeiASRClient, handle_recording_session
from .audio_utils import AudioUtils
from .websocket_client import XunfeiWebSocketClient

__all__ = [
    "XunfeiASRClient",
    "XunfeiWebSocketClient",
    "AudioUtils",
    "handle_recording_session",
]
