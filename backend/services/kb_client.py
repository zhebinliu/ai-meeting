"""Async client for the external Knowledge Base (KB) system.

Authenticates with username/password against ``POST /api/auth/login`` to
obtain a JWT, caches it in-process, and on 401 transparently re-logins
once before retrying. Exposes a thin facade over the endpoints we use:

* :py:meth:`KBClient.list_projects`  – ``GET  /api/projects``
* :py:meth:`KBClient.upload_markdown` – ``POST /api/documents/upload``

The credentials and base URL come from :mod:`backend.config`. If the KB
is not configured (any of base url / user / password missing), every
method raises :class:`KBNotConfigured`.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class KBError(RuntimeError):
    """Generic KB API error (network / non-2xx responses)."""


class KBNotConfigured(KBError):
    """Raised when KB credentials/url are missing in the environment."""


class KBAuthError(KBError):
    """Raised when login fails (bad credentials, etc.)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class KBClient:
    """Process-wide singleton-style async client for the KB API.

    The class itself is reentrancy-safe: a single :class:`asyncio.Lock`
    serialises login attempts so concurrent uploads don't all try to
    re-authenticate.
    """

    # Class-level cache so multiple route invocations share one token.
    _token: str | None = None
    _token_expires_at: datetime | None = None
    _login_lock: asyncio.Lock = asyncio.Lock()

    # Treat the cached token as expiring 30 minutes earlier than the
    # server-side exp to avoid edge-case 401 right after a refresh.
    _SAFETY_MARGIN = timedelta(minutes=30)

    # ------------------------------------------------------------------
    # Construction & shared HTTP client
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        if not settings.kb_enabled:
            raise KBNotConfigured(
                "Knowledge Base sync is not configured. Set KNOWLEDGE_BASE_BASE_URL, "
                "KNOWLEDGE_BASE_USERNAME and KNOWLEDGE_BASE_PASSWORD in .env to enable."
            )
        self.base_url: str = settings.KB_BASE_URL.rstrip("/")
        self.username: str = settings.KB_USERNAME
        self.password: str = settings.KB_PASSWORD

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _ensure_token(self, *, force: bool = False) -> str:
        """Return a valid JWT, logging in on demand."""
        async with KBClient._login_lock:
            if (
                not force
                and KBClient._token
                and KBClient._token_expires_at
                and datetime.utcnow() + self._SAFETY_MARGIN < KBClient._token_expires_at
            ):
                return KBClient._token

            url = f"{self.base_url}/api/auth/login"
            payload = {"username": self.username, "password": self.password}
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                raise KBError(f"KB login network error: {exc}") from exc

            if resp.status_code != 200:
                raise KBAuthError(
                    f"KB login failed: HTTP {resp.status_code} – {resp.text[:200]}"
                )

            try:
                data = resp.json()
                token = data["access_token"]
            except (ValueError, KeyError) as exc:
                raise KBAuthError(
                    f"KB login response malformed: {resp.text[:200]}"
                ) from exc

            KBClient._token = token
            # The KB JWT we observed lasts ~7 days; assume 6 days to be safe
            # if we can't decode it. The server checks exp anyway.
            KBClient._token_expires_at = datetime.utcnow() + timedelta(days=6)
            logger.info("KB: obtained new access token (cached for 6 days)")
            return token

    # ------------------------------------------------------------------
    # Internal request helper with one-shot 401 retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        params: Any = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"

        async def _do_call(token: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(timeout=60.0) as client:
                return await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    files=files,
                    data=data,
                    params=params,
                )

        token = await self._ensure_token()
        try:
            resp = await _do_call(token)
        except httpx.HTTPError as exc:
            raise KBError(f"KB {method} {path} network error: {exc}") from exc

        if resp.status_code == 401:
            # Token expired despite our cache; force-refresh and retry once.
            logger.info("KB: 401 received, refreshing token and retrying once")
            token = await self._ensure_token(force=True)
            try:
                resp = await _do_call(token)
            except httpx.HTTPError as exc:
                raise KBError(f"KB {method} {path} retry network error: {exc}") from exc

        return resp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_projects(self) -> list[dict[str, Any]]:
        """Return all projects available to the current account."""
        resp = await self._request("GET", "/api/projects")
        if resp.status_code != 200:
            raise KBError(
                f"KB list_projects failed: HTTP {resp.status_code} – {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise KBError("KB list_projects returned non-JSON body") from exc

    async def upload_markdown(
        self,
        *,
        filename: str,
        content: str,
        project_id: str | None = None,
        doc_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload a Markdown document. Returns ``{id, filename, status}``.

        ``project_id`` and ``doc_type`` are optional. Defaults for
        ``doc_type`` come from :data:`settings.KB_DEFAULT_DOC_TYPE` when
        not supplied.
        """
        if not filename.endswith(".md"):
            filename = f"{filename}.md"
        # Keep filename short / filesystem-safe; KB stores it verbatim.
        safe_name = filename.replace("/", "_").replace("\\", "_")[:200]

        files = {
            "file": (
                safe_name,
                io.BytesIO(content.encode("utf-8")),
                "text/markdown",
            ),
        }
        form_data: dict[str, str] = {}
        if project_id:
            form_data["project_id"] = project_id
        effective_doc_type = doc_type or settings.KB_DEFAULT_DOC_TYPE
        if effective_doc_type:
            form_data["doc_type"] = effective_doc_type

        resp = await self._request(
            "POST",
            "/api/documents/upload",
            files=files,
            data=form_data or None,
        )

        if resp.status_code not in (200, 201):
            raise KBError(
                f"KB upload failed: HTTP {resp.status_code} – {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise KBError("KB upload returned non-JSON body") from exc

        # Augment with a viewable URL pointing at the SPA's document detail.
        # The web app currently lives at <base>/documents/<id>; we expose a
        # best-guess URL — frontend can still fall back to listing.
        doc_id = data.get("id")
        if doc_id:
            data["url"] = f"{self.base_url}/documents/{doc_id}"
        return data

    async def list_project_documents(self, project_id: str) -> list[dict[str, Any]]:
        """Return all documents that belong to ``project_id``.

        Items are summaries (no body) — use :py:meth:`get_document` to
        fetch the actual ``markdown_content`` for each.
        """
        if not project_id:
            return []
        resp = await self._request(
            "GET", f"/api/projects/{project_id}/documents"
        )
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise KBError(
                f"KB list_project_documents failed: HTTP {resp.status_code} – {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise KBError("KB list_project_documents returned non-JSON") from exc
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        return list(data) if isinstance(data, list) else []

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Fetch a single document detail.

        Returns the raw KB payload which includes ``markdown_content``,
        ``summary`` and ``faq`` fields; or ``None`` if the doc no longer
        exists. Other errors raise :class:`KBError`.
        """
        if not doc_id:
            return None
        resp = await self._request("GET", f"/api/documents/{doc_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise KBError(
                f"KB get_document failed: HTTP {resp.status_code} – {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise KBError("KB get_document returned non-JSON") from exc

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a previously uploaded document by its KB UUID.

        Returns ``True`` on success or if the document was already gone
        (404 is treated as idempotent success). Other errors raise
        :class:`KBError` so callers can decide whether to abort.
        """
        if not doc_id:
            return False
        resp = await self._request("DELETE", f"/api/documents/{doc_id}")
        if resp.status_code in (200, 204):
            return True
        if resp.status_code == 404:
            logger.info("KB delete: document %s already gone", doc_id)
            return True
        raise KBError(
            f"KB delete failed: HTTP {resp.status_code} – {resp.text[:200]}"
        )
