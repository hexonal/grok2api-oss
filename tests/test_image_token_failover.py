import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1 import image as image_module
from app.core.exceptions import AppException, ErrorType
from app.services.grok.models.model import ModelService
from app.services.token.models import TokenInfo, TokenStatus
from app.services.token.pool import TokenPool
from app.services.token.manager import TokenManager


def test_call_grok_routes_to_next_token_after_429(monkeypatch):
    async def _run():
        manager = TokenManager()

        super_pool = TokenPool("ssoSuper")
        super_pool.add(TokenInfo(token="limited-super", quota=140))

        basic_pool = TokenPool("ssoBasic")
        basic_pool.add(TokenInfo(token="good-basic", quota=80))

        manager.pools = {
            "ssoSuper": super_pool,
            "ssoBasic": basic_pool,
        }
        manager._schedule_save = lambda: None  # type: ignore[method-assign]

        calls: list[str] = []

        async def fake_chat(self, token, **kwargs):
            calls.append(token)
            if token == "limited-super":
                raise AppException(
                    message="Image generation is currently rate limited upstream.",
                    error_type=ErrorType.RATE_LIMIT.value,
                    code="rate_limit_exceeded",
                    status_code=429,
                )
            return object()

        class FakeImageCollectProcessor:
            def __init__(self, model_id, token, response_format="b64_json"):
                self.model_id = model_id
                self.token = token
                self.response_format = response_format

            async def process(self, response):
                return [f"image via {self.token}"]

        monkeypatch.setattr(image_module.GrokChatService, "chat", fake_chat)
        monkeypatch.setattr(
            image_module,
            "ImageCollectProcessor",
            FakeImageCollectProcessor,
        )

        images = await image_module.call_grok(
            manager,
            "limited-super",
            "draw a fox",
            ModelService.get("grok-imagine-image-pro"),
        )

        assert calls == ["limited-super", "good-basic"]
        assert super_pool.get("limited-super").status == TokenStatus.COOLING
        assert images == ["image via good-basic"]

    asyncio.run(_run())
