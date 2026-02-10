"""
Models API 路由
"""

from fastapi import APIRouter

from app.services.grok.models.model import ModelService


router = APIRouter(tags=["Models"])


def _capabilities_for(m) -> dict:
    """根据模型能力返回支持的端点和特性"""
    caps = {"endpoints": [], "vision": False}
    if not m.is_image and not m.is_video:
        caps["endpoints"].append("/v1/chat/completions")
        caps["vision"] = True
    if m.is_image:
        caps["endpoints"].append("/v1/images/generations")
        caps["endpoints"].append("/v1/images/edits")
    if m.is_video:
        caps["endpoints"].append("/v1/videos")
    return caps


@router.get("/models")
async def list_models():
    """OpenAI 兼容 models 列表接口"""
    data = []
    for m in ModelService.list():
        caps = _capabilities_for(m)
        data.append({
            "id": m.model_id,
            "object": "model",
            "created": 0,
            "owned_by": "grok2api",
            "endpoints": caps["endpoints"],
            "capabilities": {
                "vision": caps["vision"],
            },
        })
    return {"object": "list", "data": data}


__all__ = ["router"]
