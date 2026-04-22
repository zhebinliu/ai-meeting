import os
import asyncio
import json
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv
import aiohttp

# Load environment
load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BASE_URL = "https://open.feishu.cn/open-apis/docx/v1"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_feishu")

async def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}) as resp:
            data = await resp.json()
            return data.get("tenant_access_token")

async def test_append_blocks():
    token = await get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    
    # 1. Create Doc
    create_url = f"{BASE_URL}/documents"
    async with aiohttp.ClientSession() as session:
        async with session.post(create_url, headers=headers, json={"title": "测试对齐协议-v1"}) as resp:
            doc_data = (await resp.json()).get("data", {}).get("document", {})
            doc_id = doc_data.get("document_id")
            root_id = doc_data.get("block_id") # Getting root block ID directly from create response
            
    print(f"Doc created: {doc_id}, Root Block: {root_id}")
    
    # 2. Prepare Blocks (Strict Alignment)
    blocks = [
        {
            "block_type": 3, # Heading 1
            "heading1": {
                "elements": [{"text_run": {"content": "1. 讨论要点", "text_element_style": {}}}],
                "style": {}
            }
        },
        {
            "block_type": 2, # Text
            "text": {
                "elements": [{"text_run": {"content": "这是一段普通的正文文本。", "text_element_style": {}}}],
                "style": {}
            }
        },
        {
            "block_type": 12, # Bullet
            "bullet": {
                "elements": [{"text_run": {"content": "列表项第 1 条", "text_element_style": {}}}],
                "style": {}
            }
        },
        {
            "block_type": 17, # Todo
            "todo": {
                "elements": [{"text_run": {"content": "这是一条待办事项事项", "text_element_style": {}}}],
                "style": {}
            }
        }
    ]
    
    # 3. Test One by One
    root_id = doc_id
    append_base_url = f"{BASE_URL}/documents/{doc_id}/blocks/{root_id}/children"
    
    for i, block in enumerate(blocks):
        print(f"Testing Block {i+1} (Type {block['block_type']})...")
        async with aiohttp.ClientSession() as session:
            async with session.post(append_base_url, headers=headers, json={"children": [block], "index": -1}) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("code") == 0:
                    print(f"  - Block {i+1} SUCCESS")
                else:
                    print(f"  - Block {i+1} FAILED: {result}")

if __name__ == "__main__":
    asyncio.run(test_append_blocks())
