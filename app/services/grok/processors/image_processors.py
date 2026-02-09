"""
图片生成响应处理器（HTTP）
"""

import asyncio
import random
from typing import AsyncGenerator, AsyncIterable, List

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

    async def process(
        self, response: AsyncIterable[bytes]
    ) -> AsyncGenerator[str, None]:
        """处理流式响应"""
        final_images = []
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

                    # img2img: progress=100 时可能携带图片 URL
                    img_url = img.get("imageUrl") or img.get("url") or ""
                    if img_url and progress >= 100:
                        if self.response_format == "url":
                            processed = await self.process_url(img_url, "image")
                            if processed:
                                final_images.append(processed)
                        else:
                            try:
                                dl_service = self._get_dl()
                                base64_data = await dl_service.to_base64(
                                    img_url, self.token, "image"
                                )
                                if base64_data:
                                    if "," in base64_data:
                                        b64 = base64_data.split(",", 1)[1]
                                    else:
                                        b64 = base64_data
                                    final_images.append(b64)
                            except Exception as e:
                                logger.warning(f"Failed to convert streaming image to base64: {e}")
                                processed = await self.process_url(img_url, "image")
                                if processed:
                                    final_images.append(processed)
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

                # modelResponse
                if mr := resp.get("modelResponse"):
                    if urls := _collect_image_urls(mr):
                        for url in urls:
                            if self.response_format == "url":
                                processed = await self.process_url(url, "image")
                                if processed:
                                    final_images.append(processed)
                                continue
                            try:
                                dl_service = self._get_dl()
                                base64_data = await dl_service.to_base64(
                                    url, self.token, "image"
                                )
                                if base64_data:
                                    if "," in base64_data:
                                        b64 = base64_data.split(",", 1)[1]
                                    else:
                                        b64 = base64_data
                                    final_images.append(b64)
                            except Exception as e:
                                logger.warning(
                                    f"Failed to convert image to base64, falling back to URL: {e}"
                                )
                                processed = await self.process_url(url, "image")
                                if processed:
                                    final_images.append(processed)
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

    async def _collect_url(self, url: str, images: list) -> None:
        """收集单个图片 URL，根据 response_format 处理"""
        if self.response_format == "url":
            processed = await self.process_url(url, "image")
            logger.info(f"ImageCollect: process_url result={processed[:120] if processed else None}")
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
                resp_keys = list(resp.keys()) if resp else []

                # 处理 streamingImageGenerationResponse（img2img 可能通过此字段返回图片）
                if img := resp.get("streamingImageGenerationResponse"):
                    progress = img.get("progress", 0)
                    img_url = img.get("imageUrl") or img.get("url") or ""
                    logger.info(
                        f"ImageCollect: streamingImageGenerationResponse "
                        f"progress={progress}, imageUrl={img_url[:120] if img_url else None}, "
                        f"keys={list(img.keys())}"
                    )
                    if img_url and progress >= 100:
                        await self._collect_url(img_url, images)
                    continue

                # 处理 modelResponse
                if mr := resp.get("modelResponse"):
                    mr_keys = list(mr.keys()) if isinstance(mr, dict) else type(mr).__name__
                    urls = _collect_image_urls(mr)
                    logger.info(
                        f"ImageCollect: modelResponse found, urls={urls}, "
                        f"mr_keys={mr_keys}, response_format={self.response_format}"
                    )
                    if urls:
                        for url in urls:
                            await self._collect_url(url, images)
                    continue

                if resp_keys:
                    logger.debug(f"ImageCollect: unhandled resp keys={resp_keys}")

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
