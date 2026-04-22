"""Feishu Bitable Writer — writes extracted requirements to Feishu Bitable (多维表格).

Handles Bitable creation, table/field setup, and batch record insertion.
Supports full sync workflow: create Bitable if needed → ensure table exists
→ create missing fields → batch insert requirement records.

Typical usage:
    auth = FeishuAuth(app_id="cli_xxx", app_secret="xxx")
    writer = FeishuBitableWriter(auth)
    url = await writer.sync_requirements(app_token="", requirements=[...])
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from .auth import FeishuAPIError, FeishuAuth, FeishuAuthError, FeishuRateLimitError

logger = logging.getLogger(__name__)


# Field type constants (Feishu Bitable field_type enum)
FIELD_TYPE_TEXT = 1
FIELD_TYPE_NUMBER = 2
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_MULTI_SELECT = 4
FIELD_TYPE_DATE = 5
FIELD_TYPE_CHECKBOX = 7
FIELD_TYPE_CREATED_TIME = 1001
FIELD_TYPE_MODIFIED_TIME = 1002


# Default requirements table fields schema
REQUIREMENTS_TABLE_NAME = "需求清单"

REQUIRED_FIELDS: List[Dict[str, Any]] = [
    {
        "field_name": "需求编号",
        "type": FIELD_TYPE_TEXT,
    },
    {
        "field_name": "所属模块",
        "type": FIELD_TYPE_SINGLE_SELECT,
        "property": {
            "options": []  # Options are auto-created as values are added
        },
    },
    {
        "field_name": "需求描述",
        "type": FIELD_TYPE_TEXT,
    },
    {
        "field_name": "优先级",
        "type": FIELD_TYPE_SINGLE_SELECT,
        "property": {
            "options": [
                {"name": "P0", "color": 0},
                {"name": "P1", "color": 1},
                {"name": "P2", "color": 2},
                {"name": "P3", "color": 3},
            ]
        },
    },
    {
        "field_name": "需求来源",
        "type": FIELD_TYPE_TEXT,
    },
    {
        "field_name": "提出人",
        "type": FIELD_TYPE_TEXT,
    },
    {
        "field_name": "状态",
        "type": FIELD_TYPE_SINGLE_SELECT,
        "property": {
            "options": [
                {"name": "待确认", "color": 4},
                {"name": "已确认", "color": 1},
                {"name": "已排期", "color": 2},
                {"name": "已完成", "color": 7},
            ]
        },
    },
    {
        "field_name": "创建时间",
        "type": FIELD_TYPE_CREATED_TIME,
    },
]


class FeishuBitableWriter:
    """Manages requirements data in Feishu Bitable tables.

    Provides full lifecycle: create Bitable, configure tables and fields,
    and batch-insert requirement records.

    Args:
        auth: An authenticated FeishuAuth instance.
    """

    BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1"
    MAX_RETRIES = 3
    RATE_LIMIT_RETRY_DELAY = 5
    BATCH_CREATE_LIMIT = 500  # Feishu API limit per batch_create call

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

        Args:
            method: HTTP method.
            url: Fully-qualified request URL.
            json_body: Optional JSON request body.

        Returns:
            Parsed JSON response.

        Raises:
            FeishuAPIError: On non-retriable API errors.
            FeishuRateLimitError: When retries are exhausted.
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
                    retry_after = int(
                        resp.headers.get("Retry-After", self.RATE_LIMIT_RETRY_DELAY)
                    )
                    logger.warning(
                        "Rate limited (429), retry %d/%d after %ds",
                        rate_limit_retries,
                        self.MAX_RETRIES,
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                data = await resp.json()

                if resp.status != 200 or data.get("code", 0) != 0:
                    err_msg = f"Feishu Bitable API failure: status={resp.status}, code={data.get('code', 0)}, msg={data.get('msg', '')}"
                    logger.critical(err_msg)
                    if json_body:
                        logger.critical(f"Failed payload: {json_body}")
                    raise FeishuAPIError(
                        code=data.get("code", resp.status),
                        message=data.get("msg", f"HTTP {resp.status}"),
                    )

                return data

    # ---- Bitable creation ----

    async def create_bitable(
        self,
        name: str = "需求管理",
        folder_token: Optional[str] = None,
    ) -> str:
        """Create a new Feishu Bitable application.

        Args:
            name: Bitable display name.
            folder_token: Optional folder token to place the Bitable in.

        Returns:
            app_token of the newly created Bitable.

        Raises:
            FeishuAPIError: On API failure.
        """
        url = f"{self.BASE_URL}/apps"
        body: Dict[str, Any] = {"name": name}
        if folder_token:
            body["folder_token"] = folder_token

        logger.info("Creating Bitable: %s", name)
        resp = await self._request_with_retry("POST", url, json_body=body)
        app_token = resp.get("data", {}).get("app", {}).get("app_token")
        if not app_token:
            raise FeishuAPIError(code=-1, message="Failed to obtain app_token")
        logger.info("Bitable created: %s", app_token)
        return app_token

    # ---- Table management ----

    async def list_tables(self, app_token: str) -> List[Dict[str, Any]]:
        """List all tables in a Bitable.

        Args:
            app_token: Bitable application token.

        Returns:
            List of table metadata dicts (each has table_id, name, etc.).
        """
        url = f"{self.BASE_URL}/apps/{app_token}/tables"
        resp = await self._request_with_retry("GET", url)
        items = resp.get("data", {}).get("items", [])
        return items

    async def create_table(
        self,
        app_token: str,
        name: str,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Create a new table in the specified Bitable.

        Args:
            app_token: Bitable application token.
            name: Table name.
            fields: Optional list of field definitions to create with the table.

        Returns:
            table_id of the newly created table.
        """
        url = f"{self.BASE_URL}/apps/{app_token}/tables"
        body: Dict[str, Any] = {"table": {"name": name}}
        if fields:
            body["table"]["fields"] = fields

        logger.info("Creating table '%s' in Bitable %s", name, app_token)
        resp = await self._request_with_retry("POST", url, json_body=body)
        table_id = resp.get("data", {}).get("table_id")
        if not table_id:
            raise FeishuAPIError(code=-1, message="Failed to obtain table_id")
        logger.info("Table created: %s", table_id)
        return table_id

    async def get_or_create_requirements_table(self, app_token: str) -> str:
        """Return the requirements table ID, creating it if missing.

        Searches existing tables for one named REQUIREMENTS_TABLE_NAME.
        If not found, creates a new table with all required fields.

        Args:
            app_token: Bitable application token.

        Returns:
            table_id of the requirements table.
        """
        tables = await self.list_tables(app_token)
        for table in tables:
            if table.get("name") == REQUIREMENTS_TABLE_NAME:
                table_id = table.get("table_id")
                logger.info("Found existing requirements table: %s", table_id)
                return table_id

        logger.info("Requirements table not found, creating new one")
        return await self.create_table(
            app_token,
            REQUIREMENTS_TABLE_NAME,
            fields=REQUIRED_FIELDS,
        )

    # ---- Field management ----

    async def list_fields(self, app_token: str, table_id: str) -> List[Dict[str, Any]]:
        """List all fields in a table.

        Args:
            app_token: Bitable application token.
            table_id: Table identifier.

        Returns:
            List of field metadata dicts.
        """
        url = f"{self.BASE_URL}/apps/{app_token}/tables/{table_id}/fields"
        resp = await self._request_with_retry("GET", url)
        return resp.get("data", {}).get("items", [])

    async def create_table_fields(
        self,
        app_token: str,
        table_id: str,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Create missing fields in the requirements table.

        Compares the provided field definitions against existing fields
        and only creates those that do not yet exist (matched by name).

        Args:
            app_token: Bitable application token.
            table_id: Table identifier.
            fields: Field definitions to ensure exist. Defaults to REQUIRED_FIELDS.
        """
        target_fields = fields or REQUIRED_FIELDS
        existing = await self.list_fields(app_token, table_id)
        existing_names = {f.get("field_name") for f in existing}

        url = f"{self.BASE_URL}/apps/{app_token}/tables/{table_id}/fields"
        for field_def in target_fields:
            name = field_def.get("field_name")
            if name in existing_names:
                logger.debug("Field '%s' already exists, skipping", name)
                continue

            logger.info("Creating field '%s' in table %s", name, table_id)
            await self._request_with_retry("POST", url, json_body=field_def)

    # ---- Record operations ----

    async def batch_create_records(
        self,
        app_token: str,
        table_id: str,
        records: List[Dict[str, Any]],
    ) -> int:
        """Batch-insert records into a table.

        Automatically splits into chunks of BATCH_CREATE_LIMIT to respect
        the Feishu API constraint.

        Args:
            app_token: Bitable application token.
            table_id: Table identifier.
            records: List of record dicts, each with a 'fields' key.

        Returns:
            Total number of records successfully created.
        """
        url = f"{self.BASE_URL}/apps/{app_token}/tables/{table_id}/records/batch_create"
        total_created = 0

        for i in range(0, len(records), self.BATCH_CREATE_LIMIT):
            batch = records[i : i + self.BATCH_CREATE_LIMIT]
            logger.debug(
                "Batch creating records %d-%d in table %s",
                i,
                i + len(batch),
                table_id,
            )
            resp = await self._request_with_retry(
                "POST", url, json_body={"records": batch}
            )
            created = resp.get("data", {}).get("records", [])
            total_created += len(created)

        logger.info("Created %d records in table %s", total_created, table_id)
        return total_created

    # ---- High-level sync ----

    def _normalize_requirements(
        self, requirements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert external requirement dicts to Bitable record format.

        Handles both pre-formatted records (with 'fields' key) and
        flat requirement dicts by mapping known keys to the Bitable schema.

        Args:
            requirements: Raw requirement data.

        Returns:
            List of records ready for batch_create.
        """
        records: List[Dict[str, Any]] = []

        for idx, req in enumerate(requirements):
            # If already in record format, pass through
            if "fields" in req:
                records.append(req)
                continue

            # Map flat dict to Bitable field names
            fields: Dict[str, Any] = {}
            if "id" in req or "requirement_id" in req:
                fields["需求编号"] = req.get("id", req.get("requirement_id", f"REQ-{idx + 1:03d}"))
            else:
                fields["需求编号"] = f"REQ-{idx + 1:03d}"

            if "module" in req:
                fields["所属模块"] = req["module"]
            if "description" in req:
                fields["需求描述"] = req["description"]
            if "priority" in req:
                fields["优先级"] = req["priority"]
            if "source" in req:
                fields["需求来源"] = req["source"]
            if "speaker" in req:
                fields["提出人"] = req["speaker"]
            if "status" in req:
                fields["状态"] = req["status"]
            else:
                fields["状态"] = "待确认"

            records.append({"fields": fields})

        return records

    async def sync_requirements(
        self,
        app_token: str,
        requirements: List[Dict[str, Any]],
    ) -> tuple[str, str | None]:
        """Full sync: ensure Bitable/table/fields exist, then insert records.

        If app_token is empty, creates a new Bitable first.

        Args:
            app_token: Existing Bitable app_token, or empty string to create new.
            requirements: List of requirement dicts. Supports both flat dicts
                (with keys like 'description', 'priority') and pre-formatted
                records (with 'fields' key).

        Returns:
            Tuple of (bitable_url, new_app_token).
            ``new_app_token`` is the token of a newly created Bitable, or
            ``None`` if an existing Bitable was reused.
        """
        new_app_token: str | None = None

        # Create Bitable if needed
        if not app_token:
            app_token = await self.create_bitable(name="需求管理")
            new_app_token = app_token

        # Ensure table exists
        table_id = await self.get_or_create_requirements_table(app_token)

        # Ensure fields exist
        await self.create_table_fields(app_token, table_id)

        # Normalize and insert records
        if requirements:
            records = self._normalize_requirements(requirements)
            await self.batch_create_records(app_token, table_id, records)

        bitable_url = f"https://feishu.cn/base/{app_token}"
        logger.info("Requirements synced to Bitable: %s", bitable_url)
        return bitable_url, new_app_token
