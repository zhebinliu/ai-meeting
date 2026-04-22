"""Extract customer requirements from meeting transcripts."""

import json
import logging
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient
from .prompts import REQUIREMENT_SYSTEM, REQUIREMENT_USER

logger = logging.getLogger(__name__)


class RequirementExtractor:
    """Identify and structure customer requirements from transcript text.

    Extracted requirements are grouped by business module and tagged
    with priority (P0–P3), source context, and the speaker who raised
    the requirement.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize with an LLM client instance.

        Args:
            llm_client: Configured :class:`LLMClient` for API calls.
        """
        self._llm = llm_client

    async def extract(
        self,
        transcript: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Extract requirements from a meeting transcript.

        Args:
            transcript: Meeting transcript (raw or polished).
            context: Optional additional context such as ``{"project": "CRM"}``
                that will be appended to the prompt for better grounding.
            temperature: LLM temperature (lower = more deterministic).

        Returns:
            List of requirement dicts, each containing:
            - **req_id**: Unique identifier (``REQ-001`` format).
            - **module**: Business module name.
            - **description**: Requirement description.
            - **priority**: ``P0`` / ``P1`` / ``P2`` / ``P3``.
            - **source**: Original sentence from the transcript.
            - **speaker**: Person who raised the requirement.

        Raises:
            ValueError: If *transcript* is empty.
        """
        if not transcript or not transcript.strip():
            raise ValueError("transcript must not be empty")

        prompt = REQUIREMENT_USER.format(transcript=transcript)

        # Optionally append extra context
        if context:
            ctx_lines = "\n".join(f"- {k}: {v}" for k, v in context.items())
            prompt += f"\n\n补充上下文：\n{ctx_lines}"

        messages = [
            {"role": "system", "content": REQUIREMENT_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        logger.info("Extracting requirements (%d chars)", len(transcript))
        raw = await self._llm.chat(messages, temperature=temperature)

        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw: str) -> List[Dict[str, Any]]:
        """Parse the LLM JSON array response, with fallback.

        Args:
            raw: Raw string returned by the LLM.

        Returns:
            Parsed list or empty list on failure.
        """
        text = raw.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else ""
        try:
            result = json.loads(text)
            if not isinstance(result, list):
                logger.warning("Expected JSON array, got %s", type(result))
                return []
            logger.info("Extracted %d requirements", len(result))
            return result
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to parse requirements JSON: %s\nRaw: %s", exc, raw)
            return []
