"""OpenAI API wrapper with retry logic and streaming support."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, List, Dict, Any

from openai import AsyncOpenAI, APIError, RateLimitError

logger = logging.getLogger(__name__)

# Default retry configuration
MAX_RETRIES: int = 3
RETRY_BASE_DELAY: float = 1.0  # seconds


class LLMClient:
    """Async wrapper around the OpenAI Chat Completions API.

    Provides retry logic for transient failures and rate limits,
    plus both regular and streaming completion methods.

    Attributes:
        model: The model identifier used for completions.
    """

    def __init__(self, api_key: str, model: str = "Qwen3-Next-80B-A3B-Instruct", base_url: str | None = None) -> None:
        """Initialize the LLM client.

        Args:
            api_key: API key (must not be hardcoded in source).
            model: Model name, defaults to ``Qwen3-Next-80B-A3B-Instruct``.
            base_url: Custom API base URL for OpenAI-compatible providers.
        """
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        logger.info("LLMClient initialized with model=%s", model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
    ) -> str:
        """Send a chat completion request and return the full response text.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            temperature: Sampling temperature (0.0 – 2.0).

        Returns:
            The assistant reply as a plain string.

        Raises:
            APIError: When all retries are exhausted.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                )
                content: str = response.choices[0].message.content or ""
                logger.debug(
                    "chat completion OK (attempt %d, tokens=%s)",
                    attempt,
                    response.usage,
                )
                return content
            except RateLimitError as exc:
                logger.warning(
                    "Rate limit hit (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    raise
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            except APIError as exc:
                logger.error(
                    "API error (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    raise
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))

        # Should never reach here, but satisfies type checker
        raise RuntimeError("Unexpected exit from retry loop")

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response chunk by chunk.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            temperature: Sampling temperature (0.0 – 2.0).

        Yields:
            Successive text chunks as they arrive from the API.

        Raises:
            APIError: When all retries are exhausted.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                stream = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                return  # Stream completed successfully
            except RateLimitError as exc:
                logger.warning(
                    "Rate limit hit during stream (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    raise
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            except APIError as exc:
                logger.error(
                    "API error during stream (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    raise
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
