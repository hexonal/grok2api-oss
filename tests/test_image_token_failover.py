import asyncio
import json
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


def test_create_image_ws_routes_to_next_token_after_429(monkeypatch):
    async def _run():
        manager = TokenManager()

        basic_pool = TokenPool("ssoBasic")
        basic_pool.add(TokenInfo(token="limited-basic", quota=80))

        super_pool = TokenPool("ssoSuper")
        super_pool.add(TokenInfo(token="good-super", quota=140))

        manager.pools = {
            "ssoBasic": basic_pool,
            "ssoSuper": super_pool,
        }
        manager._schedule_save = lambda: None  # type: ignore[method-assign]

        async def fake_reload_if_stale():
            return None

        async def fake_get_token_manager():
            return manager

        def fake_get_config(key, default=None):
            values = {
                "image.image_ws": True,
                "image.image_ws_nsfw": False,
                "chat.stream": False,
            }
            return values.get(key, default)

        calls: list[str] = []

        def fake_stream(token, **kwargs):
            async def stream():
                calls.append(token)
                if token == "limited-basic":
                    yield {
                        "type": "error",
                        "error_code": "rate_limit_exceeded",
                        "error": "Image rate limit exceeded",
                    }
                    return

                yield {
                    "type": "image",
                    "image_id": "img-1",
                    "stage": "final",
                    "blob": "data:image/jpeg;base64,ZmFrZS1pbWFnZQ==",
                    "blob_size": 256,
                    "url": "https://assets.grok.com/generated/img-1.jpg",
                    "is_final": True,
                }

            return stream()

        monkeypatch.setattr(image_module, "get_token_manager", fake_get_token_manager)
        monkeypatch.setattr(image_module, "get_config", fake_get_config)
        monkeypatch.setattr(image_module.image_service, "stream", fake_stream)
        manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]

        response = await image_module.create_image(
            image_module.ImageGenerationRequest(
                prompt="draw a tiny blue circle",
                model="grok-imagine-image-lite",
                n=1,
                size="1024x1024",
                response_format="b64_json",
                stream=False,
            )
        )
        payload = json.loads(response.body)

        assert calls == ["limited-basic", "good-super"]
        assert basic_pool.get("limited-basic").status == TokenStatus.COOLING
        assert len(payload["data"]) == 1
        assert payload["data"][0]["b64_json"] == "ZmFrZS1pbWFnZQ=="

    asyncio.run(_run())
