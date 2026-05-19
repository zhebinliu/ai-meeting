# ai-meeting

会议纪要 / 需求抽取 / 干系人识别 AI Pipeline —— 作为 git submodule 嵌入 [knowledge-base](https://github.com/zhebinliu/knowledge-base) (`kb-system`) 运行。

## 仓库结构

本分支(`from-kb-system`)采用 **overlay 布局**:目录结构跟它在 kb-system 里的相对路径完全一致,这样作为 submodule 挂到 `kb-system/meeting/` 之后,Docker 构建时通过二次 `COPY meeting/backend/ /app/` 让代码落到原位,Python / TypeScript 的 import 路径 **完全不用改**。

```
backend/
  api/meeting.py            → /app/api/meeting.py
  models/meeting.py         → /app/models/meeting.py
  prompts/meeting.py        → /app/prompts/meeting.py
  tasks/meeting_tasks.py    → /app/tasks/meeting_tasks.py
  services/meeting/         → /app/services/meeting/
    {asr,audio_utils,docx_export,feishu,kb_sync,pipeline,storage}.py
    templates/minutes_template.docx

frontend/src/
  pages/console/                 → frontend/src/pages/console/    (旧 UI)
    ConsoleMeeting{,Detail,New}.tsx
  redesign/console/              → frontend/src/redesign/console/ (新 UI)
    ConsoleMeeting{,Detail,New}.tsx
```

## 运行时依赖(由宿主仓 kb-system 提供)

本仓 **不能独立运行**,代码依赖 kb-system 的:

- **DB / 模型**:`models.get_session`、`models.project.Project`、`models.user.User`(meetings 表通过 `project_id` FK 到 projects 表)
- **认证**:`services.auth.get_current_user`
- **权限**:`services.project_acl.{get_user_project_access, assert_project_access}`
- **Celery**:`tasks` 包(meeting_tasks 在 `tasks/__init__.py` 里被 eager import,见 [kb-system LEARNING.md § 6](https://github.com/zhebinliu/knowledge-base/blob/main/LEARNING.md))
- **环境变量**:OpenAI / Anthropic key、阿里云 ASR、飞书 app credentials、MinIO,详见 kb-system `.env`

## 在 kb-system 里的集成方式

kb-system 仓的:
- `backend/Dockerfile` build context 改成仓库根,先 `COPY backend/ /app/` 再 `COPY meeting/backend/ /app/`
- `frontend/Dockerfile` 同理
- `backend/main.py`、`backend/tasks/__init__.py`、`frontend/src/App.tsx` 的 import 不变 —— 因为 overlay 之后路径和原来一样

## 历史背景

- main 分支:2026-04-28 之前的独立 FastAPI 服务版本(已废弃,留作备查)
- from-kb-system 分支:2026-05-19 从 kb-system 抽出,代码与生产同步
