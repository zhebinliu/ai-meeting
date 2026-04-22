import logging
import asyncio
import os
import tempfile
from typing import Callable, Optional
from faster_whisper import WhisperModel
from backend.services.asr.audio_utils import AudioUtils

logger = logging.getLogger(__name__)

class RecognitionResult:
    """ASR recognition result compatible with the existing pipeline."""
    def __init__(self, text: str, is_final: bool = True, start: float = 0, end: float = 0, duration: float = 0):
        self.text = text
        self.is_final = is_final
        self.start = start
        self.end = end
        self.duration = duration

class WhisperASRClient:
    """ASR Client using Faster-Whisper local model."""
    
    _model_cache = {}

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        """Initialize Whisper model."""
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._result_callback: Optional[Callable[[RecognitionResult], None]] = None
        self._model: Optional[WhisperModel] = None

    def _get_model(self) -> WhisperModel:
        """Lazy load and cache model to save memory."""
        cache_key = (self.model_size, self.device, self.compute_type)
        if cache_key not in WhisperASRClient._model_cache:
            logger.info("Loading Whisper model: %s (%s, %s)", self.model_size, self.device, self.compute_type)
            WhisperASRClient._model_cache[cache_key] = WhisperModel(
                self.model_size, 
                device=self.device, 
                compute_type=self.compute_type,
                cpu_threads=4,
                num_workers=2
            )
        return WhisperASRClient._model_cache[cache_key]

    def on_result(self, callback: Callable[[RecognitionResult], None]):
        """Set callback for transcription results."""
        self._result_callback = callback

    async def transcribe_full(self, pcm_data: bytes):
        """Transcribe long PCM data with real-time segment updates."""
        if not pcm_data:
            logger.warning("No audio data to transcribe")
            return

        wav_data = AudioUtils.pcm_to_wav(pcm_data)
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_data)
            tmp_path = tmp.name

        try:
            loop = asyncio.get_running_loop()
            # Run transcription in thread pool
            await loop.run_in_executor(
                None, 
                self._run_transcription_with_callback, 
                tmp_path,
                loop
            )
            logger.info("Whisper ASR: Finalized transcription process")
            
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _run_transcription_with_callback(self, audio_path: str, loop: asyncio.AbstractEventLoop):
        """Sync method that iterates segments and triggers thread-safe callbacks."""
        model = self._get_model()
        segments, info = model.transcribe(audio_path, beam_size=3, language="zh")
        
        duration = info.duration
        for segment in segments:
            text = segment.text.strip()
            if text and self._result_callback:
                result = RecognitionResult(
                    text=text, 
                    start=segment.start, 
                    end=segment.end, 
                    duration=duration
                )
                # Thread-safe callback to the main loop
                loop.call_soon_threadsafe(self._result_callback, result)

    async def close(self):
        """Cleanup."""
        pass

