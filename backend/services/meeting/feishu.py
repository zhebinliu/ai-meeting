"""飞书集成 minimal MVP(2026-05-11)。

源自 meeting-ai/services/feishu/ 的精简迁移,只保留两个核心能力:
1. 把会议纪要 markdown 导出为飞书 docx 文档
2. 把需求清单批量写入飞书多维表(用户预先创建好表)

凭证策略:每个用户在 Settings.tsx 里配置自己的 feishu_app_id + feishu_app_secret。
不复用全局凭证(用户拍板,2026-05-11)。

依赖:仅 httpx(避免引入 aiohttp / cryptography)。
"""
from __future__ import annotations

import time
from typing import Optional

import httpx
import structlog

from models.user import User

logger = structlog.get_logger()

# ── 常量 ──────────────────────────────────────────────────────────────────

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_DOCX_BASE = "https://open.feishu.cn/open-apis/docx/v1"
_BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
_TIMEOUT = 30.0


class FeishuError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"飞书 API 错误 code={code}: {message}")


# ── 凭证读取 ───────────────────────────────────────────────────────────

def get_user_feishu_credentials(user: User) -> Optional[tuple[str, str]]:
    """从 User 模型读出飞书凭证。未配置返回 None。"""
    if not user.feishu_app_id or not user.feishu_app_secret:
        return None
    return user.feishu_app_id, user.feishu_app_secret


# ── 简易 token 缓存(内存级,进程内)──────────────────────────────────

_token_cache: dict[str, tuple[str, float]] = {}  # app_id -> (token, expires_at)


async def get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取 tenant access token,5 分钟内缓存复用。"""
    cached = _token_cache.get(app_id)
    if cached and time.time() < cached[1] - 300:  # 5 分钟提前刷新
        return cached[0]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(_TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret})
        if resp.status_code != 200:
            raise FeishuError(resp.status_code, f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuError(data.get("code", -1), data.get("msg", "未知错误"))
        token = data["tenant_access_token"]
        expires_at = time.time() + data.get("expire", 7200)
        _token_cache[app_id] = (token, expires_at)
        logger.info("feishu_token_refreshed", app_id=app_id[:8] + "***", expire=data.get("expire"))
        return token


# ── markdown → 飞书 docx blocks(简化版) ──────────────────────────────

def _markdown_to_blocks(markdown: str) -> list[dict]:
    """把 markdown 按段落拆成飞书 text blocks(简化:不解析 # / 表格 / 列表格式)。

    飞书 docx 的 block_type:
      - 2: 文本段落
      - 3-9: 标题 1-7(我们简化只用 2)
    """
    blocks: list[dict] = []
    # 按双换行拆段
    paragraphs = [p.strip() for p in markdown.split("\n\n") if p.strip()]
    if not paragraphs:
        # 兜底:单段
        paragraphs = [markdown.strip() or "(无内容)"]

    for para in paragraphs:
        # 单段过长(飞书 docx 单 text 元素限制 8000 字)→ 截断
        text = para[:7900]
        blocks.append({
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": text}}
                ]
            },
        })
    return blocks


# ── 文档导出 ───────────────────────────────────────────────────────────

async def create_doc_with_markdown(
    app_id: str,
    app_secret: str,
    title: str,
    markdown: str,
    folder_token: Optional[str] = None,
) -> tuple[str, str]:
    """创建飞书 docx 文档并写入 markdown 内容。

    返回 (document_id, url)。失败抛 FeishuError。
    """
    token = await get_tenant_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # 1. 创建空文档
        body: dict = {"title": title[:120]}
        if folder_token:
            body["folder_token"] = folder_token
        resp = await client.post(f"{_DOCX_BASE}/documents", json=body, headers=headers)
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuError(data.get("code", -1), data.get("msg", "创建文档失败"))
        document_id = data["data"]["document"]["document_id"]
        logger.info("feishu_doc_created", document_id=document_id, title=title[:40])

        # 2. 拿根 block_id
        resp = await client.get(f"{_DOCX_BASE}/documents/{document_id}", headers=headers)
        gdata = resp.json()
        root_block_id = (gdata.get("data", {}).get("document", {}) or {}).get("block_id") or document_id

        # 3. 追加内容块(分批,飞书单批最多 50 块)
        blocks = _markdown_to_blocks(markdown)
        batch_size = 20
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i + batch_size]
            resp = await client.post(
                f"{_DOCX_BASE}/documents/{document_id}/blocks/{root_block_id}/children",
                json={"children": batch, "index": -1},
                headers=headers,
            )
            rdata = resp.json()
            if rdata.get("code") != 0:
                logger.warning(
                    "feishu_doc_append_partial_fail",
                    document_id=document_id, code=rdata.get("code"), msg=rdata.get("msg", "")[:120],
                )
                # 部分失败不阻断,文档已经创建了

    url = f"https://feishu.cn/docx/{document_id}"
    logger.info("feishu_doc_populated", url=url, blocks=len(blocks))
    return document_id, url


# ── 多维表批量写入需求 ──────────────────────────────────────────────

async def batch_create_bitable_records(
    app_id: str,
    app_secret: str,
    app_token: str,
    table_id: str,
    records: list[dict],
) -> str:
    """批量写入飞书多维表。返回多维表 URL。

    records 形如 [{"req_id": "REQ-001", "module": "...", "priority": "P1", ...}, ...]
    用户需要在飞书提前创建好表 + 字段名跟 records 字典 key 对齐。
    """
    if not records:
        return f"https://feishu.cn/base/{app_token}"

    token = await get_tenant_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 转成飞书要求的 records 格式:[{fields: {...}}, ...]
    payload_records = [{"fields": r} for r in records]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # 飞书 batch_create 单次最多 1000 条
        batch_size = 500
        for i in range(0, len(payload_records), batch_size):
            batch = payload_records[i:i + batch_size]
            resp = await client.post(
                f"{_BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records/batch_create",
                json={"records": batch},
                headers=headers,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise FeishuError(data.get("code", -1), data.get("msg", "写入多维表失败"))

    url = f"https://feishu.cn/base/{app_token}?table={table_id}"
    logger.info("feishu_bitable_written", url=url, rows=len(records))
    return url
