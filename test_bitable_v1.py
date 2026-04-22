import os
import asyncio
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv
import aiohttp

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_bitable")

async def get_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}) as resp:
            return (await resp.json()).get("tenant_access_token")

async def test_bitable():
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # 1. Create App (Bitable)
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/apps", headers=headers, json={"name": "测试多维表格-v1"}) as resp:
            app_data = await resp.json()
            app_token = app_data.get("data", {}).get("app", {}).get("app_token")
            
    if not app_token:
        print(f"Failed to create app: {app_data}")
        return

    print(f"App created: {app_token}")

    # 2. Test Create Table with specific fields
    # Hypothesis: Field type 1001 (Created Time) might fail during table creation
    fields = [
        {"field_name": "需求编号", "type": 1},
        {"field_name": "所属模块", "type": 3, "property": {"options": []}},
        {"field_name": "需求描述", "type": 1},
        {
            "field_name": "优先级", 
            "type": 3, 
            "property": {
                "options": [
                    {"name": "P0", "color": 0},
                    {"name": "P1", "color": 1},
                    {"name": "P2", "color": 2},
                    {"name": "P3", "color": 3},
                ]
            }
        },
        {"field_name": "需求来源", "type": 1},
        {"field_name": "提出人", "type": 1},
        {
            "field_name": "状态",
            "type": 3,
            "property": {
                "options": [
                    {"name": "待确认", "color": 4},
                    {"name": "已确认", "color": 1},
                    {"name": "已排期", "color": 2},
                    {"name": "已完成", "color": 7},
                ]
            }
        },
        {"field_name": "创建时间", "type": 1001},
    ]
    
    table_body = {
        "table": {
            "name": "需求清单",
            "fields": fields
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/apps/{app_token}/tables", headers=headers, json=table_body) as resp:
            data = await resp.json()
            if data.get("code") == 0:
                print("SUCCESS: Table created!")
            else:
                print(f"FAILED: {data}")

if __name__ == "__main__":
    asyncio.run(test_bitable())
