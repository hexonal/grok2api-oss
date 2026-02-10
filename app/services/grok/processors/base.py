"""
响应处理器基类和通用工具
"""

import asyncio
import time
from typing import Any, AsyncGenerator, Optional, AsyncIterable, List, TypeVar

from app.core.config import get_config
from app.core.logger import logger
from app.services.grok.services.assets import DownloadService
from app.services.oss import get_oss_service


ASSET_URL = "https://assets.grok.com/"

T = TypeVar("T")


def _is_http2_stream_error(e: Exception) -> bool:
    """检查是否为 HTTP/2 流错误"""
    err_str = str(e).lower()
    return "http/2" in err_str or "curl: (92)" in err_str or "stream" in err_str


def _normalize_stream_line(line: Any) -> Optional[str]:
    """规范化流式响应行，兼容 SSE data 前缀与空行"""
    if line is None:
        return None
    if isinstance(line, (bytes, bytearray)):
        text = line.decode("utf-8", errors="ignore")
    else:
        text = str(line)
    text = text.strip()
    if not text:
        return None
    if text.startswith("data:"):
        text = text[5:].strip()
    if text == "[DONE]":
        return None
    return text


def _collect_image_urls(obj: Any) -> List[str]:
    """递归收集响应中的图片 URL"""
    urls: List[str] = []
    seen = set()

    def add(url: str):
        if not url or url in seen:
            return
        seen.add(url)
        urls.append(url)

    _LIST_KEYS = {
        "generatedImageUrls", "imageUrls", "imageURLs",
        "editedImageUrls", "resultImageUrls", "outputImageUrls",
        "imageEditUris", "fileUris",
    }
    _SINGLE_KEYS = {
        "imageUrl", "imageURL", "generatedImageUrl", "editedImageUrl",
    }

    def walk(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _LIST_KEYS:
                    if isinstance(item, list):
                        for url in item:
                            if isinstance(url, str):
                                add(url)
                    elif isinstance(item, str):
                        add(item)
                    continue
                if key in _SINGLE_KEYS:
                    if isinstance(item, str):
                        add(item)
                    continue
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)

    # 兜底：按已知字段名未找到 URL 时，扫描所有字符串值查找 Grok 资产路径
    if not urls:
        _scan_asset_urls(obj, add)

    return urls


def _scan_asset_urls(obj: Any, add_fn) -> None:
    """扫描所有字符串值，查找 Grok 资产 URL 模式"""
    if isinstance(obj, str):
        if "/generated/" in obj or "assets.grok.com" in obj:
            add_fn(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _scan_asset_urls(v, add_fn)
    elif isinstance(obj, list):
        for item in obj:
            _scan_asset_urls(item, add_fn)


class StreamIdleTimeoutError(Exception):
    """流空闲超时错误"""

    def __init__(self, idle_seconds: float):
        self.idle_seconds = idle_seconds
        super().__init__(f"Stream idle timeout after {idle_seconds}s")


async def _with_idle_timeout(
    iterable: AsyncIterable[T], idle_timeout: float, model: str = ""
) -> AsyncGenerator[T, None]:
    """
    包装异步迭代器，添加空闲超时检测

    Args:
        iterable: 原始异步迭代器
        idle_timeout: 空闲超时时间(秒)，0 表示禁用
        model: 模型名称(用于日志)
    """
    if idle_timeout <= 0:
        async for item in iterable:
            yield item
        return

    iterator = iterable.__aiter__()
    while True:
        try:
            item = await asyncio.wait_for(iterator.__anext__(), timeout=idle_timeout)
            yield item
        except asyncio.TimeoutError:
            logger.warning(
                f"Stream idle timeout after {idle_timeout}s",
                extra={"model": model, "idle_timeout": idle_timeout},
            )
            raise StreamIdleTimeoutError(idle_timeout)
        except StopAsyncIteration:
            break


class BaseProcessor:
    """基础处理器"""

    def __init__(self, model: str, token: str = ""):
        self.model = model
        self.token = token
        self.created = int(time.time())
        self.app_url = get_config("app.app_url")
        self._dl_service: Optional[DownloadService] = None

    def _get_dl(self) -> DownloadService:
        """获取下载服务实例（复用）"""
        if self._dl_service is None:
            self._dl_service = DownloadService()
        return self._dl_service

    async def close(self):
        """释放下载服务资源"""
        if self._dl_service:
            await self._dl_service.close()
            self._dl_service = None

    async def process_url(self, path: str, media_type: str = "image") -> str:
        """处理资产 URL"""
        original_path = path
        if path.startswith("http"):
            from urllib.parse import urlparse

            path = urlparse(path).path

        if not path.startswith("/"):
            path = f"/{path}"

        logger.info(f"process_url: original={original_path}, path={path}, app_url={self.app_url}")

        if self.app_url:
            dl_service = self._get_dl()
            local_path, mime_type = await dl_service.download(path, self.token, media_type)
            local_url = f"{self.app_url.rstrip('/')}/v1/files/{media_type}{path}"

            logger.info(f"process_url: downloaded local_path={local_path}, exists={local_path.exists() if local_path else False}, mime={mime_type}")

            if local_path and local_path.exists():
                oss = get_oss_service()
                oss_enabled = oss.is_enabled()
                logger.info(f"process_url: oss_enabled={oss_enabled}")
                if oss_enabled:
                    try:
                        data = local_path.read_bytes()
                        filename = local_path.name
                        default_ct = "video/mp4" if media_type == "video" else "image/jpeg"
                        oss_url = await oss.upload_file(data, filename, mime_type or default_ct, media_type)
                        if oss_url:
                            logger.info(f"process_url: OSS upload ok, url={oss_url}")
                            return oss_url
                    except Exception as e:
                        logger.warning(f"OSS upload in process_url failed: {e}")

            logger.info(f"process_url: returning local_url={local_url}")
            return local_url
        else:
            direct_url = f"{ASSET_URL.rstrip('/')}{path}"
            logger.info(f"process_url: no app_url, returning direct={direct_url}")
            return direct_url


__all__ = [
    "BaseProcessor",
    "StreamIdleTimeoutError",
    "_with_idle_timeout",
    "_normalize_stream_line",
    "_collect_image_urls",
    "_is_http2_stream_error",
]
