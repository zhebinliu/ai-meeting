"""Feishu OAuth 2.0 authentication module.

Provides tenant access token management with automatic refresh on expiry.
All API interactions require a valid tenant access token obtained through
the internal application credentials (app_id + app_secret).

Typical usage:
    auth = FeishuAuth(app_id="cli_xxx", app_secret="xxx")
    token = await auth.get_tenant_access_token()
"""

import time
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class FeishuAPIError(Exception):
    """Base exception for Feishu API errors.

    Attributes:
        code: Feishu API error code (0 means success).
        message: Human-readable error description.
    """

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Feishu API error {code}: {message}")


class FeishuAuthError(FeishuAPIError):
    """Raised when authentication fails (invalid credentials, expired token)."""
    pass


class FeishuRateLimitError(FeishuAPIError):
    """Raised when the API returns HTTP 429 (rate limit exceeded)."""
    pass


class FeishuAuth:
    """Manages Feishu tenant access tokens with automatic refresh.

    The tenant access token is scoped to the application and is required
    for all subsequent API calls. Tokens expire after ~2 hours; this class
    handles caching and refresh transparently.

    Args:
        app_id: Feishu application ID (format: cli_xxx).
        app_secret: Feishu application secret.
    """

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    TOKEN_EXPIRY_BUFFER_SECONDS = 300  # Refresh 5 min before actual expiry

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return or create a reusable aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session. Call on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_tenant_access_token(self) -> str:
        """Return a valid tenant access token, refreshing if expired.

        Returns:
            The tenant access token string.

        Raises:
            FeishuAuthError: If the token request fails.
            FeishuRateLimitError: If the API rate limit is hit.
        """
        if self._token and time.time() < self._expires_at - self.TOKEN_EXPIRY_BUFFER_SECONDS:
            return self._token

        return await self.refresh_token()

    async def refresh_token(self) -> str:
        """Force-refresh the tenant access token.

        Returns:
            The new tenant access token string.

        Raises:
            FeishuAuthError: If the token request fails.
            FeishuRateLimitError: If the API rate limit is hit.
        """
        logger.info("Refreshing Feishu tenant access token")
        session = await self._get_session()
        payload = {
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }

        async with session.post(self.TOKEN_URL, json=payload) as resp:
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After", "60")
                raise FeishuRateLimitError(
                    code=429,
                    message=f"Rate limit exceeded. Retry after {retry_after}s",
                )

            if resp.status != 200:
                body = await resp.text()
                raise FeishuAuthError(
                    code=resp.status,
                    message=f"HTTP {resp.status}: {body}",
                )

            data = await resp.json()

        if data.get("code") != 0:
            raise FeishuAuthError(
                code=data.get("code", -1),
                message=data.get("msg", "Unknown error"),
            )

        self._token = data["tenant_access_token"]
        expire_seconds = data.get("expire", 7200)
        self._expires_at = time.time() + expire_seconds

        logger.info(
            "Tenant access token acquired, expires in %d seconds", expire_seconds
        )
        return self._token
