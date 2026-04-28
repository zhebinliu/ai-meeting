"""End-to-end meeting AI processing pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient
from .text_polisher import TextPolisher
from .minutes_generator import MinutesGenerator
from .requirement_extractor import RequirementExtractor
from .stakeholder_extractor import StakeholderExtractor

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
        self.stakeholder_extractor = StakeholderExtractor(self.llm)
        logger.info("MeetingAIPipeline ready (model=%s)", model)

    async def process(
        self,
        raw_transcript: str,
        meeting_title: str = "",
        requirement_context: Optional[Dict[str, Any]] = None,
        meeting_id: int | None = None,
        kb_docs: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run the full processing pipeline.

        Steps:
            1. Polish the raw transcript.
            2. Generate structured meeting minutes.
            3. Extract customer requirements.
            4. Extract stakeholder graph (uses minutes + optional KB docs).

        Args:
            raw_transcript: Raw ASR output to process.
            meeting_title: Optional meeting title for minutes context.
            requirement_context: Optional extra context for extraction
                (e.g. ``{"project": "CRM"}``).
            meeting_id: Optional integer used as ``meeting_id`` reference
                in stakeholder source citations.
            kb_docs: Optional list of KB document detail dicts (each with
                ``id``, ``filename``, ``markdown_content``, ``summary``)
                whose people will be merged into the stakeholder graph.

        Returns:
            Dict with keys:
            - **polished_transcript**: Cleaned transcript string.
            - **meeting_minutes**: Structured minutes dict.
            - **requirements**: List of requirement dicts.
            - **stakeholder_map**: ``{stakeholders: [...], relations: [...]}``
        """
        logger.info("Pipeline start — title='%s', %d chars", meeting_title, len(raw_transcript))

        # Step 1: Polish
        polished = await self.polisher.polish(raw_transcript)

        # Step 2 & 3: minutes and requirements run in parallel (independent).
        import asyncio

        minutes, requirements = await asyncio.gather(
            self.minutes_gen.generate(polished, meeting_title=meeting_title),
            self.req_extractor.extract(polished, context=requirement_context),
        )

        # Step 4: stakeholder graph — depends on the minutes + transcript +
        # optional KB context, so it runs last (still relatively cheap).
        stakeholder_map: Dict[str, Any] = {"stakeholders": [], "relations": []}
        try:
            stakeholder_map = await self.stakeholder_extractor.extract(
                meeting_id=meeting_id or 0,
                meeting_title=meeting_title,
                transcript=polished,
                minutes=minutes,
                kb_docs=kb_docs or [],
            )
        except Exception:  # noqa: BLE001
            # Stakeholder extraction is "extra" — never let it fail the
            # whole pipeline. Just log and continue with an empty map.
            logger.exception("Stakeholder extraction failed; continuing with empty map")

        logger.info(
            "Pipeline done — %d key_points, %d decisions, %d action_items, %d requirements, %d stakeholders",
            len(minutes.get("key_points", [])),
            len(minutes.get("decisions", [])),
            len(minutes.get("action_items", [])),
            len(requirements),
            len(stakeholder_map.get("stakeholders", [])),
        )

        return {
            "polished_transcript": polished,
            "meeting_minutes": minutes,
            "requirements": requirements,
            "stakeholder_map": stakeholder_map,
        }
