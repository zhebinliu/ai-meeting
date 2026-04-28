import base64
import logging
import asyncio
import re
from typing import Callable, Optional, List
from openai import AsyncOpenAI
from backend.services.asr.audio_utils import AudioUtils

logger = logging.getLogger(__name__)


def _strip_repetition_loop(text: str) -> str:
    """Detect and truncate ASR hallucination loops.

    LLM-based ASR (e.g. Xiaomi MiMo) sometimes degenerates into repeating
    a short phrase dozens of times when the audio is silent/noisy. We
    detect a phrase of 2-12 chars that repeats >=4 times consecutively
    and cut off everything from the second occurrence onward.
    """
    if not text or len(text) < 30:
        return text
    # Try phrase lengths from short to long; first match wins
    for n in range(2, 13):
        pattern = re.compile(r'(.{' + str(n) + r'}?)\1{3,}')
        m = pattern.search(text)
        if m:
            cut = m.start() + n  # keep one occurrence of the phrase
            logger.warning("ASR repetition loop detected (phrase=%r, repeats>=4), truncating from %d/%d",
                           m.group(1), cut, len(text))
            return text[:cut].rstrip('，,。.、 ')
    return text

class RecognitionResult:
    """ASR recognition result compatible with the existing pipeline."""
    def __init__(self, text: str, is_final: bool = False, index: int = 0):
        self.text = text
        self.is_final = is_final
        self.index = index

class XiaomiASRClient:
    """ASR Client using Xiaomi MiMo-V2-Omni multimodal model."""
    
    def __init__(self, api_key: str, base_url: str, model: str, max_concurrency: int = 8):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._result_callback: Optional[Callable[[RecognitionResult], None]] = None

    def on_result(self, callback: Callable[[RecognitionResult], None]):
        """Set callback for transcription results."""
        self._result_callback = callback

    async def close(self):
        """Close the underlying OpenAI client session."""
        await self.client.close()

    async def _transcribe_chunk(self, chunk: bytes, index: int, total: int):
        """Process a single chunk with concurrency control."""
        async with self.semaphore:
            logger.info("Xiaomi ASR [%d/%d]: Starting request...", index + 1, total)
            wav_data = AudioUtils.pcm_to_wav(chunk)
            b64_audio = base64.b64encode(wav_data).decode("utf-8")

            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "你是一个会议记录员。请精确地将这段会议语音转写为文本，保持原始口吻，只输出转写文本，不要解释。如果音频为静音、噪音或无法识别，请直接返回空字符串。严禁重复输出同一短语。"},
                                {
                                    "type": "input_audio",
                                    "input_audio": { "data": b64_audio, "format": "wav" }
                                }
                            ]
                        }
                    ],
                    max_tokens=512,
                    temperature=0.1,
                    frequency_penalty=0.5,
                )

                text = response.choices[0].message.content.strip()
                cleaned = _strip_repetition_loop(text)
                if cleaned != text:
                    logger.info("Xiaomi ASR [%d/%d]: Repetition loop cleaned: %d -> %d chars", index + 1, total, len(text), len(cleaned))
                text = cleaned
                logger.info("Xiaomi ASR [%d/%d]: Finished. Text length: %d", index + 1, total, len(text))

                if text and self._result_callback:
                    self._result_callback(RecognitionResult(text=text, is_final=True, index=index))

                return text

            except Exception as e:
                logger.error("Xiaomi ASR failed for chunk %d: %s", index + 1, e)
                return ""

    async def transcribe_full(self, pcm_data: bytes):
        """Transcribe long PCM data concurrently."""
        if not pcm_data:
            logger.warning("No audio data to transcribe")
            return

        # Use 20-second chunks (more efficient for batching while keeping accuracy)
        chunk_seconds = 20 
        chunk_size = 16000 * 2 * chunk_seconds
        
        chunks = [pcm_data[i:i+chunk_size] for i in range(0, len(pcm_data), chunk_size)]
        total = len(chunks)
        logger.info("Xiaomi ASR: Concurrent processing of %d chunks (8 at a time)", total)

        # Create all tasks
        tasks = [self._transcribe_chunk(chunk, i, total) for i, chunk in enumerate(chunks)]
        
        # Run concurrently
        await asyncio.gather(*tasks)

        logger.info("Xiaomi ASR: Completed all concurrent tasks")
