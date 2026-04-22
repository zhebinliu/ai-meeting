"""Polish raw ASR transcripts into clean, readable text."""

import logging
from typing import Optional

from .llm_client import LLMClient
from .prompts import POLISH_SYSTEM, POLISH_USER

logger = logging.getLogger(__name__)


class TextPolisher:
    """Remove filler words and fix grammar in raw meeting transcripts.

    Uses an LLM to clean up speech-to-text output while preserving
    original meaning, speaker labels, and domain terminology.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize with an LLM client instance.

        Args:
            llm_client: Configured :class:`LLMClient` for API calls.
        """
        self._llm = llm_client

    async def polish(
        self,
        raw_transcript: str,
        temperature: float = 0.3,
    ) -> str:
        """Polish a raw ASR transcript.

        Steps performed:
        1. Remove filler words (嗯, 啊, 那个, 这个, 就是说, etc.)
        2. Fix sentence structure and grammar
        3. Keep original meaning intact
        4. Preserve speaker labels if present
        5. Keep professional terminology unchanged

        Args:
            raw_transcript: Raw speech-to-text output.
            temperature: LLM temperature (lower = more deterministic).

        Returns:
            Polished transcript as a string.

        Raises:
            ValueError: If *raw_transcript* is empty.
            Exception: Propagated from :meth:`LLMClient.chat` on failure.
        """
        if not raw_transcript or not raw_transcript.strip():
            logger.warning("Empty transcript provided to polisher")
            raise ValueError("raw_transcript must not be empty")

        messages = [
            {"role": "system", "content": POLISH_SYSTEM},
            {
                "role": "user",
                "content": POLISH_USER.format(raw_transcript=raw_transcript),
            },
        ]

        logger.info("Polishing transcript (%d chars)", len(raw_transcript))
        result = await self._llm.chat(messages, temperature=temperature)
        logger.info("Polishing complete (%d chars)", len(result))
        return result
