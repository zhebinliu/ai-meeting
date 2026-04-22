"""WebSocket endpoint for real-time audio streaming and transcription."""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.database import async_session_factory
from backend.models.meeting import Meeting
from backend.services.asr.xunfei_asr import XunfeiASRClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/recording/{meeting_id}")
async def recording_websocket(
    websocket: WebSocket,
    meeting_id: int,
    token: str = Query(...),
) -> None:
    """Handle real-time audio streaming via WebSocket.

    Requires a ``token`` query parameter for authentication.

    Protocol:
    - Client sends binary audio chunks (PCM 16kHz, 16-bit, mono).
    - Server sends JSON transcript messages back.

    Message format (server -> client):
        {
            "type": "transcript",
            "text": "recognised text",
            "is_final": true/false,
            "speaker": "speaker_1"
        }
    """
    # --- Authentication ---
    if token != settings.WS_AUTH_TOKEN:
        await websocket.close(code=4001, reason="Unauthorized")
        logger.warning("WebSocket auth failed for meeting_id=%s", meeting_id)
        return

    await websocket.accept()
    logger.info("WebSocket connected for meeting_id=%s", meeting_id)

    # Use a single DB session for the entire WebSocket connection
    # to avoid race conditions from opening/closing sessions per segment.
    async with async_session_factory() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None:
            await websocket.send_json({"type": "error", "detail": "Meeting not found"})
            await websocket.close(code=4004)
            return

        # ------------------------------------------------------------------
        # ASR integration (Buffered 10s-30s)
        # ------------------------------------------------------------------
        from backend.services.asr.xiaomi_asr import XiaomiASRClient
        from backend.services.asr.whisper_asr import WhisperASRClient

        transcript_queue: asyncio.Queue = asyncio.Queue()
        
        if settings.ASR_ENGINE == "whisper":
            logger.info("WebSocket: Using Local Whisper引擎 (size=%s)", settings.WHISPER_MODEL_SIZE)
            asr_client = WhisperASRClient(model_size=settings.WHISPER_MODEL_SIZE)
        else:
            logger.info("WebSocket: Using Xiaomi MiMo-V2引擎")
            asr_client = XiaomiASRClient(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                model=settings.XIAOMI_OMNI_MODEL,
            )

        def on_result(result) -> None:
            """Handle recognition results from ASR."""
            text = getattr(result, "text", "") or ""
            if text:
                transcript_queue.put_nowait({"text": text, "is_final": True})

        asr_client.on_result(on_result)

        # 10 seconds of 16kHz 16-bit mono PCM = 16000 * 2 * 10 = 320,000 bytes
        CHUNK_SIZE_BYTES = 16000 * 2 * 10
        audio_buffer = bytearray()

        try:
            # Concurrently read transcript queue and forward to WebSocket client
            async def send_transcripts() -> None:
                """Read transcript queue and forward to WebSocket client."""
                while True:
                    transcript = await transcript_queue.get()
                    transcript_message = {
                        "type": "transcript",
                        "text": transcript["text"],
                        "is_final": transcript["is_final"],
                        "speaker": "speaker_1",
                    }
                    await websocket.send_json(transcript_message)

                    # Persist final transcript segments
                    if transcript["is_final"] and transcript["text"]:
                        # Refresh meeting object to get latest transcript
                        await db.refresh(meeting)
                        existing = meeting.raw_transcript or ""
                        meeting.raw_transcript = existing + transcript["text"] + "\n"
                        await db.commit()
                        logger.info(
                            "Saved 30s chunk to meeting %s (total %d segments)",
                            meeting_id,
                            len(meeting.raw_transcript.split('\n')),
                        )

            send_task = asyncio.ensure_future(send_transcripts())

            try:
                while True:
                    data = await websocket.receive_bytes()
                    if not data:
                        continue
                    
                    audio_buffer.extend(data)
                    
                    # When buffer reaches 30 seconds, trigger Xiaomi ASR
                    if len(audio_buffer) >= CHUNK_SIZE_BYTES:
                        logger.info("WebSocket: Received 30s of audio, transcribing segment...")
                        chunk_to_transcribe = bytes(audio_buffer)
                        audio_buffer = bytearray()
                        
                        # Use transcribe_full for the segment (handles wav conversion)
                        # Fire and forget if we don't want to block receiving next bytes, 
                        # but usually Xiaomi is fast enough and loop is fast.
                        asyncio.create_task(asr_client.transcribe_full(chunk_to_transcribe))
            finally:
                # Handle remaining buffer on disconnect
                if audio_buffer:
                    logger.info("WebSocket: Transcribing final remaining buffer (%d bytes)...", len(audio_buffer))
                    asyncio.create_task(asr_client.transcribe_full(bytes(audio_buffer)))
                
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for meeting_id=%s", meeting_id)
        except Exception:
            logger.exception("Unexpected error in WebSocket for meeting_id=%s", meeting_id)
            await websocket.close(code=1011)
        finally:
            await asr_client.close()
