import base64
import logging
import asyncio
from typing import Callable, Optional, List
from openai import AsyncOpenAI
from services.asr.audio_utils import AudioUtils

logger = logging.getLogger(__name__)

class RecognitionResult:
    """ASR recognition result compatible with the existing pipeline."""
    def __init__(self, text: str, is_final: bool = False):
        self.text = text
        self.is_final = is_final

class XiaomiASRClient:
    """ASR Client using Xiaomi MiMo-V2-Omni multimodal model."""
    
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self._result_callback: Optional[Callable[[RecognitionResult], None]] = None

    def on_result(self, callback: Callable[[RecognitionResult], None]):
        """Set callback for transcription results."""
        self._result_callback = callback

    async def close(self):
        """Close the underlying OpenAI client session."""
        await self.client.close()

    async def transcribe_full(self, pcm_data: bytes):
        """Transcribe long PCM data by chunking it for the Omni model."""
        if not pcm_data:
            logger.warning("No audio data to transcribe")
            return

        # Use 10-second chunks for more frequent progress updates
        chunk_seconds = 10 
        chunk_size = 16000 * 2 * chunk_seconds # 16kHz * 2 bytes/sample * seconds
        
        chunks = [pcm_data[i:i+chunk_size] for i in range(0, len(pcm_data), chunk_size)]
        logger.info("Xiaomi ASR: Processing %d chunks (%d seconds each)", len(chunks), chunk_seconds)

        for idx, chunk in enumerate(chunks):
            logger.info("Xiaomi ASR: Transcribing chunk %d/%d...", idx + 1, len(chunks))
            wav_data = AudioUtils.pcm_to_wav(chunk)
            b64_audio = base64.b64encode(wav_data).decode("utf-8")

            try:
                # Call Xiaomi MiMo-V2-Omni 
                # Note: Explicitly asking for transcription in the prompt
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "你是一个会议记录员。请精确地将这段会议语音转写为文本，保持原始口吻。只输出转写后的文本内容，不要有任何开场白或解释。"},
                                {
                                    "type": "input_audio",
                                    "input_audio": { "data": b64_audio, "format": "wav" }
                                }
                            ]
                        }
                    ],
                    max_tokens=4096,
                    temperature=0.1
                )
                
                text = response.choices[0].message.content.strip()
                if text and self._result_callback:
                    # Notify progress
                    self._result_callback(RecognitionResult(text=text, is_final=True))
                
                # Small delay to avoid aggressive rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error("Xiaomi ASR failed for chunk %d: %s", idx + 1, e)
                continue

        logger.info("Xiaomi ASR: Completed all chunks")
