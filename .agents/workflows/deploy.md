---
description: 部署代码到生产服务器
---

# Meeting-AI 生产部署工作流

## 服务器信息
- **地址**: `34.136.165.103`
- **用户**: `liu`
- **SSH Key**: `~/Downloads/gcp_key`
- **项目目录**: `/home/liu/meeting-ai`
- **服务名**: `meeting-ai`（systemd）
- **数据库**: `/home/liu/meeting-ai/meeting_ai.db`（绝对路径）

## 项目结构（本地）
```
meeting-ai/
├── backend/            # Python 后端（FastAPI）
│   ├── main.py         # 入口，以 python -m uvicorn backend.main:app 启动
│   ├── config.py       # 配置，UPLOAD_DIR 使用绝对路径
│   ├── database.py
│   ├── models/
│   ├── routes/
│   └── services/       # ← 所有服务（ai/asr/feishu）都在这里
│       ├── ai/
│       ├── asr/
│       └── feishu/
├── frontend/           # 静态前端
├── .rsyncignore        # rsync 排除规则
└── deploy.sh           # 一键部署脚本
```

> [!IMPORTANT]
> `services/` 目录在 `backend/` 内部，不在根目录。所有导入必须使用 `from backend.services...` 前缀。

## 标准部署流程

// turbo-all

1. 赋予脚本执行权限（首次部署时执行一次）
```bash
chmod +x deploy.sh
```

2. 执行一键部署（同步代码 + 数据库迁移 + 重启 + 验证）
```bash
./deploy.sh
```

## 可选参数

- `./deploy.sh --no-migrate`：跳过数据库迁移（仅同步代码和重启）
- `./deploy.sh --no-restart`：仅同步代码，不重启服务

## 手动排障命令

查看实时日志：
```bash
ssh -i ~/Downloads/gcp_key liu@34.136.165.103 "sudo journalctl -u meeting-ai -f"
```

查看服务状态：
```bash
ssh -i ~/Downloads/gcp_key liu@34.136.165.103 "sudo systemctl status meeting-ai"
```

检查数据库字段：
```bash
ssh -i ~/Downloads/gcp_key liu@34.136.165.103 "python3 -c \"import sqlite3; c=sqlite3.connect('/home/liu/meeting-ai/meeting_ai.db').cursor(); c.execute('PRAGMA table_info(meetings)'); print([r[1] for r in c.fetchall()])\""
```

查看服务器目录结构：
```bash
ssh -i ~/Downloads/gcp_key liu@34.136.165.103 "ls -R /home/liu/meeting-ai/backend/services/"
```

## 常见问题

| 错误 | 原因 | 解决 |
|------|------|------|
| `502 Bad Gateway` | 服务崩溃 | 查看日志，找 `ModuleNotFoundError` 或 `ImportError` |
| `500 Internal Server Error` | 数据库字段缺失 | 重新执行 `./deploy.sh`（含迁移步骤） |
| `ModuleNotFoundError: backend.services.xxx` | services 目录未同步 | 检查 `backend/services/ai/` 目录是否存在于服务器 |
| `no such column: meetings.xxx` | 数据库 schema 过旧 | 执行 `./deploy.sh` 或单独运行迁移步骤 |
