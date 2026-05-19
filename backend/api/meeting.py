"""会议纪要 API — Block A CRUD 基础(2026-05-11)。

源自 meeting-ai 项目 routes/meeting.py 的迁移。Block A 范围:
  - 会议 CRUD(创建空白 / 文本创建 / 列表 / 详情 / 更新 / 删除)
  - 关联 KB 项目(替代原 kb_project_id 字符串)
  - 干系人图谱直写(占位,后续 Block B 接入自动提取)
  - 列出会议的需求(只读,Block B 接入自动提取)

后续 Block:
  - B(AI pipeline + Celery):POST /{id}/process + /actions/*
  - C(文件上传 + ASR):POST /{id}/upload
  - D(WebSocket):/ws/recording/{id}
  - E(KB / 飞书):/sync-kb / /export-feishu / /sync-requirements
"""
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from models.meeting import Meeting, Requirement
from models.project import Project
from models.user import User
from services.auth import get_current_user

logger = structlog.get_logger()
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    title: str = Field(default="未命名会议", max_length=256)
    project_id: Optional[str] = None


class MeetingFromText(BaseModel):
    title: str = Field(default="未命名会议", max_length=256)
    transcript: str = Field(min_length=1, max_length=200000)
    project_id: Optional[str] = None


class MeetingPatch(BaseModel):
    title: Optional[str] = None
    end_time: Optional[datetime] = None
    raw_transcript: Optional[str] = None
    polished_transcript: Optional[str] = None
    meeting_minutes: Optional[dict] = None
    status: Optional[str] = None
    total_chunks: Optional[int] = None
    done_chunks: Optional[int] = None


class ProjectLink(BaseModel):
    project_id: Optional[str] = None  # null 表示解除关联


class StakeholderMapIn(BaseModel):
    stakeholder_map: dict  # {stakeholders: [...], relations: [...], version?: int}


# ── DTO ──────────────────────────────────────────────────────────────────────

def _meeting_dto(m: Meeting, project_name: Optional[str] = None) -> dict:
    return {
        "id": m.id,
        "title": m.title,
        "owner_id": m.owner_id,
        "project_id": m.project_id,
        "project_name": project_name,
        "start_time": m.start_time,
        "end_time": m.end_time,
        "created_at": m.created_at,
        "raw_transcript": m.raw_transcript or "",
        "polished_transcript": m.polished_transcript or "",
        "meeting_minutes": m.meeting_minutes,
        "status": m.status,
        "asr_engine": m.asr_engine,
        "total_chunks": m.total_chunks,
        "done_chunks": m.done_chunks,
        "audio_object_key": m.audio_object_key,
        "feishu_url": m.feishu_url,
        "bitable_app_token": m.bitable_app_token,
        "kb_doc_id": m.kb_doc_id,
        "kb_url": m.kb_url,
        "kb_synced_at": m.kb_synced_at,
        "stakeholder_map": m.stakeholder_map,
        "stakeholder_kb_doc_id": m.stakeholder_kb_doc_id,
        "stakeholder_kb_url": m.stakeholder_kb_url,
        "stakeholder_kb_synced_at": m.stakeholder_kb_synced_at,
    }


def _requirement_dto(r: Requirement) -> dict:
    return {
        "id": r.id,
        "meeting_id": r.meeting_id,
        "req_id": r.req_id,
        "module": r.module,
        "description": r.description,
        "priority": r.priority,
        "source": r.source,
        "speaker": r.speaker,
        "status": r.status,
        "created_at": r.created_at,
    }


# ── 权限辅助 ───────────────────────────────────────────────────────────────

async def _load_meeting_owned(
    meeting_id: int, session: AsyncSession, user: User
) -> Meeting:
    """加载会议并校验访问权限。
    - admin 看全部
    - 会议 owner 看自己的
    - 2026-05-12 加:会议绑定了 project 时,该 project 的协作者也可访问
      (顾问、运营常常需要看 / 编辑别人主持的会议)
    """
    m = await session.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "会议不存在")
    if user.is_admin or m.owner_id == user.id:
        return m
    # 项目协作者权限
    if m.project_id:
        from services.project_acl import get_user_project_access
        access = await get_user_project_access(user, m.project_id)
        if access is not None:  # owner / read_write / read 都允许进会议详情
            return m
    raise HTTPException(403, "无权访问该会议")


async def _validate_project_link(
    session: AsyncSession, project_id: Optional[str], user: User
) -> Optional[str]:
    """校验项目存在且当前用户有 write 权限。返回 project_id(或 None)。

    2026-05-12 修复:此前只校项目存在,任意登录用户可把 meeting 绑到他人项目然后
    跑 AI pipeline 读他人项目数据并写回。现在调用 project_acl 做权限隔离。
    """
    if not project_id:
        return None
    p = await session.get(Project, project_id)
    if not p:
        raise HTTPException(400, "关联的项目不存在")
    from services.project_acl import assert_project_access
    await assert_project_access(user, project_id, "write")
    return project_id


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("")
async def create_meeting(
    body: MeetingCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """创建空白会议(占位,后续配合 WS 录音或 upload)。"""
    project_id = await _validate_project_link(session, body.project_id, user)
    m = Meeting(
        title=body.title,
        owner_id=user.id,
        project_id=project_id,
        status="recording",
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    logger.info("meeting_created", meeting_id=m.id, user=user.username)
    return _meeting_dto(m)


@router.post("/from-text")
async def create_from_text(
    body: MeetingFromText,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """从文本直接创建会议,跳过 ASR。raw_transcript 立即填好。

    Block B 接通后,这里会同步触发 process Celery task;当前仅落库返回。
    """
    project_id = await _validate_project_link(session, body.project_id, user)
    m = Meeting(
        title=body.title,
        owner_id=user.id,
        project_id=project_id,
        raw_transcript=body.transcript,
        status="processing",  # 后续 Block B 完成后真正变 processing → completed
        asr_engine="text",
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    logger.info("meeting_from_text", meeting_id=m.id, length=len(body.transcript))
    # 自动触发 AI pipeline(异步)
    from tasks.meeting_tasks import process_meeting as _task
    _task.delay(m.id)
    return _meeting_dto(m)


@router.get("")
async def list_meetings(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """列出当前用户的会议(admin 看全部)。按 created_at 倒序。"""
    stmt = select(Meeting).order_by(Meeting.created_at.desc())
    if not user.is_admin:
        stmt = stmt.where(Meeting.owner_id == user.id)
    rows = (await session.scalars(stmt)).all()

    # 一次性查所有相关 project 的名字
    project_ids = {m.project_id for m in rows if m.project_id}
    project_names: dict[str, str] = {}
    if project_ids:
        projects = (await session.scalars(
            select(Project).where(Project.id.in_(project_ids))
        )).all()
        project_names = {p.id: p.name for p in projects}

    return [_meeting_dto(m, project_names.get(m.project_id)) for m in rows]


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """获取会议详情(含 requirements)。"""
    m = await _load_meeting_owned(meeting_id, session, user)

    # join project name
    project_name = None
    if m.project_id:
        p = await session.get(Project, m.project_id)
        project_name = p.name if p else None

    # 关联需求
    reqs = (await session.scalars(
        select(Requirement).where(Requirement.meeting_id == m.id).order_by(Requirement.id)
    )).all()

    dto = _meeting_dto(m, project_name)
    dto["requirements"] = [_requirement_dto(r) for r in reqs]
    return dto


@router.patch("/{meeting_id}")
async def patch_meeting(
    meeting_id: int,
    body: MeetingPatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """部分更新会议。"""
    m = await _load_meeting_owned(meeting_id, session, user)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(m, key, value)
    await session.commit()
    await session.refresh(m)
    return _meeting_dto(m)


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """删除会议(级联删除 requirements,由 FK ondelete=CASCADE 处理)。"""
    m = await _load_meeting_owned(meeting_id, session, user)
    audio_key = m.audio_object_key
    # 显式删 requirements,避免 DB 未强制 FK 级联时遗漏
    await session.execute(sql_delete(Requirement).where(Requirement.meeting_id == m.id))
    await session.delete(m)
    await session.commit()
    # 同步删 MinIO 音频(失败不阻塞)
    if audio_key:
        try:
            from services.meeting.storage import delete_audio
            delete_audio(audio_key)
        except Exception as e:
            logger.warning("meeting_audio_cleanup_failed", key=audio_key, error=str(e)[:120])
    logger.info("meeting_deleted", meeting_id=meeting_id, user=user.username)
    return {"status": "ok"}


@router.get("/{meeting_id}/requirements")
async def list_meeting_requirements(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """列出某会议的所有需求。"""
    m = await _load_meeting_owned(meeting_id, session, user)
    reqs = (await session.scalars(
        select(Requirement).where(Requirement.meeting_id == m.id).order_by(Requirement.id)
    )).all()
    return [_requirement_dto(r) for r in reqs]


@router.put("/{meeting_id}/project")
async def link_project(
    meeting_id: int,
    body: ProjectLink,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """关联或解除 KB 项目。"""
    m = await _load_meeting_owned(meeting_id, session, user)
    m.project_id = await _validate_project_link(session, body.project_id, user)
    await session.commit()
    await session.refresh(m)
    project_name = None
    if m.project_id:
        p = await session.get(Project, m.project_id)
        project_name = p.name if p else None
    return _meeting_dto(m, project_name)


@router.put("/{meeting_id}/stakeholder-map")
async def put_stakeholder_map(
    meeting_id: int,
    body: StakeholderMapIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """直接覆盖 stakeholder_map(用于前端手动编辑后保存)。"""
    m = await _load_meeting_owned(meeting_id, session, user)
    m.stakeholder_map = body.stakeholder_map
    await session.commit()
    await session.refresh(m)
    return _meeting_dto(m)


# 2026-05-12:单条 requirement 编辑 + 改名同步

class RequirementPatch(BaseModel):
    """单条需求 PATCH:仅传需要改的字段。"""
    module: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None  # P0/P1/P2/P3
    source: Optional[str] = None
    speaker: Optional[str] = None
    status: Optional[str] = None


@router.patch("/{meeting_id}/requirements/{req_id}")
async def patch_requirement(
    meeting_id: int,
    req_id: int,
    body: RequirementPatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """更新单条需求字段。"""
    await _load_meeting_owned(meeting_id, session, user)
    r = await session.get(Requirement, req_id)
    if not r or r.meeting_id != meeting_id:
        raise HTTPException(404, "需求不存在或不属于该会议")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    await session.commit()
    await session.refresh(r)
    return _requirement_dto(r)


class RequirementCreate(BaseModel):
    """新增需求(2026-05-12 加)。"""
    module: str = ""
    description: str = ""
    priority: str = "P2"
    source: Optional[str] = None
    speaker: Optional[str] = None
    status: str = "待确认"


@router.post("/{meeting_id}/requirements", status_code=201)
async def create_requirement(
    meeting_id: int,
    body: RequirementCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """手动新增一条需求。"""
    await _load_meeting_owned(meeting_id, session, user)
    # 生成 req_id:取当前 max + 1
    existing = (await session.scalars(
        select(Requirement).where(Requirement.meeting_id == meeting_id)
    )).all()
    next_idx = len(existing) + 1
    r = Requirement(
        meeting_id=meeting_id,
        req_id=f"REQ-{next_idx:03d}",
        module=body.module,
        description=body.description,
        priority=body.priority,
        source=body.source,
        speaker=body.speaker,
        status=body.status,
    )
    session.add(r)
    await session.commit()
    await session.refresh(r)
    return _requirement_dto(r)


@router.delete("/{meeting_id}/requirements/{req_id}", status_code=204)
async def delete_requirement(
    meeting_id: int,
    req_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """删除单条需求。"""
    await _load_meeting_owned(meeting_id, session, user)
    r = await session.get(Requirement, req_id)
    if not r or r.meeting_id != meeting_id:
        raise HTTPException(404, "需求不存在或不属于该会议")
    await session.delete(r)
    await session.commit()
    return None


class StakeholderRenamePayload(BaseModel):
    """改名同步:把 minutes / requirements 里 old_name(及别名)的引用换成 new_name。"""
    old_name: str
    new_name: str
    old_aliases: list[str] = []  # 旧别名也一起替换(可选)


@router.post("/{meeting_id}/stakeholders/rename")
async def rename_stakeholder_references(
    meeting_id: int,
    body: StakeholderRenamePayload,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """把改了名的干系人引用同步到 meeting_minutes 各字段 + requirements.speaker。

    匹配规则:对 old_name + 所有 old_aliases 做精确字符串替换(全字匹配)。
    "全字"指:仅当目标字段值与匹配项完全相等、或被「、」「,」「;」「 」分隔
    时才替换,避免把"张总"误改成"新名总"。
    """
    m = await _load_meeting_owned(meeting_id, session, user)
    candidates = {body.old_name, *body.old_aliases}
    candidates.discard("")
    if not candidates or not body.new_name.strip():
        return {"replaced_in_minutes": 0, "replaced_in_requirements": 0}

    def _replace_exact(text: str | None) -> tuple[str | None, int]:
        if not text:
            return text, 0
        replaced = 0
        for cand in candidates:
            # 全字匹配:cand 前后必须是分隔符或字符串边界
            import re
            pattern = r"(?<![\w一-鿿])" + re.escape(cand) + r"(?![\w一-鿿])"
            new_text, n = re.subn(pattern, body.new_name, text)
            text = new_text
            replaced += n
        return text, replaced

    # 1) meeting_minutes 各字段
    mm = dict(m.meeting_minutes or {})
    minutes_replaced = 0

    # a. 元信息单字段(string)
    for key in ("meeting_host", "meeting_recorder", "organizer", "summary"):
        v = mm.get(key)
        if isinstance(v, str):
            new_v, n = _replace_exact(v)
            if n:
                mm[key] = new_v
                minutes_replaced += n

    # b. attendees 数组
    if isinstance(mm.get("attendees"), list):
        new_attendees = []
        for s in mm["attendees"]:
            if isinstance(s, str):
                new_s, n = _replace_exact(s)
                minutes_replaced += n
                new_attendees.append(new_s)
            else:
                new_attendees.append(s)
        mm["attendees"] = new_attendees

    # c. key_points[] 的 topic / content(自由文本里可能提及名字)
    if isinstance(mm.get("key_points"), list):
        for item in mm["key_points"]:
            if isinstance(item, dict):
                for k in ("topic", "content"):
                    if isinstance(item.get(k), str):
                        new_v, n = _replace_exact(item[k])
                        if n:
                            item[k] = new_v
                            minutes_replaced += n

    # d. decisions[] / action_items[] / unresolved[] 所有文本字段 + owner
    text_fields = {
        "decisions": ("content", "owner"),
        "action_items": ("task", "owner", "remark", "deadline"),
        "unresolved": ("issue", "owner", "reason", "remark"),
    }
    for arr_key, fields in text_fields.items():
        arr = mm.get(arr_key)
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            for f in fields:
                if isinstance(item.get(f), str):
                    new_v, n = _replace_exact(item[f])
                    if n:
                        item[f] = new_v
                        minutes_replaced += n

    if minutes_replaced:
        m.meeting_minutes = mm

    # 2) requirements:speaker + description + source + module
    reqs = (await session.scalars(
        select(Requirement).where(Requirement.meeting_id == meeting_id)
    )).all()
    req_replaced = 0
    for r in reqs:
        for attr in ("speaker", "description", "source", "module"):
            v = getattr(r, attr, None)
            if isinstance(v, str):
                new_v, n = _replace_exact(v)
                if n:
                    setattr(r, attr, new_v)
                    req_replaced += n

    await session.commit()
    logger.info("stakeholder_renamed",
                meeting_id=meeting_id,
                old=body.old_name, new=body.new_name,
                minutes=minutes_replaced, requirements=req_replaced)
    return {"replaced_in_minutes": minutes_replaced, "replaced_in_requirements": req_replaced}


# ── 音频上传 + ASR(Block C) ───────────────────────────────────────────

@router.post("/upload", status_code=202)
async def upload_audio_meeting(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """上传音频文件创建会议。后台异步:ASR → AI pipeline。

    成功返回 meeting_id,前端轮询 GET /{id} 拿状态。
    """
    from services.meeting.storage import upload_audio
    from tasks.meeting_tasks import transcribe_meeting as _task

    # 简单大小限制(50 MB),防大文件打爆 MinIO
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传文件为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "音频文件超过 50 MB 限制")

    pid = await _validate_project_link(session, project_id, user)
    derived_title = title or (file.filename or "录音会议")
    m = Meeting(
        title=derived_title,
        owner_id=user.id,
        project_id=pid,
        status="recording",
        asr_engine="xiaomi",
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)

    # 上传到 MinIO
    try:
        object_key = upload_audio(m.id, file.filename or "audio.bin", content, content_type=file.content_type or "audio/mpeg")
    except Exception as e:
        logger.exception("meeting_upload_minio_failed", meeting_id=m.id, error=str(e)[:200])
        m.status = "failed"
        await session.commit()
        raise HTTPException(500, "上传到对象存储失败")

    m.audio_object_key = object_key
    m.status = "processing"  # 排队等 ASR
    await session.commit()

    # 触发 ASR Celery task
    _task.delay(m.id)
    logger.info("meeting_upload_dispatched", meeting_id=m.id, bytes=len(content), key=object_key)
    return {"meeting_id": m.id, "status": "accepted", "object_key": object_key}


# ── AI Pipeline 触发(Block B) ──────────────────────────────────────────

@router.post("/{meeting_id}/process", status_code=202)
async def process_meeting(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """触发 AI pipeline(异步,通过 Celery)。立即返回 202。

    Pipeline:polish → minutes/requirements(并行)→ stakeholders。
    完成后 status 切到 completed,前端轮询 GET /{id} 取结果。
    """
    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.raw_transcript or not m.raw_transcript.strip():
        raise HTTPException(400, "无 raw_transcript,无法触发 pipeline")
    m.status = "processing"
    await session.commit()

    from tasks.meeting_tasks import process_meeting as _task
    _task.delay(meeting_id)
    logger.info("meeting_process_dispatched", meeting_id=meeting_id, user=user.username)
    return {"status": "accepted", "meeting_id": meeting_id}


# ── 单点 actions(同步,小数据量) ──────────────────────────────────────

@router.post("/{meeting_id}/actions/polish")
async def action_polish(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """仅润色 raw_transcript,写回 polished_transcript。"""
    from services.meeting import polish_transcript
    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.raw_transcript:
        raise HTTPException(400, "无 raw_transcript")
    polished = await polish_transcript(m.raw_transcript)
    m.polished_transcript = polished
    await session.commit()
    return {"polished_transcript": polished}


@router.post("/{meeting_id}/actions/summarize")
async def action_summarize(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """仅生成纪要。优先用 polished_transcript,fallback raw。"""
    from services.meeting import generate_minutes
    m = await _load_meeting_owned(meeting_id, session, user)
    text = m.polished_transcript or m.raw_transcript
    if not text:
        raise HTTPException(400, "无可用 transcript")
    minutes = await generate_minutes(text, meeting_title=m.title or "")
    m.meeting_minutes = minutes
    await session.commit()
    return {"meeting_minutes": minutes}


@router.get("/{meeting_id}/export-docx")
async def export_meeting_docx(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """按「纷享销客 CRM 实施纪要模板」生成 docx。2026-05-12。

    返回 application/vnd.openxmlformats-officedocument.wordprocessingml.document
    流,前端 a[download] 即可下载。
    """
    from fastapi.responses import Response
    from urllib.parse import quote
    from services.meeting.docx_export import render_minutes_docx

    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.meeting_minutes:
        raise HTTPException(400, "纪要尚未生成,无法导出")

    # 兜底字段:模板缺会议时间时尝试用 meeting.start_time
    fallback_time = ""
    if m.start_time:
        fallback_time = m.start_time.strftime("%Y年%m月%d日 %H:%M")
        if m.end_time:
            fallback_time += "~" + m.end_time.strftime("%H:%M")

    try:
        docx_bytes = render_minutes_docx(
            meeting_title=m.title,
            minutes=m.meeting_minutes,
            fallback_time=fallback_time,
        )
    except Exception as e:
        logger.exception("export_minutes_docx_failed", meeting_id=meeting_id, error=str(e)[:200])
        raise HTTPException(500, f"生成 docx 失败:{e}")

    safe_name = quote(f"{m.title or '会议纪要'}.docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.post("/{meeting_id}/actions/extract_requirements")
async def action_extract_requirements(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """仅提取需求(覆盖式重建)。"""
    from services.meeting import extract_requirements
    m = await _load_meeting_owned(meeting_id, session, user)
    text = m.polished_transcript or m.raw_transcript
    if not text:
        raise HTTPException(400, "无可用 transcript")
    raw_reqs = await extract_requirements(text)
    # 覆盖式重建
    await session.execute(sql_delete(Requirement).where(Requirement.meeting_id == meeting_id))
    out: list[dict] = []
    for r in raw_reqs:
        rec = Requirement(
            meeting_id=meeting_id,
            req_id=r.get("req_id") or "REQ-001",
            module=r.get("module") or "",
            description=r.get("description") or "",
            priority=r.get("priority") or "P2",
            source=r.get("source"),
            speaker=r.get("speaker"),
            status=r.get("status") or "待确认",
        )
        session.add(rec)
        out.append(r)
    await session.commit()
    return {"requirements": out}


@router.post("/{meeting_id}/actions/extract_stakeholders")
async def action_extract_stakeholders(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """仅提取干系人图谱。"""
    from services.meeting import extract_stakeholders
    m = await _load_meeting_owned(meeting_id, session, user)
    text = m.polished_transcript or m.raw_transcript
    if not text:
        raise HTTPException(400, "无可用 transcript")
    smap = await extract_stakeholders(
        meeting_id=m.id,
        meeting_title=m.title or "",
        transcript=text,
        minutes=m.meeting_minutes if isinstance(m.meeting_minutes, dict) else None,
    )
    m.stakeholder_map = smap
    await session.commit()
    return {"stakeholder_map": smap}


# ── KB 同步(Block E.1) ────────────────────────────────────────────────

@router.post("/{meeting_id}/sync-kb")
async def sync_to_kb(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """把会议纪要同步到 kb-system 知识库(写入 Document 表)。

    要求会议已经处理完成(meeting_minutes 非空)。每次调用都创建一份**新**的
    Document,旧的不动 — 保留历史版本。
    """
    from services.meeting.kb_sync import sync_minutes_to_kb
    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.meeting_minutes:
        raise HTTPException(400, "会议纪要尚未生成,请先触发 process")
    doc_id, url = await sync_minutes_to_kb(session, m, uploader_id=user.id)
    await session.commit()
    return {"status": "ok", "kb_doc_id": doc_id, "kb_url": url}


@router.post("/{meeting_id}/sync-stakeholder-map-kb")
async def sync_stakeholders_to_kb_endpoint(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """把干系人图谱同步到 kb-system 知识库。"""
    from services.meeting.kb_sync import sync_stakeholders_to_kb
    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.stakeholder_map:
        raise HTTPException(400, "干系人图谱尚未生成,请先触发 extract_stakeholders")
    doc_id, url = await sync_stakeholders_to_kb(session, m, uploader_id=user.id)
    await session.commit()
    return {"status": "ok", "kb_doc_id": doc_id, "kb_url": url}


# ── 飞书凭证管理(Block E.4) ──────────────────────────────────────────

class FeishuCredentialsIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1, max_length=255)


@router.get("/feishu-credentials")
async def get_feishu_credentials(
    user: User = Depends(get_current_user),
):
    """读取当前用户的飞书配置状态(不返 secret)。"""
    return {
        "configured": bool(user.feishu_app_id and user.feishu_app_secret),
        "app_id": user.feishu_app_id,
    }


@router.put("/feishu-credentials")
async def put_feishu_credentials(
    body: FeishuCredentialsIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """配置/更新当前用户的飞书凭证。"""
    user.feishu_app_id = body.app_id.strip()
    user.feishu_app_secret = body.app_secret.strip()
    session.add(user)
    await session.commit()
    logger.info("feishu_creds_updated", user=user.username)
    return {"status": "ok", "configured": True, "app_id": user.feishu_app_id}


@router.delete("/feishu-credentials")
async def delete_feishu_credentials(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """清除当前用户的飞书凭证。"""
    user.feishu_app_id = None
    user.feishu_app_secret = None
    session.add(user)
    await session.commit()
    return {"status": "ok", "configured": False}


# ── 飞书会议导出 + 多维表同步(Block E.5) ─────────────────────────────

class BitableSyncIn(BaseModel):
    bitable_app_token: str = Field(min_length=1, max_length=128)
    table_id: str = Field(min_length=1, max_length=64)


def _require_feishu(user: User):
    """没配飞书直接抛 412,前端引导去 Settings 配置。"""
    from services.meeting.feishu import get_user_feishu_credentials
    creds = get_user_feishu_credentials(user)
    if not creds:
        raise HTTPException(412, "请先在「个人设置」中配置飞书集成")
    return creds


@router.post("/{meeting_id}/export-feishu")
async def export_to_feishu(
    meeting_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """把会议纪要导出为飞书 docx 文档。"""
    from services.meeting.feishu import create_doc_with_markdown, FeishuError
    from services.meeting.kb_sync import render_minutes_markdown

    app_id, app_secret = _require_feishu(user)
    m = await _load_meeting_owned(meeting_id, session, user)
    if not m.meeting_minutes:
        raise HTTPException(400, "会议纪要尚未生成,请先触发 process")

    markdown = render_minutes_markdown(m)
    title = f"{m.title or '未命名会议'} - 会议纪要"
    try:
        doc_id, url = await create_doc_with_markdown(app_id, app_secret, title, markdown)
    except FeishuError as e:
        raise HTTPException(502, f"飞书 API 失败:{e.message}")

    m.feishu_url = url
    await session.commit()
    return {"status": "ok", "url": url, "document_id": doc_id}


@router.post("/{meeting_id}/sync-requirements")
async def sync_requirements_to_bitable(
    meeting_id: int,
    body: BitableSyncIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """把会议提取出的需求清单批量写入飞书多维表。

    用户需要在飞书侧预先创建好多维表 + 表,字段名要跟 records 字典 key 对齐:
    req_id / module / description / priority / source / speaker / status
    """
    from services.meeting.feishu import batch_create_bitable_records, FeishuError

    app_id, app_secret = _require_feishu(user)
    m = await _load_meeting_owned(meeting_id, session, user)
    reqs = (await session.scalars(
        select(Requirement).where(Requirement.meeting_id == m.id).order_by(Requirement.id)
    )).all()
    if not reqs:
        raise HTTPException(400, "该会议没有需求记录")

    records = [
        {
            "req_id": r.req_id,
            "module": r.module,
            "description": r.description,
            "priority": r.priority,
            "source": r.source or "",
            "speaker": r.speaker or "",
            "status": r.status,
        }
        for r in reqs
    ]
    try:
        url = await batch_create_bitable_records(
            app_id, app_secret, body.bitable_app_token, body.table_id, records
        )
    except FeishuError as e:
        raise HTTPException(502, f"飞书多维表 API 失败:{e.message}")

    m.bitable_app_token = body.bitable_app_token
    await session.commit()
    return {"status": "ok", "url": url, "rows": len(records)}


# 兼容旧 ingest webhook(避免老调用方报 404)
@router.post("/ingest")
async def ingest_meeting():
    """Webhook for meeting transcript ingestion — deprecated,使用 POST /from-text 代替。"""
    raise HTTPException(410, "已迁移:请使用 POST /api/meeting/from-text")
