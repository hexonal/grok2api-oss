"""
异步视频生成 API 路由

提供 POST /videos 提交任务、GET /videos/{taskId} 轮询进度的异步任务模式，
供 Java 网关 (GrokGatewayApi) 对接。
"""

import asyncio
import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

import orjson
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import get_config
from app.core.exceptions import (
    AppException,
    ErrorType,
    ValidationException,
)
from app.core.logger import logger
from app.services.grok.models.model import ModelService
from app.services.grok.processors.base import (
    BaseProcessor,
    _with_idle_timeout,
    _normalize_stream_line,
)
from app.services.grok.services.assets import UploadService
from app.services.grok.services.media import VideoService
from app.services.token import get_token_manager, EffortType

router = APIRouter(tags=["Videos"])

# ---------------------------------------------------------------------------
# Task storage
# ---------------------------------------------------------------------------

_TASKS: dict[str, "VideoTask"] = {}


@dataclass
class VideoTask:
    """视频生成任务状态"""

    id: str
    model: str
    prompt: str
    status: str = "processing"  # processing | completed | failed
    progress: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))
    completed_at: Optional[int] = None
    video_url: Optional[str] = None
    error: Optional[str] = None

    def to_create_response(self) -> dict:
        return {
            "id": self.id,
            "object": "video.generation",
            "status": self.status,
            "created_at": self.created_at,
        }

    def to_response(self) -> dict:
        resp = {
            "id": self.id,
            "object": "video",
            "model": self.model,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "video_url": self.video_url,
            "error": self.error,
        }
        return resp


async def _expire_task(task_id: str, ttl: int) -> None:
    """TTL 后自动移除任务"""
    await asyncio.sleep(ttl)
    _TASKS.pop(task_id, None)


# ---------------------------------------------------------------------------
# Background generation coroutine
# ---------------------------------------------------------------------------


async def _run_video_generation(
    task: VideoTask,
    image_data_uri: Optional[str],
    aspect_ratio: str,
    seconds: int,
    size: str,
) -> None:
    """后台执行视频生成并更新 task 状态"""
    token_str: Optional[str] = None
    token_mgr = None

    try:
        # 1) 获取 token
        token_mgr = await get_token_manager()
        await token_mgr.reload_if_stale()

        pool_candidates = ModelService.pool_candidates_for_model(task.model)
        token_info = token_mgr.get_token_for_video(
            resolution=size,
            video_length=seconds,
            pool_candidates=pool_candidates,
        )

        if not token_info:
            task.status = "failed"
            task.error = "No available tokens"
            return

        token_str = token_info.token
        if token_str.startswith("sso="):
            token_str = token_str[4:]

        # 2) 上传图片（图生视频）
        image_url: Optional[str] = None
        if image_data_uri:
            upload_service = UploadService()
            try:
                _, file_uri = await upload_service.upload(image_data_uri, token_str)
                image_url = f"https://assets.grok.com/{file_uri}"
                logger.info(f"[VideoTask {task.id}] Image uploaded: {image_url}")
            finally:
                await upload_service.close()

        # 3) 调用 VideoService 获取流
        service = VideoService()
        if image_url:
            response = await service.generate_from_image(
                token_str,
                task.prompt,
                image_url,
                aspect_ratio,
                seconds,
                size,
            )
        else:
            response = await service.generate(
                token_str,
                task.prompt,
                aspect_ratio,
                seconds,
                size,
            )

        # 4) 解析流获取进度和最终 URL
        idle_timeout = get_config("timeout.video_idle_timeout")
        processor = BaseProcessor(task.model, token_str)

        try:
            async for line in _with_idle_timeout(response, idle_timeout, task.model):
                line = _normalize_stream_line(line)
                if not line:
                    continue
                try:
                    data = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue

                resp = data.get("result", {}).get("response", {})
                video_resp = resp.get("streamingVideoGenerationResponse")
                if not video_resp:
                    continue

                progress = video_resp.get("progress", 0)
                task.progress = progress

                if progress == 100:
                    video_url = video_resp.get("videoUrl", "")
                    if video_url:
                        final_url = await processor.process_url(video_url, "video")
                        task.video_url = final_url
                        task.status = "completed"
                        task.completed_at = int(time.time())
                        logger.info(
                            f"[VideoTask {task.id}] Completed: {final_url}"
                        )
        finally:
            await processor.close()

        # 如果流结束但未达到 100%，标记失败
        if task.status == "processing":
            task.status = "failed"
            task.error = "Video generation stream ended without completion"

        # 5) 记录 token 消耗
        if token_mgr and token_str and task.status == "completed":
            try:
                model_info = ModelService.get(task.model)
                effort = (
                    EffortType.HIGH
                    if (model_info and model_info.cost.value == "high")
                    else EffortType.LOW
                )
                await token_mgr.consume(token_str, effort)
            except Exception as e:
                logger.warning(f"[VideoTask {task.id}] Failed to record usage: {e}")

    except Exception as e:
        logger.error(f"[VideoTask {task.id}] Generation failed: {e}")
        task.status = "failed"
        task.error = str(e)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/videos")
async def create_video(
    prompt: str = Form(None),
    model: str = Form("grok-imagine-1.0-video"),
    aspect_ratio: str = Form("3:2"),
    seconds: str = Form("6"),
    size: str = Form("480p"),
    input_reference: Optional[UploadFile] = File(None),
):
    """提交视频生成任务，立即返回 task ID"""

    logger.info(
        f"Video generation request: prompt='{prompt}', model={model}, "
        f"aspect_ratio={aspect_ratio}, seconds={seconds}, size={size}, "
        f"has_input_reference={input_reference is not None and bool(input_reference.filename)}"
    )

    # 参数校验
    if not prompt or not prompt.strip():
        raise ValidationException(
            message="prompt is required",
            param="prompt",
            code="missing_prompt",
        )

    # 规范化参数
    size = size.lower()
    try:
        seconds_int = int(seconds)
    except (ValueError, TypeError):
        seconds_int = 6

    # 读取 input_reference 文件 → base64 data-URI
    image_data_uri: Optional[str] = None
    if input_reference and input_reference.filename:
        content = await input_reference.read()
        await input_reference.close()
        if content:
            mime = (input_reference.content_type or "image/jpeg").lower()
            ext = Path(input_reference.filename).suffix.lower()
            if mime in ("application/octet-stream", ""):
                mime_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                }
                mime = mime_map.get(ext, "image/jpeg")
            logger.info(
                f"Video input_reference: filename={input_reference.filename}, "
                f"size={len(content)} bytes, mime={mime}"
            )
            b64 = base64.b64encode(content).decode()
            image_data_uri = f"data:{mime};base64,{b64}"

    # 创建任务
    task_id = f"grok:{uuid4()}"
    task = VideoTask(id=task_id, model=model, prompt=prompt.strip())
    _TASKS[task_id] = task

    # 启动后台生成
    asyncio.create_task(
        _run_video_generation(task, image_data_uri, aspect_ratio, seconds_int, size)
    )
    # 1 小时后自动清理
    asyncio.create_task(_expire_task(task_id, 3600))

    return JSONResponse(content=task.to_create_response())


@router.get("/videos/{task_id}")
async def get_video(task_id: str):
    """查询视频生成任务状态"""
    task = _TASKS.get(task_id)
    if not task:
        raise AppException(
            message=f"Task not found: {task_id}",
            error_type=ErrorType.NOT_FOUND.value,
            code="task_not_found",
            status_code=404,
        )
    return JSONResponse(content=task.to_response())


__all__ = ["router"]
