"""High-level Xunfei streaming ASR client.

Wraps the low-level WebSocket protocol handler with session management,
result parsing, auto-reconnect, and a callback-based result API.

Usage:
    client = XunfeiASRClient(app_id, api_key, api_secret)
    client.on_result(lambda r: print(r["text"], r["is_final"]))
    await client.connect()
    await client.start_recognition()
    await client.send_audio(pcm_chunk)
    await client.stop_recognition()
    await client.close()
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .audio_utils import AudioUtils, MAX_CHUNK_SIZE
from .websocket_client import SessionState, XunfeiWebSocketClient

logger = logging.getLogger(__name__)

# Maximum reconnection attempts on transient failures
MAX_RECONNECT_ATTEMPTS: int = 3
RECONNECT_DELAY_SECONDS: float = 1.0


@dataclass
class RecognitionResult:
    """Parsed recognition result from Xunfei ASR.

    Attributes:
        text: Recognized text (may be partial for interim results).
        is_final: Whether this is a finalized result (rt=0) or interim (rt=1).
        raw: The original unmodified response dict from the server.
    """

    text: str
    is_final: bool
    raw: Dict[str, Any] = field(repr=False)


class XunfeiASRClient:
    """High-level client for Xunfei real-time streaming ASR.

    Manages the full lifecycle: connect -> start recognition ->
    stream audio -> receive results -> stop recognition -> close.

    Supports callback-based result delivery, auto-reconnect on
    transient errors, and proper async resource cleanup.

    Args:
        app_id: Xunfei application ID.
        api_key: Xunfei API key.
        api_secret: Xunfei API secret.
        max_reconnect_attempts: Max reconnection tries on failure (default: 3).

    Environment Variables (fallback if args not provided):
        XUNFEI_APP_ID: Application ID.
        XUNFEI_API_KEY: API key.
        XUNFEI_API_SECRET: API secret.

    Example:
        >>> async def on_result(result: RecognitionResult):
        ...     prefix = "[FINAL]" if result.is_final else "[interim]"
        ...     print(f"{prefix} {result.text}")
        ...
        >>> client = XunfeiASRClient(app_id, api_key, api_secret)
        >>> client.on_result(on_result)
        >>> await client.connect()
        >>> await client.start_recognition()
        >>> await client.send_audio(pcm_data)
        >>> await client.stop_recognition()
        >>> await client.close()
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        max_reconnect_attempts: int = MAX_RECONNECT_ATTEMPTS,
    ) -> None:
        self._app_id: str = app_id or os.environ.get("XUNFEI_APP_ID", "")
        self._api_key: str = api_key or os.environ.get("XUNFEI_API_KEY", "")
        self._api_secret: str = api_secret or os.environ.get("XUNFEI_API_SECRET", "")

        if not all([self._app_id, self._api_key, self._api_secret]):
            raise ValueError(
                "Xunfei credentials are required. Provide them as arguments "
                "or set XUNFEI_APP_ID, XUNFEI_API_KEY, XUNFEI_API_SECRET "
                "environment variables."
            )

        self._max_reconnect: int = max_reconnect_attempts
        self._ws_client: XunfeiWebSocketClient = XunfeiWebSocketClient(
            app_id=self._app_id,
            api_key=self._api_key,
            api_secret=self._api_secret,
        )

        self._result_callbacks: List[Callable[[RecognitionResult], None]] = []
        self._error_callbacks: List[Callable[[Exception], None]] = []
        self._is_recognizing: bool = False

        # Register internal message handler
        self._ws_client.set_message_callback(self._handle_raw_message)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        """Current connection state."""
        return self._ws_client.state

    @property
    def is_recognizing(self) -> bool:
        """Whether a recognition session is active."""
        return self._is_recognizing

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_result(self, callback: Callable[[RecognitionResult], None]) -> None:
        """Register a callback for recognition results.

        The callback receives a RecognitionResult with:
            - text: Recognized text string
            - is_final: True for finalized results, False for interim
            - raw: Original server response dict

        Multiple callbacks can be registered; all will be invoked.

        Args:
            callback: Async or sync function to handle results.
        """
        self._result_callbacks.append(callback)

    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Register a callback for errors.

        Args:
            callback: Function to handle exceptions.
        """
        self._error_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the Xunfei ASR WebSocket endpoint.

        Raises:
            ConnectionError: If connection fails after all retry attempts.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_reconnect + 1):
            try:
                await self._ws_client.connect()
                logger.info(
                    "Xunfei ASR connected (attempt %d/%d)",
                    attempt,
                    self._max_reconnect,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Connection attempt %d/%d failed: %s",
                    attempt,
                    self._max_reconnect,
                    exc,
                )
                if attempt < self._max_reconnect:
                    await asyncio.sleep(RECONNECT_DELAY_SECONDS * attempt)

        raise ConnectionError(
            f"Failed to connect after {self._max_reconnect} attempts: {last_error}"
        )

    async def close(self) -> None:
        """Close the WebSocket connection and clean up resources.

        Safe to call even if not connected. Cancels any active
        recognition session first.
        """
        if self._is_recognizing:
            logger.warning("Closing while recognition is active; stopping first")
            try:
                await self.stop_recognition()
            except Exception as exc:
                logger.error("Error stopping recognition during close: %s", exc)

        await self._ws_client.close()
        self._result_callbacks.clear()
        self._error_callbacks.clear()
        logger.info("XunfeiASRClient closed")

    # ------------------------------------------------------------------
    # Recognition session
    # ------------------------------------------------------------------

    async def start_recognition(self) -> None:
        """Start a new recognition session.

        Sends the start frame to the server. After this call, use
        send_audio() to stream audio data.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If recognition is already active.
        """
        if self._is_recognizing:
            raise RuntimeError("Recognition session is already active")

        await self._ws_client.send_start_frame()
        self._is_recognizing = True
        logger.info("Recognition session started")

    async def send_audio(self, audio_data: bytes) -> None:
        """Send an audio chunk to the ASR engine.

        Automatically chunks large payloads into 1280-byte frames
        as required by the Xunfei protocol.

        Args:
            audio_data: Raw PCM bytes (16kHz, mono, 16-bit).

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If recognition session is not active.
            ValueError: If audio_data is empty.
        """
        if not self._is_recognizing:
            raise RuntimeError("No active recognition session. Call start_recognition() first.")

        if not audio_data:
            raise ValueError("audio_data must not be empty")

        chunks: List[bytes] = AudioUtils.chunk_audio(audio_data, MAX_CHUNK_SIZE)
        for chunk in chunks:
            await self._ws_client.send_audio_chunk(chunk)
            await asyncio.sleep(0.002)  # Reduce delay to speed up processing for large files

    async def stop_recognition(self) -> None:
        """Stop the current recognition session.

        Sends the end frame and marks the session as inactive.
        Final results may still arrive via callbacks after this call.

        Raises:
            RuntimeError: If no recognition session is active.
        """
        if not self._is_recognizing:
            raise RuntimeError("No active recognition session")

        await self._ws_client.send_end_frame()
        self._is_recognizing = False
        logger.info("Recognition session stopped")

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _handle_raw_message(self, data: Dict[str, Any]) -> None:
        """Parse a raw server response and dispatch to result callbacks.
        """
        logger.info("Raw message from Xunfei: %s", json.dumps(data))
        # Support both old (header-based) and new (data-based) response formats
        if "data" in data:
            inner: Dict[str, Any] = data.get("data", {})
            action: str = inner.get("action", "")
            msg_type: str = data.get("msg_type", "")
            code: int = data.get("code", 0)  # 0 = success, -1 or other = error
        else:
            # Fallback: old header-based format
            inner = data.get("header", {})
            action = inner.get("action", "")
            msg_type = action
            code = inner.get("code", -1)

        if code != 0:
            error_msg = data.get("message", inner.get("message", "Unknown ASR error"))
            exc = RuntimeError(f"Xunfei ASR error [code={code}]: {error_msg}")
            logger.error("Server error response: %s", exc)
            self._notify_error(exc)
            return

        if msg_type == "result" or action == "result":
            result = self._parse_result(data)
            if result:
                for cb in self._result_callbacks:
                    try:
                        cb(result)
                    except Exception as exc:
                        logger.error("Result callback error: %s", exc)

        elif action == "started":
            sid = inner.get("sessionId", inner.get("sid", ""))
            if sid:
                self._ws_client.session_id = sid
            logger.info("ASR session started (sid=%s)", sid)

        elif action == "end":
            logger.info("ASR session ended")

        else:
            logger.debug("Received action '%s': %s", action, data)

    @staticmethod
    def _parse_result(data: Dict[str, Any]) -> Optional[RecognitionResult]:
        """Extract text and finality from a Large Model API result.

        New structure: {"data": {"cn": {"st": {"rt": [...]}}, "ls": false}, "msg_type": "result"}
        """
        try:
            inner = data.get("data", {})
            ls = inner.get("ls", False) # last segment of the session
            cn = inner.get("cn", {})
            st = cn.get("st", {})
            res_type = st.get("type", "0") # 0=interim, 1=final
            rt_list = st.get("rt", [])
            
            # is_final means this sentence/segment is finalized
            is_final = (res_type == "1")

            words: List[str] = []
            for rt in rt_list:
                for ws in rt.get("ws", []):
                    for cw in ws.get("cw", []):
                        word = cw.get("w", "")
                        if word:
                            words.append(word)

            if not words and not ls:
                return None

            text: str = "".join(words)

            return RecognitionResult(
                text=text,
                is_final=is_final or ls, # If either it's a final segment or end of stream
                raw=data,
            )

        except Exception as exc:
            logger.error("Failed to parse result: %s | data=%s", exc, data)
            return None

        except Exception as exc:
            logger.error("Failed to parse result: %s | data=%s", exc, data)
            return None

    def _notify_error(self, exc: Exception) -> None:
        """Dispatch an error to all registered error callbacks.

        Args:
            exc: The exception to dispatch.
        """
        for cb in self._error_callbacks:
            try:
                cb(exc)
            except Exception as cb_exc:
                logger.error("Error callback itself failed: %s", cb_exc)


# ======================================================================
# Integration helper: bridge browser audio to Xunfei ASR
# ======================================================================


async def handle_recording_session(
    audio_queue: "asyncio.Queue[Optional[bytes]]",
    transcript_callback: Callable[[str, bool], None],
    app_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> None:
    """Handle a complete recording session bridging audio to Xunfei ASR.

    This function is designed to be spawned as an async task. It:
      1. Connects to Xunfei ASR
      2. Starts recognition
      3. Reads audio chunks from the queue
      4. Sends them to Xunfei
      5. Invokes transcript_callback with results
      6. Stops and cleans up when None is received from the queue

    Args:
        audio_queue: Async queue of raw PCM audio chunks.
                     Send None to signal end of recording.
        transcript_callback: Called with (text, is_final) for each result.
        app_id: Xunfei app ID (or from env XUNFEI_APP_ID).
        api_key: Xunfei API key (or from env XUNFEI_API_KEY).
        api_secret: Xunfei API secret (or from env XUNFEI_API_SECRET).

    Example:
        >>> queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        >>> async def on_transcript(text: str, is_final: bool):
        ...     print(f"{'[FINAL]' if is_final else '[interim]'} {text}")
        >>> await handle_recording_session(queue, on_transcript)
    """
    client = XunfeiASRClient(
        app_id=app_id,
        api_key=api_key,
        api_secret=api_secret,
    )

    def _on_result(result: RecognitionResult) -> None:
        """Bridge RecognitionResult to the simpler (text, is_final) callback."""
        transcript_callback(result.text, result.is_final)

    client.on_result(_on_result)

    try:
        await client.connect()
        await client.start_recognition()
        logger.info("Recording session started, waiting for audio chunks...")

        while True:
            chunk: Optional[bytes] = await audio_queue.get()

            if chunk is None:
                # End-of-stream sentinel
                logger.info("End-of-stream received, stopping recognition")
                break

            try:
                await client.send_audio(chunk)
            except Exception as exc:
                logger.error("Failed to send audio chunk: %s", exc)
                # Continue processing — transient errors shouldn't kill the session

    except asyncio.CancelledError:
        logger.info("Recording session cancelled")
        raise

    except Exception as exc:
        logger.error("Recording session error: %s", exc)
        raise

    finally:
        try:
            if client.is_recognizing:
                await client.stop_recognition()
        except Exception as exc:
            logger.error("Error stopping recognition: %s", exc)

        await client.close()
        logger.info("Recording session ended")
