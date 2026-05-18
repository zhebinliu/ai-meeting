"""Generate structured meeting minutes from polished transcripts."""

import json
import logging
from typing import Any, Dict, Optional

from .llm_client import LLMClient
from .prompts import MINUTES_SYSTEM, MINUTES_USER

logger = logging.getLogger(__name__)

# Default empty structure returned on parse failure
_EMPTY_MINUTES: Dict[str, Any] = {
    "summary": "",
    "attendees": [],
    "key_points": [],
    "decisions": [],
    "action_items": [],
}


class MinutesGenerator:
    """Produce structured meeting minutes from a transcript.

    The output is a dict with keys: ``summary``, ``attendees``,
    ``key_points``, ``decisions``, and ``action_items``.

    Optionally accepts a template dict (from ``MeetingTemplate``) whose
    ``format_requirements``, ``style_preferences`` and ``schema_structure``
    fields are injected into the system prompt.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize with an LLM client instance.

        Args:
            llm_client: Configured :class:`LLMClient` for API calls.
        """
        self._llm = llm_client

    async def generate(
        self,
        polished_transcript: str,
        meeting_title: str = "",
        temperature: float = 0.3,
        template: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate structured meeting minutes from a polished transcript.

        Args:
            polished_transcript: Cleaned meeting transcript text.
            meeting_title: Optional meeting title for context.
            temperature: LLM temperature (lower = more deterministic).
            template: Optional template dict with keys ``format_requirements``,
                ``style_preferences``, ``schema_structure``. If provided,
                the system prompt is augmented with these preferences.

        Returns:
            Dict with keys:
            - **summary**: Overall meeting summary string.
            - **attendees**: List of identified attendee names.
            - **key_points**: List of ``{"topic": ..., "content": ...}``.
            - **decisions**: List of ``{"content": ..., "owner": ...}``.
            - **action_items**: List of ``{"task": ..., "owner": ..., "deadline": ...}``.

        Raises:
            ValueError: If *polished_transcript* is empty.
        """
        if not polished_transcript or not polished_transcript.strip():
            raise ValueError("polished_transcript must not be empty")

        system_prompt = self._build_system_prompt(template)

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": MINUTES_USER.format(
                    meeting_title=meeting_title or "(未指定)",
                    transcript=polished_transcript,
                ),
            },
        ]

        logger.info(
            "Generating minutes for '%s' (%d chars)%s",
            meeting_title,
            len(polished_transcript),
            " with template" if template else "",
        )
        raw = await self._llm.chat(messages, temperature=temperature)

        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(
        template: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Augment the base MINUTES_SYSTEM with template preferences.

        Args:
            template: Optional dict with ``format_requirements``,
                ``style_preferences``, and/or ``schema_structure`` keys.

        Returns:
            The augmented system prompt string.
        """
        if template is None:
            return MINUTES_SYSTEM

        parts = [MINUTES_SYSTEM]
        f = (template.get("format_requirements") or "").strip()
        s = (template.get("style_preferences") or "").strip()
        sc = (template.get("schema_structure") or "").strip()

        if f:
            parts.append(f"\n## 格式要求\n{f}\n")
        if s:
            parts.append(f"\n## 风格偏好\n{s}\n")
        if sc:
            parts.append(f"\n## 期望的输出结构\n{sc}\n")

        return "\n".join(parts)

    @staticmethod
    def _parse_response(raw: str) -> Dict[str, Any]:
        """Parse the LLM JSON response, with fallback for fenced blocks.

        Args:
            raw: Raw string returned by the LLM.

        Returns:
            Parsed dict or an empty template on failure.
        """
        text = raw.strip()
        # Strip markdown fences if the model added them despite instructions
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            text = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else ""
        try:
            result = json.loads(text)
            logger.info("Minutes parsed successfully")
            return result
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to parse minutes JSON: %s\nRaw: %s", exc, raw)
            return {**_EMPTY_MINUTES, "_raw": raw}
