"""会议音频文件 MinIO 存储封装。

Bucket 默认 `meeting-audio`(可通过 settings.meeting_audio_bucket 覆盖)。
首次上传时 ensure_bucket 幂等创建。
"""
from __future__ import annotations

import io
import time
from typing import Optional

import structlog
from minio import Minio
from minio.error import S3Error

from config import settings

logger = structlog.get_logger()


def _client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_user,
        secret_key=settings.minio_password,
        secure=False,
    )


def _bucket_name() -> str:
    # 兼容老 settings:若未配置 meeting_audio_bucket 则用默认值
    return getattr(settings, "meeting_audio_bucket", None) or "meeting-audio"


def ensure_bucket():
    """幂等创建 bucket。失败抛异常由调用方处理。"""
    mc = _client()
    bucket = _bucket_name()
    try:
        if not mc.bucket_exists(bucket):
            mc.make_bucket(bucket)
            logger.info("meeting_audio_bucket_created", bucket=bucket)
    except S3Error as e:
        logger.warning("ensure_bucket_failed", bucket=bucket, error=str(e)[:120])


def upload_audio(meeting_id: int, filename: str, content: bytes, content_type: str = "audio/mpeg") -> str:
    """上传音频。返回 object_key(用于后续下载和持久化)。"""
    ensure_bucket()
    mc = _client()
    bucket = _bucket_name()
    # key 形如 4/1715420000-录音.mp3
    safe_name = filename.replace("/", "_").replace("\\", "_")[:120]
    key = f"{meeting_id}/{int(time.time())}-{safe_name}"
    mc.put_object(bucket, key, io.BytesIO(content), len(content), content_type=content_type)
    logger.info("meeting_audio_uploaded", meeting_id=meeting_id, key=key, bytes=len(content))
    return key


def download_audio(object_key: str) -> bytes:
    """下载音频。失败抛 S3Error。"""
    mc = _client()
    bucket = _bucket_name()
    resp = mc.get_object(bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def delete_audio(object_key: Optional[str]):
    """删除音频(可选,会议删除时调用)。失败仅日志不抛。"""
    if not object_key:
        return
    try:
        _client().remove_object(_bucket_name(), object_key)
    except S3Error as e:
        logger.warning("meeting_audio_delete_failed", key=object_key, error=str(e)[:120])
