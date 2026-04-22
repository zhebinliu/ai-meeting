import logging
import asyncio
import os
import tempfile
from typing import Callable, Optional
from faster_whisper import WhisperModel
from services.asr.audio_utils import AudioUtils

logger = logging.getLogger(__name__)

class RecognitionResult:
    """ASR recognition result compatible with the existing pipeline."""
    def __init__(self, text: str, is_final: bool = True):
        self.text = text
        self.is_final = is_final

class WhisperASRClient:
    """ASR Client using Faster-Whisper local model."""
    
    _model_cache = {}

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        """Initialize Whisper model.
        
        Args:
            model_size: Model size (tiny, base, small, medium, large-v3).
            device: 'cpu' or 'cuda'.
            compute_type: quantization (int8, float16, etc).
        """
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
        """Transcribe long PCM data by running Faster-Whisper in a thread pool."""
        if not pcm_data:
            logger.warning("No audio data to transcribe")
            return

        # 1. Convert PCM to WAV for Whisper
        wav_data = AudioUtils.pcm_to_wav(pcm_data)
        
        # 2. Save to temporary file (faster-whisper takes file path or stream)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_data)
            tmp_path = tmp.name

        try:
            # 3. Run transcription in thread pool to avoid blocking event loop
            loop = asyncio.get_running_loop()
            segments, info = await loop.run_in_executor(
                None, 
                self._run_transcription, 
                tmp_path
            )

            # 4. Process segments and trigger callbacks
            full_text = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    full_text.append(text)
                    if self._result_callback:
                        self._result_callback(RecognitionResult(text=text))
            
            logger.info("Whisper ASR: Completed transcription (%d segments)", len(full_text))
            
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _run_transcription(self, audio_path: str):
        """Internal synchronous transcription method."""
        model = self._get_model()
        # beam_size=3 is a good balance for Speed vs Accuracy
        segments, info = model.transcribe(audio_path, beam_size=3, language="zh")
        # Consume generator into a list to ensure it's fully processed in the executor
        return list(segments), info

    async def close(self):
        """Cleanup (optional for local model)."""
        pass
