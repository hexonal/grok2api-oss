"""
OSS 对象存储服务 — 将图片/视频上传到 S3 兼容存储
"""

from datetime import datetime, timezone
from typing import Optional

import aioboto3

from app.core.config import get_config
from app.core.logger import logger


class OssService:
    """S3 兼容的对象存储服务"""

    def __init__(self):
        self._session = aioboto3.Session()

    @staticmethod
    def is_enabled() -> bool:
        if not get_config("oss.enabled", False):
            return False
        required = ("oss.endpoint", "oss.access_key", "oss.secret_key", "oss.bucket")
        return all(get_config(k) for k in required)

    def _get_client_kwargs(self) -> dict:
        return dict(
            service_name="s3",
            endpoint_url=get_config("oss.endpoint"),
            aws_access_key_id=get_config("oss.access_key"),
            aws_secret_access_key=get_config("oss.secret_key"),
            region_name=get_config("oss.region", "us-east-1"),
        )

    def _build_object_key(self, filename: str, media_type: str = "image") -> str:
        prefix = get_config("oss.path_prefix", "grok").strip("/")
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{prefix}/{media_type}/{date_str}/{filename}"

    def get_public_url(self, object_key: str) -> str:
        public_base = get_config("oss.public_base_url", "")
        if public_base:
            return f"{public_base.rstrip('/')}/{object_key}"
        endpoint = get_config("oss.endpoint", "")
        bucket = get_config("oss.bucket", "")
        return f"{endpoint.rstrip('/')}/{bucket}/{object_key}"

    async def upload_file(
        self, data: bytes, filename: str, content_type: str = "image/jpeg", media_type: str = "image"
    ) -> Optional[str]:
        if not self.is_enabled():
            return None

        object_key = self._build_object_key(filename, media_type)
        bucket = get_config("oss.bucket")

        try:
            async with self._session.client(**self._get_client_kwargs()) as client:
                await client.put_object(
                    Bucket=bucket,
                    Key=object_key,
                    Body=data,
                    ContentType=content_type,
                    ContentEncoding="identity",
                )
            url = self.get_public_url(object_key)
            logger.info(f"OSS upload ok: {object_key}")
            return url
        except Exception as e:
            logger.warning(f"OSS upload failed: {e}")
            return None


_oss_service: Optional[OssService] = None


def get_oss_service() -> OssService:
    global _oss_service
    if _oss_service is None:
        _oss_service = OssService()
    return _oss_service
