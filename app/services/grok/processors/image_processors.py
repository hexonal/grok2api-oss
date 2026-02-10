"""
图片生成响应处理器（HTTP）
"""

import asyncio
import random
from typing import AsyncGenerator, AsyncIterable, List, Set

import orjson
from curl_cffi.requests.errors import RequestsError

from app.core.config import get_config
from app.core.logger import logger
from app.core.exceptions import UpstreamException
from .base import (
    BaseProcessor,
    StreamIdleTimeoutError,
    _with_idle_timeout,
    _normalize_stream_line,
    _collect_image_urls,
    _is_http2_stream_error,
)


def _normalize_asset_path(url: str) -> str:
    """提取资产路径用于去重（去掉 -part-N 中间产物后缀）"""
    import re
    path = url.split("?")[0]
    path = re.sub(r"-part-\d+/", "/", path)
    if path.startswith("http"):
        from urllib.parse import urlparse
        path = urlparse(path).path
    return path


class ImageStreamProcessor(BaseProcessor):
    """图片生成流式响应处理器"""

    def __init__(
        self, model: str, token: str = "", n: int = 1, response_format: str = "b64_json"
    ):
        super().__init__(model, token)
        self.partial_index = 0
        self.n = n
        self.target_index = random.randint(0, 1) if n == 1 else None
        self.response_format = response_format
        if response_format == "url":
            self.response_field = "url"
        elif response_format == "base64":
            self.response_field = "base64"
        else:
            self.response_field = "b64_json"

    def _sse(self, event: str, data: dict) -> str:
        """构建 SSE 响应"""
        return f"event: {event}\ndata: {orjson.dumps(data).decode()}\n\n"

    async def _collect_image(
        self, url: str, images: list, seen: Set[str]
    ) -> bool:
        """收集单张图片，返回是否成功添加（去重）"""
        key = _normalize_asset_path(url)
        if key in seen:
            return False
        seen.add(key)

        if self.response_format == "url":
            processed = await self.process_url(url, "image")
            if processed:
                images.append(processed)
                return True
            return False

        try:
            dl_service = self._get_dl()
            base64_data = await dl_service.to_base64(url, self.token, "image")
            if base64_data:
                if "," in base64_data:
                    b64 = base64_data.split(",", 1)[1]
                else:
                    b64 = base64_data
                images.append(b64)
                return True
        except Exception as e:
            logger.warning(f"Failed to convert image to base64, falling back to URL: {e}")
            processed = await self.process_url(url, "image")
            if processed:
                images.append(processed)
                return True
        return False

    async def process(
        self, response: AsyncIterable[bytes]
    ) -> AsyncGenerator[str, None]:
        """处理流式响应"""
        final_images = []
        seen: Set[str] = set()
        idle_timeout = get_config("timeout.stream_idle_timeout")

        try:
            async for line in _with_idle_timeout(response, idle_timeout, self.model):
                line = _normalize_stream_line(line)
                if not line:
                    continue
                try:
                    data = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue

                resp = data.get("result", {}).get("response", {})

                # 图片生成进度 + img2img 完成 URL
                if img := resp.get("streamingImageGenerationResponse"):
                    image_index = img.get("imageIndex", 0)
                    progress = img.get("progress", 0)

                    if self.n == 1 and image_index != self.target_index:
                        continue

                    out_index = 0 if self.n == 1 else image_index

                    # progress=100 时携带最终图片 URL
                    img_url = img.get("imageUrl") or img.get("url") or ""
                    if img_url and progress >= 100:
                        await self._collect_image(img_url, final_images, seen)
                        continue

                    yield self._sse(
                        "image_generation.partial_image",
                        {
                            "type": "image_generation.partial_image",
                            self.response_field: "",
                            "index": out_index,
                            "progress": progress,
                        },
                    )
                    continue

                # cachedImageGenerationResponse（chat-based imageGen）
                if cached := resp.get("cachedImageGenerationResponse"):
                    img_url = cached.get("imageUrl") or ""
                    if img_url:
                        await self._collect_image(img_url, final_images, seen)
                    continue

                # modelResponse
                if mr := resp.get("modelResponse"):
                    if urls := _collect_image_urls(mr):
                        for url in urls:
                            await self._collect_image(url, final_images, seen)
                    continue

            for index, b64 in enumerate(final_images):
                if self.n == 1:
                    if index != self.target_index:
                        continue
                    out_index = 0
                else:
                    out_index = index

                yield self._sse(
                    "image_generation.completed",
                    {
                        "type": "image_generation.completed",
                        self.response_field: b64,
                        "index": out_index,
                        "usage": {
                            "total_tokens": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "input_tokens_details": {
                                "text_tokens": 0,
                                "image_tokens": 0,
                            },
                        },
                    },
                )
        except asyncio.CancelledError:
            logger.debug("Image stream cancelled by client")
        except StreamIdleTimeoutError as e:
            raise UpstreamException(
                message=f"Image stream idle timeout after {e.idle_seconds}s",
                status_code=504,
                details={
                    "error": str(e),
                    "type": "stream_idle_timeout",
                    "idle_seconds": e.idle_seconds,
                },
            )
        except RequestsError as e:
            if _is_http2_stream_error(e):
                logger.warning(f"HTTP/2 stream error in image: {e}")
                raise UpstreamException(
                    message="Upstream connection closed unexpectedly",
                    status_code=502,
                    details={"error": str(e), "type": "http2_stream_error"},
                )
            logger.error(f"Image stream request error: {e}")
            raise UpstreamException(
                message=f"Upstream request failed: {e}",
                status_code=502,
                details={"error": str(e)},
            )
        except Exception as e:
            logger.error(
                f"Image stream processing error: {e}",
                extra={"error_type": type(e).__name__},
            )
            raise
        finally:
            await self.close()


class ImageCollectProcessor(BaseProcessor):
    """图片生成非流式响应处理器"""

    def __init__(self, model: str, token: str = "", response_format: str = "b64_json"):
        super().__init__(model, token)
        self.response_format = response_format

    async def _collect_url(self, url: str, images: list, seen: Set[str]) -> None:
        """收集单个图片 URL，去重 + 根据 response_format 处理"""
        key = _normalize_asset_path(url)
        if key in seen:
            logger.debug(f"ImageCollect: skipping duplicate {url[:80]}")
            return
        seen.add(key)

        if self.response_format == "url":
            processed = await self.process_url(url, "image")
            if processed:
                images.append(processed)
            return
        try:
            dl_service = self._get_dl()
            base64_data = await dl_service.to_base64(url, self.token, "image")
            if base64_data:
                if "," in base64_data:
                    b64 = base64_data.split(",", 1)[1]
                else:
                    b64 = base64_data
                images.append(b64)
        except Exception as e:
            logger.warning(f"Failed to convert image to base64, falling back to URL: {e}")
            processed = await self.process_url(url, "image")
            if processed:
                images.append(processed)

    async def process(self, response: AsyncIterable[bytes]) -> List[str]:
        """处理并收集图片"""
        images = []
        seen: Set[str] = set()
        idle_timeout = get_config("timeout.stream_idle_timeout")

        try:
            async for line in _with_idle_timeout(response, idle_timeout, self.model):
                line = _normalize_stream_line(line)
                if not line:
                    continue
                try:
                    data = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue

                resp = data.get("result", {}).get("response", {})

                # 处理 streamingImageGenerationResponse（img2img 通过此字段返回图片）
                if img := resp.get("streamingImageGenerationResponse"):
                    progress = img.get("progress", 0)
                    img_url = img.get("imageUrl") or img.get("url") or ""
                    if img_url and progress >= 100:
                        await self._collect_url(img_url, images, seen)
                    continue

                # 处理 cachedImageGenerationResponse（chat-based imageGen 通过此字段返回）
                if cached := resp.get("cachedImageGenerationResponse"):
                    img_url = cached.get("imageUrl") or ""
                    if img_url:
                        logger.info(f"ImageCollect: got cachedImageGeneration URL")
                        await self._collect_url(img_url, images, seen)
                    continue

                # 处理 modelResponse
                if mr := resp.get("modelResponse"):
                    if urls := _collect_image_urls(mr):
                        for url in urls:
                            await self._collect_url(url, images, seen)
                    continue

        except asyncio.CancelledError:
            logger.debug("Image collect cancelled by client")
        except StreamIdleTimeoutError as e:
            logger.warning(f"Image collect idle timeout: {e}")
        except RequestsError as e:
            if _is_http2_stream_error(e):
                logger.warning(f"HTTP/2 stream error in image collect: {e}")
            else:
                logger.error(f"Image collect request error: {e}")
        except Exception as e:
            logger.error(
                f"Image collect processing error: {e}",
                extra={"error_type": type(e).__name__},
            )
        finally:
            await self.close()

        logger.info(f"ImageCollect: total images collected={len(images)}")
        return images


__all__ = ["ImageStreamProcessor", "ImageCollectProcessor"]
