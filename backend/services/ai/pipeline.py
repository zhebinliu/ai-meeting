"""End-to-end meeting AI processing pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient
from .text_polisher import TextPolisher
from .minutes_generator import MinutesGenerator
from .requirement_extractor import RequirementExtractor

logger = logging.getLogger(__name__)


class MeetingAIPipeline:
    """Orchestrates transcript polishing, minutes generation, and
    requirement extraction in a single async call.

    Usage::

        pipeline = MeetingAIPipeline(openai_api_key="sk-...")
        result = await pipeline.process(raw_transcript, meeting_title="Q1 Review")
    """

    def __init__(self, openai_api_key: str, model: str = "Qwen3-Next-80B-A3B-Instruct", base_url: str | None = None) -> None:
        """Initialize all sub-components.

        Args:
            openai_api_key: API key.
            model: Model name passed to :class:`LLMClient`.
            base_url: Custom API base URL for OpenAI-compatible providers.
        """
        self.llm = LLMClient(api_key=openai_api_key, model=model, base_url=base_url)
        self.polisher = TextPolisher(self.llm)
        self.minutes_gen = MinutesGenerator(self.llm)
        self.req_extractor = RequirementExtractor(self.llm)
        logger.info("MeetingAIPipeline ready (model=%s)", model)

    async def process(
        self,
        raw_transcript: str,
        meeting_title: str = "",
        requirement_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the full processing pipeline.

        Steps:
            1. Polish the raw transcript.
            2. Generate structured meeting minutes.
            3. Extract customer requirements.

        Args:
            raw_transcript: Raw ASR output to process.
            meeting_title: Optional meeting title for minutes context.
            requirement_context: Optional extra context for extraction
                (e.g. ``{"project": "CRM"}``).

        Returns:
            Dict with keys:
            - **polished_transcript**: Cleaned transcript string.
            - **meeting_minutes**: Structured minutes dict.
            - **requirements**: List of requirement dicts.
        """
        logger.info("Pipeline start — title='%s', %d chars", meeting_title, len(raw_transcript))

        # Step 1: Polish
        polished = await self.polisher.polish(raw_transcript)

        # Step 2 & 3: Run minutes and requirements in parallel
        # (they are independent of each other)
        import asyncio

        minutes, requirements = await asyncio.gather(
            self.minutes_gen.generate(polished, meeting_title=meeting_title),
            self.req_extractor.extract(polished, context=requirement_context),
        )

        logger.info(
            "Pipeline done — %d key_points, %d decisions, %d action_items, %d requirements",
            len(minutes.get("key_points", [])),
            len(minutes.get("decisions", [])),
            len(minutes.get("action_items", [])),
            len(requirements),
        )

        return {
            "polished_transcript": polished,
            "meeting_minutes": minutes,
            "requirements": requirements,
        }
