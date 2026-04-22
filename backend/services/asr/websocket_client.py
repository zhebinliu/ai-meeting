"""Low-level Xunfei WebSocket protocol handler (大模型版).

Manages the WebSocket connection lifecycle, authentication signature
generation, and raw message framing for the Xunfei Large Model ASR API.

Protocol Reference:
    Endpoint:  wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1
    Auth:      HmacSHA1(sorted_params_string, APISecret) → Base64
    Audio:     16kHz mono 16-bit PCM, max 1280 bytes/frame
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

# Xunfei Large Model ASR WebSocket endpoint
ASR_WS_ENDPOINT: str = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"


class SessionState(Enum):
    """WebSocket session lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECOGNIZING = "recognizing"
    CLOSING = "closing"
    ERROR = "error"


class XunfeiWebSocketClient:
    """Low-level client for Xunfei Large Model ASR WebSocket protocol.

    Handles connection, authentication, message framing, and response
    parsing. Designed to be wrapped by the higher-level XunfeiASRClient.

    Args:
        app_id: Xunfei application ID.
        api_key: Xunfei API key (used as accessKeyId).
        api_secret: Xunfei API secret (used for HmacSHA1 signature).

    Example:
        >>> client = XunfeiWebSocketClient(app_id, api_key, api_secret)
        >>> await client.connect()
        >>> await client.send_start_frame()
        >>> await client.send_audio_chunk(pcm_bytes)
        >>> await client.send_end_frame()
        >>> await client.close()
    """

    def __init__(
        self,
        app_id: str,
        api_key: str,
        api_secret: str,
    ) -> None:
        self._app_id: str = app_id
        self._api_key: str = api_key
        self._api_secret: str = api_secret

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._state: SessionState = SessionState.DISCONNECTED

        self._receive_task: Optional[asyncio.Task[None]] = None
        self._message_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._error_callback: Optional[Callable[[Exception], None]] = None
        
        self._session_id: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is open and usable."""
        return self._ws is not None and not self._ws.closed

    @property
    def session_id(self) -> Optional[str]:
        """Xunfei session ID for the current connection."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    @staticmethod
    def _build_utc_param() -> str:
        """Return current time in the format required by Xunfei: YYYY-MM-DDTHH:MM:SS+0800."""
        tz_cst = timezone(timedelta(hours=8))
        now = datetime.now(tz_cst)
        return now.strftime("%Y-%m-%dT%H:%M:%S+0800")

    def _build_auth_url(self) -> str:
        """Construct the authenticated WebSocket URL for the Large Model API.

        Authentication steps:
            1. Collect params: appId, accessKeyId, utc, lang, audio_encode, samplerate, uuid
            2. Sort by key name ascending
            3. URL-encode each key and value
            4. Concatenate as "key=value&key=value&..."
            5. HmacSHA1(concatenated_string, key=APISecret)
            6. Base64 encode → signature
            7. Append signature to URL

        Returns:
            Full WebSocket URL with authentication query parameters.
        """
        utc_param: str = self._build_utc_param()
        request_uuid: str = str(uuid.uuid4())

        # Collect all params (excluding signature)
        params: Dict[str, str] = {
            "appId": self._app_id,
            "accessKeyId": self._api_key,
            "utc": utc_param,
            "lang": "autodialect",
            "audio_encode": "pcm_s16le",
            "samplerate": "16000",
            "uuid": request_uuid,
        }

        # Sort by key name ascending
        sorted_keys = sorted(params.keys())

        # URL-encode each key and value, concatenate
        encoded_parts: list[str] = []
        for key in sorted_keys:
            encoded_key = quote(key, safe="")
            encoded_val = quote(params[key], safe="")
            encoded_parts.append(f"{encoded_key}={encoded_val}")

        param_string = "&".join(encoded_parts)

        # HmacSHA1 signature
        mac = hmac.new(
            self._api_secret.encode("utf-8"),
            param_string.encode("utf-8"),
            hashlib.sha1,
        )
        signature: str = base64.b64encode(mac.digest()).decode("utf-8")

        # Build final URL
        url: str = f"{ASR_WS_ENDPOINT}?{param_string}&signature={quote(signature, safe='')}"

        logger.debug(
            "Built auth URL (utc=%s, uuid=%s)",
            utc_param,
            request_uuid,
        )
        return url

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open a WebSocket connection to Xunfei Large Model ASR.

        Raises:
            ConnectionError: If already connected or connection fails.
            aiohttp.ClientError: On HTTP/WS handshake failure.
        """
        if self.is_connected:
            raise ConnectionError("WebSocket is already connected")

        self._state = SessionState.CONNECTING
        url: str = self._build_auth_url()

        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(url)
            self._state = SessionState.CONNECTED
            logger.info("Connected to Xunfei Large Model ASR WebSocket")

            # Start background receiver
            self._receive_task = asyncio.ensure_future(self._receive_loop())

        except Exception as exc:
            self._state = SessionState.ERROR
            logger.error("Failed to connect to Xunfei ASR: %s", exc)
            await self._cleanup_session()
            raise

    async def close(self) -> None:
        """Gracefully close the WebSocket connection.

        Sends a close frame and waits for the receiver task to finish.
        Safe to call multiple times.
        """
        if self._state == SessionState.DISCONNECTED:
            return

        self._state = SessionState.CLOSING
        logger.info("Closing Xunfei ASR WebSocket connection")

        # Cancel receiver task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        await self._cleanup_session()
        self._state = SessionState.DISCONNECTED
        logger.info("Xunfei ASR WebSocket connection closed")

    async def _cleanup_session(self) -> None:
        """Close WS and HTTP session resources."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # ------------------------------------------------------------------
    # Frame sending
    # ------------------------------------------------------------------

    async def send_start_frame(self) -> None:
        """Send the start-of-stream control frame.

        Uses the Large Model API header-based protocol:
            {"header": {"action": "started", "app_id": "..."}}
        (The server acknowledges with action "started" after connection.)

        Must be called before sending audio data.

        Raises:
            ConnectionError: If WebSocket is not connected.
        """
        # The new LLM API documentation does not mention a 'started' frame sent to the server.
        # We only update our local state.
        self._state = SessionState.RECOGNIZING
        logger.debug("Recognition session active (locally)")

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send a single audio chunk as a binary frame.

        Args:
            audio_data: Raw PCM bytes (max 1280 bytes recommended).

        Raises:
            ConnectionError: If WebSocket is not connected.
            ValueError: If audio_data is empty.
        """
        if not audio_data:
            raise ValueError("audio_data must not be empty")
        await self._send_binary(audio_data)

    async def send_end_frame(self) -> None:
        """Send the end-of-stream control frame.

        Documentation says format: {"end": true, "sessionId": "..."}
        """
        if not self._session_id:
            logger.warning("Sending end frame without sessionId")
            
        frame: Dict[str, Any] = {
            "end": True,
            "sessionId": self._session_id or "",
        }
        await self._send_text(json.dumps(frame))
        logger.debug("Sent end frame: %s", frame)

    async def _send_text(self, data: str) -> None:
        """Send a text frame through the WebSocket.

        Args:
            data: JSON string to send.

        Raises:
            ConnectionError: If WebSocket is not connected.
        """
        async with self._lock:
            if not self.is_connected:
                raise ConnectionError("WebSocket is not connected")
            await self._ws.send_str(data)  # type: ignore[union-attr]

    async def _send_binary(self, data: bytes) -> None:
        """Send a binary frame through the WebSocket.

        Args:
            data: Raw bytes to send.

        Raises:
            ConnectionError: If WebSocket is not connected.
        """
        async with self._lock:
            if not self.is_connected:
                raise ConnectionError("WebSocket is not connected")
            await self._ws.send_bytes(data)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Message receiving
    # ------------------------------------------------------------------

    def set_message_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Register a callback for parsed JSON responses.

        Args:
            callback: Function called with each parsed response dict.
        """
        self._message_callback = callback

    def set_error_callback(self, callback: Callable[[Exception], None]) -> None:
        """Register a callback for connection errors.

        Args:
            callback: Function called when an error occurs in the receive loop.
        """
        self._error_callback = callback

    async def _receive_loop(self) -> None:
        """Background task that continuously reads WebSocket messages.

        Parses JSON text messages and invokes the registered callback.
        Terminates when the WebSocket is closed or an error occurs.
        """
        logger.debug("Receive loop started")
        try:
            async for msg in self._ws:  # type: ignore[union-attr]
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data: Dict[str, Any] = json.loads(msg.data)
                        if self._message_callback:
                            self._message_callback(data)
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON: %s", msg.data[:200])

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        "WebSocket error: %s",
                        self._ws.exception() if self._ws else "unknown",
                    )
                    break

                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    logger.info("WebSocket closed by server")
                    break

        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
            raise

        except Exception as exc:
            logger.error("Receive loop exception: %s", exc)
            if self._error_callback:
                self._error_callback(exc)

        finally:
            logger.debug("Receive loop terminated")
