"""Feishu Document Writer — creates and populates Feishu documents with meeting minutes.

Uses the Feishu Document API (docx/v1) to create new documents and append
structured blocks (headings, text, bullet lists) for meeting minutes in
Miao-ji (妙记) style.

Typical usage:
    auth = FeishuAuth(app_id="cli_xxx", app_secret="xxx")
    writer = FeishuDocWriter(auth)
    doc_url = await writer.create_meeting_doc(meeting_data)
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from .auth import FeishuAPIError, FeishuAuth, FeishuAuthError, FeishuRateLimitError
from .templates import DocTemplates

logger = logging.getLogger(__name__)


class FeishuDocWriter:
    """Creates Feishu documents populated with meeting minutes content.

    Handles document creation and sequential block insertion with
    automatic token management and error handling.

    Args:
        auth: An authenticated FeishuAuth instance.
    """

    BASE_URL = "https://open.feishu.cn/open-apis/docx/v1"
    MAX_RETRIES = 3
    RATE_LIMIT_RETRY_DELAY = 5  # seconds

    def __init__(self, auth: FeishuAuth) -> None:
        self._auth = auth
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return or create a reusable aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _authorized_headers(self) -> Dict[str, str]:
        """Return headers with a valid Bearer token."""
        token = await self._auth.get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request with retry on rate limits and 401.

        On 401, refreshes the token and retries once.
        On 429, waits and retries up to MAX_RETRIES times.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Fully-qualified request URL.
            json_body: Optional JSON request body.

        Returns:
            Parsed JSON response.

        Raises:
            FeishuAPIError: On non-retriable API errors.
            FeishuRateLimitError: When retries are exhausted on 429.
        """
        import asyncio

        session = await self._get_session()
        rate_limit_retries = 0
        auth_retries = 0

        while True:
            headers = await self._authorized_headers()
            async with session.request(method, url, headers=headers, json=json_body) as resp:
                if resp.status == 401:
                    auth_retries += 1
                    if auth_retries > self.MAX_RETRIES:
                        raise FeishuAuthError(
                            code=401,
                            message=f"Authentication failed after {self.MAX_RETRIES} token refreshes",
                        )
                    logger.info("Received 401, refreshing token and retrying (%d/%d)",
                                auth_retries, self.MAX_RETRIES)
                    try:
                        await self._auth.refresh_token()
                    except FeishuAuthError:
                        raise
                    continue

                if resp.status == 429:
                    rate_limit_retries += 1
                    if rate_limit_retries > self.MAX_RETRIES:
                        raise FeishuRateLimitError(
                            code=429,
                            message=f"Rate limit exceeded after {self.MAX_RETRIES} retries",
                        )
                    retry_after = int(resp.headers.get("Retry-After", self.RATE_LIMIT_RETRY_DELAY))
                    logger.warning("Rate limited (429), retry %d/%d after %ds",
                                   rate_limit_retries, self.MAX_RETRIES, retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                data = await resp.json()

                if resp.status != 200 or data.get("code", 0) != 0:
                    err_msg = f"Feishu API failure: status={resp.status}, code={data.get('code', 0)}, msg={data.get('msg', '')}"
                    logger.critical(err_msg)
                    if json_body:
                        logger.critical(f"Failed payload: {json_body}")
                    raise FeishuAPIError(
                        code=data.get("code", resp.status),
                        message=data.get("msg", f"HTTP {resp.status}"),
                    )

                return data

    def _format_doc_content(self, meeting_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert meeting data into a list of Feishu document block dicts.

        Builds the block tree for the document body. Each block is a dict
        conforming to the Feishu docx block schema.

        Args:
            meeting_data: Structured meeting data dictionary.

        Returns:
            List of block dictionaries ready for the batch-create API.
        """
        blocks: List[Dict[str, Any]] = []
        title = meeting_data.get("title", "未命名会议")
        start_time = meeting_data.get("start_time", "")
        end_time = meeting_data.get("end_time", "")
        attendees: List[str] = meeting_data.get("attendees", [])
        summary: str = meeting_data.get("summary", "")
        key_points: List[str] = meeting_data.get("key_points", [])
        decisions: List[Dict[str, str]] = meeting_data.get("decisions", [])
        action_items: List[Dict[str, str]] = meeting_data.get("action_items", [])
        full_transcript: str = meeting_data.get("full_transcript", "")

        # --- Document title (H1) ---
        date_str = meeting_data.get("date", start_time)
        if date_str:
            h1_text = f"会议纪要 - {title} - {date_str}"
        else:
            h1_text = f"会议纪要 - {title}"
        blocks.append(self._heading1_block(h1_text))

        # --- Basic Info (H2 + content) ---
        blocks.append(self._heading2_block("基本信息"))
        blocks.append(self._text_block(f"会议标题：{title}"))
        if start_time and end_time:
            blocks.append(self._text_block(f"会议时间：{start_time} - {end_time}"))
        elif start_time:
            blocks.append(self._text_block(f"会议时间：{start_time}"))
        if attendees:
            blocks.append(self._text_block(f"参会人员：{', '.join(attendees)}"))

        # --- Summary ---
        if summary:
            blocks.append(self._heading2_block("会议概述"))
            blocks.append(self._text_block(summary))

        # --- Key Points ---
        if key_points:
            blocks.append(self._heading2_block("讨论要点"))
            for point in key_points:
                topic = point.get("topic", "")
                content = point.get("content", "")
                if topic and content:
                    blocks.append(self._bullet_block(f"【{topic}】：{content}"))
                elif topic or content:
                    blocks.append(self._bullet_block(topic or content))

        # --- Decisions ---
        if decisions:
            blocks.append(self._heading2_block("决议事项"))
            for decision in decisions:
                content = decision.get("content", "")
                owner = decision.get("owner", "")
                if owner:
                    blocks.append(self._bullet_block(f"{content}（负责人：{owner}）"))
                else:
                    blocks.append(self._bullet_block(content))

        # --- Action Items ---
        if action_items:
            blocks.append(self._heading2_block("待办事项"))
            for item in action_items:
                content = item.get("task", "")
                owner = item.get("owner", "")
                deadline = item.get("deadline", "")
                parts = [content]
                if owner:
                    parts.append(f"负责人：{owner}")
                if deadline:
                    parts.append(f"截止：{deadline}")
                blocks.append(self._todo_block(" - ".join(parts)))

        # --- Full Transcript ---
        if full_transcript:
            blocks.append(self._heading2_block("完整转写"))
            for line in full_transcript.split("\n"):
                stripped = line.strip()
                if stripped:
                    blocks.append(self._text_block(stripped))

        return blocks

    # ---- Block factory helpers ----

    @staticmethod
    def _heading1_block(text: str) -> Dict[str, Any]:
        """Create a heading-1 block."""
        return {
            "block_type": 3,
            "heading1": {
                "elements": [
                    {
                        "text_run": {
                            "content": text or " ",
                            "text_element_style": {}
                        }
                    }
                ],
                "style": {}
            },
        }

    @staticmethod
    def _heading2_block(text: str) -> Dict[str, Any]:
        """Create a heading-2 block."""
        return {
            "block_type": 4,
            "heading2": {
                "elements": [
                    {
                        "text_run": {
                            "content": text or " ",
                            "text_element_style": {}
                        }
                    }
                ],
                "style": {}
            },
        }

    @staticmethod
    def _text_block(text: str) -> Dict[str, Any]:
        """Create a paragraph text block."""
        return {
            "block_type": 2,
            "text": {
                "elements": [
                    {
                        "text_run": {
                            "content": text or " ",
                            "text_element_style": {}
                        }
                    }
                ],
                "style": {}
            },
        }

    @staticmethod
    def _bullet_block(text: str) -> Dict[str, Any]:
        """Create a bullet (unordered list) block."""
        return {
            "block_type": 12,
            "bullet": {
                "elements": [
                    {
                        "text_run": {
                            "content": text or " ",
                            "text_element_style": {}
                        }
                    }
                ],
                "style": {}
            },
        }

    @staticmethod
    def _todo_block(text: str) -> Dict[str, Any]:
        """Create a todo block."""
        return {
            "block_type": 17,
            "todo": {
                "elements": [
                    {
                        "text_run": {
                            "content": text or " ",
                            "text_element_style": {}
                        }
                    }
                ],
                "style": {}
            },
        }

    # ---- Public API ----

    async def create_meeting_doc(
        self,
        meeting_data: Dict[str, Any],
        folder_token: Optional[str] = None,
    ) -> str:
        """Create a Feishu document with meeting minutes and return its URL.

        Steps:
            1. Create an empty document via the docx API.
            2. Build content blocks from meeting_data.
            3. Batch-append blocks to the document body.

        Args:
            meeting_data: Structured meeting data (see DocTemplates.meeting_minutes).
            folder_token: Optional folder token to create the document in.

        Returns:
            URL string of the created Feishu document.

        Raises:
            FeishuAPIError: On any API failure.
        """
        # Step 1: Create empty document
        title = DocTemplates.meeting_doc_title(meeting_data)
        create_url = f"{self.BASE_URL}/documents"
        create_body: Dict[str, Any] = {"title": title}
        if folder_token:
            create_body["folder_token"] = folder_token

        logger.info("Creating Feishu document: %s", title)
        create_resp = await self._request_with_retry("POST", create_url, json_body=create_body)

        doc_data = create_resp.get("data", {}).get("document", {})
        document_id = doc_data.get("document_id")
        if not document_id:
            raise FeishuAPIError(
                code=-1,
                message="Failed to obtain document_id from create response",
            )

        logger.info("Document created: %s", document_id)

        # Step 2: Build content blocks
        blocks = self._format_doc_content(meeting_data)
        if not blocks:
            logger.warning("No content blocks generated for document %s", document_id)
            return f"https://feishu.cn/docx/{document_id}"

        # Step 3: Single-append blocks for precision debugging
        batch_size = 1
        
        # Best practice: get the actual root block_id of the document
        get_url = f"{self.BASE_URL}/documents/{document_id}"
        get_resp = await self._request_with_retry("GET", get_url)
        body_root_block_id = get_resp.get("data", {}).get("document", {}).get("block_id")
        
        if not body_root_block_id:
            logger.warning("Could not fetch root block_id, falling back to document_id")
            body_root_block_id = document_id
        
        append_url = (
            f"{self.BASE_URL}/documents/{document_id}/"
            f"blocks/{body_root_block_id}/children"
        )

        for i in range(0, len(blocks), batch_size):
            batch = blocks[i : i + batch_size]
            logger.info("Appending blocks %d-%d to document %s",
                         i + 1, i + len(batch), document_id)
            await self._request_with_retry(
                "POST",
                append_url,
                json_body={"children": batch, "index": -1},
            )

        doc_url = f"https://feishu.cn/docx/{document_id}"
        logger.info("Document populated: %s (%d blocks)", doc_url, len(blocks))
        return doc_url
