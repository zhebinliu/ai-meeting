"""会议纪要模型:Meeting + Requirement。

源自独立项目 meeting-ai 的合并(2026-05-11)。相对原项目的关键调整:
- 主键沿用 int autoincrement(meeting-ai 内部 19 处用 meeting_id:int,改 UUID 会触发大改)
- meeting_minutes / stakeholder_map 从 TEXT 改 JSON(Postgres 下走 JSONB)
- 新增 owner_id(JWT 多用户隔离)
- 新增 project_id FK(替换原 kb_project_id 字符串)
"""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from models import Base
from services._time import utcnow_naive as _utcnow


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="未命名会议")

    # 用户 / 项目隔离
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True, index=True)

    # 时间线
    start_time: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    # 转写产物
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    polished_transcript: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    # meeting_minutes JSON 结构:{summary, key_points[], decisions[], action_items[]}
    meeting_minutes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 状态机:recording / processing / completed / failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="recording")
    asr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 音频文件存储(MinIO object key,Block C 引入)
    audio_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 飞书产物
    bitable_app_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feishu_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # KB 同步(纪要文档)
    kb_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kb_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 干系人图谱(JSON {stakeholders, relations, version})
    stakeholder_map: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stakeholder_kb_doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stakeholder_kb_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stakeholder_kb_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Meeting id={self.id} title={self.title!r} status={self.status!r}>"


class Requirement(Base):
    __tablename__ = "meeting_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    req_id: Mapped[str] = mapped_column(String(32), nullable=False, default="REQ-001")
    module: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="P2")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="待确认")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} req_id={self.req_id!r} priority={self.priority!r}>"
