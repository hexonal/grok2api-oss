"""
Grok 模型管理服务
"""

from enum import Enum
from typing import Optional, Tuple, List
from pydantic import BaseModel, Field

from app.core.exceptions import ValidationException


class Tier(str, Enum):
    """模型档位"""

    BASIC = "basic"
    SUPER = "super"


class Cost(str, Enum):
    """计费类型"""

    LOW = "low"
    HIGH = "high"


class PoolRouting(str, Enum):
    """Token 池路由策略"""

    BASIC_THEN_SUPER = "basic_then_super"
    SUPER_THEN_BASIC = "super_then_basic"
    SUPER_ONLY = "super_only"


class ModelInfo(BaseModel):
    """模型信息"""

    model_id: str
    grok_model: str
    model_mode: str
    tier: Tier = Field(default=Tier.BASIC)
    pool_routing: PoolRouting = Field(default=PoolRouting.BASIC_THEN_SUPER)
    cost: Cost = Field(default=Cost.LOW)
    display_name: str
    description: str = ""
    is_video: bool = False
    is_image: bool = False


class ModelService:
    """模型管理服务"""

    MODELS = [
        ModelInfo(
            model_id="grok-3",
            grok_model="grok-3",
            model_mode="MODEL_MODE_GROK_3",
            cost=Cost.LOW,
            display_name="GROK-3",
        ),
        ModelInfo(
            model_id="grok-3-mini",
            grok_model="grok-3",
            model_mode="MODEL_MODE_GROK_3_MINI_THINKING",
            cost=Cost.LOW,
            display_name="GROK-3-MINI",
        ),
        ModelInfo(
            model_id="grok-3-thinking",
            grok_model="grok-3",
            model_mode="MODEL_MODE_GROK_3_THINKING",
            cost=Cost.LOW,
            display_name="GROK-3-THINKING",
        ),
        ModelInfo(
            model_id="grok-4",
            grok_model="grok-4",
            model_mode="MODEL_MODE_GROK_4",
            cost=Cost.LOW,
            display_name="GROK-4",
        ),
        ModelInfo(
            model_id="grok-4-mini",
            grok_model="grok-4-mini",
            model_mode="MODEL_MODE_GROK_4_MINI_THINKING",
            cost=Cost.LOW,
            display_name="GROK-4-MINI",
        ),
        ModelInfo(
            model_id="grok-4-thinking",
            grok_model="grok-4",
            model_mode="MODEL_MODE_GROK_4_THINKING",
            cost=Cost.LOW,
            display_name="GROK-4-THINKING",
        ),
        ModelInfo(
            model_id="grok-4-heavy",
            grok_model="grok-4",
            model_mode="MODEL_MODE_HEAVY",
            cost=Cost.HIGH,
            tier=Tier.SUPER,
            pool_routing=PoolRouting.SUPER_ONLY,
            display_name="GROK-4-HEAVY",
        ),
        ModelInfo(
            model_id="grok-4.1-mini",
            grok_model="grok-4-1-thinking-1129",
            model_mode="MODEL_MODE_GROK_4_1_MINI_THINKING",
            cost=Cost.LOW,
            display_name="GROK-4.1-MINI",
        ),
        ModelInfo(
            model_id="grok-4.1-fast",
            grok_model="grok-4-1-thinking-1129",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.LOW,
            display_name="GROK-4.1-FAST",
        ),
        ModelInfo(
            model_id="grok-4.1-expert",
            grok_model="grok-4-1-thinking-1129",
            model_mode="MODEL_MODE_EXPERT",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="GROK-4.1-EXPERT",
        ),
        ModelInfo(
            model_id="grok-4.1-thinking",
            grok_model="grok-4-1-thinking-1129",
            model_mode="MODEL_MODE_GROK_4_1_THINKING",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="GROK-4.1-THINKING",
        ),
        ModelInfo(
            model_id="grok-3-imageGen",
            grok_model="grok-3",
            model_mode="",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok-3 ImageGen",
            description="Image generation via Grok-3 chat",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-4-imageGen",
            grok_model="grok-4",
            model_mode="",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok-4 ImageGen",
            description="Image generation via Grok-4 chat",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-4.1-imageGen",
            grok_model="grok-4-1-thinking-1129",
            model_mode="",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok-4.1 ImageGen",
            description="Image generation via Grok-4.1 chat",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-image-lite",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.LOW,
            display_name="Grok Imagine Image Lite",
            description="Official basic-tier image generation model",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-image",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Image",
            description="Official standard image generation model",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-image-pro",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Image Pro",
            description="Official pro image generation model",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-1.0",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Image Legacy",
            description="Legacy alias for grok-imagine-image",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-image-edit",
            grok_model="imagine-image-edit",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Image Edit",
            description="Official image edit model",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-1.0-edit",
            grok_model="imagine-image-edit",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Image Edit Legacy",
            description="Legacy alias for grok-imagine-image-edit",
            is_image=True,
        ),
        ModelInfo(
            model_id="grok-imagine-video",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Video",
            description="Official video generation model",
            is_video=True,
        ),
        ModelInfo(
            model_id="grok-imagine-1.0-video",
            grok_model="grok-3",
            model_mode="MODEL_MODE_FAST",
            cost=Cost.HIGH,
            pool_routing=PoolRouting.SUPER_THEN_BASIC,
            display_name="Grok Imagine Video Legacy",
            description="Legacy alias for grok-imagine-video",
            is_video=True,
        ),
    ]

    _map = {m.model_id: m for m in MODELS}

    @classmethod
    def get(cls, model_id: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return cls._map.get(model_id)

    @classmethod
    def list(cls) -> list[ModelInfo]:
        """获取所有模型"""
        return list(cls._map.values())

    @classmethod
    def valid(cls, model_id: str) -> bool:
        """模型是否有效"""
        return model_id in cls._map

    @classmethod
    def to_grok(cls, model_id: str) -> Tuple[str, str]:
        """转换为 Grok 参数"""
        model = cls.get(model_id)
        if not model:
            raise ValidationException(f"Invalid model ID: {model_id}")
        return model.grok_model, model.model_mode

    @classmethod
    def can_generate_image(cls, model_id: str) -> bool:
        """模型是否支持图片生成（仅 is_image 模型）"""
        model = cls.get(model_id)
        return bool(model and model.is_image)

    @classmethod
    def supports_vision(cls, model_id: str) -> bool:
        """模型是否支持图片输入/理解（非图片非视频的聊天模型）"""
        model = cls.get(model_id)
        if not model:
            return False
        return not model.is_image and not model.is_video

    @classmethod
    def ensure_chat_compatible(cls, model_id: str) -> None:
        """确保模型可用于 /v1/chat/completions"""
        model = cls.get(model_id)
        if not model:
            raise ValidationException(
                message=(
                    f"The model `{model_id}` does not exist or you do not have access to it."
                ),
                param="model",
                code="model_not_found",
            )
        if model.is_image:
            raise ValidationException(
                message=(
                    f"The model `{model_id}` does not support `/v1/chat/completions`. "
                    "Use `/v1/images/generations` for image generation or "
                    "`/v1/images/edits` for image editing."
                ),
                param="model",
                code="model_not_supported",
            )
        if model.is_video:
            raise ValidationException(
                message=(
                    f"The model `{model_id}` does not support `/v1/chat/completions`. "
                    "Use `/v1/videos` instead."
                ),
                param="model",
                code="model_not_supported",
            )

    @classmethod
    def pool_for_model(cls, model_id: str) -> str:
        """根据模型选择 Token 池"""
        return cls.pool_candidates_for_model(model_id)[0]

    @classmethod
    def pool_candidates_for_model(cls, model_id: str) -> List[str]:
        """按优先级返回可用 Token 池列表"""
        model = cls.get(model_id)
        if not model:
            return ["ssoBasic", "ssoSuper"]
        if model.pool_routing == PoolRouting.SUPER_ONLY:
            return ["ssoSuper"]
        if model.pool_routing == PoolRouting.SUPER_THEN_BASIC:
            return ["ssoSuper", "ssoBasic"]
        return ["ssoBasic", "ssoSuper"]


__all__ = ["ModelService"]
