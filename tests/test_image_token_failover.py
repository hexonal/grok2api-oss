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


def _new_manager_with_basic_tokens(tokens: list[tuple[str, int]]) -> TokenManager:
    manager = TokenManager()
    basic_pool = TokenPool("ssoBasic")
    for token, quota in tokens:
        basic_pool.add(TokenInfo(token=token, quota=quota))
    manager.pools = {"ssoBasic": basic_pool}
    manager._schedule_save = lambda: None  # type: ignore[method-assign]
    return manager


def _patch_image_ws(
    monkeypatch,
    manager: TokenManager,
    fake_stream,
    extra_config: dict | None = None,
):
    async def fake_reload_if_stale():
        return None

    async def fake_get_token_manager():
        return manager

    def fake_get_config(key, default=None):
        values = {
            "image.image_ws": True,
            "image.image_ws_nsfw": False,
            "image.image_ws_max_token_attempts": 3,
            "image.image_ws_circuit_breaker_threshold": 99,
            "image.image_ws_circuit_breaker_seconds": 60,
            "chat.stream": False,
        }
        if extra_config:
            values.update(extra_config)
        return values.get(key, default)

    monkeypatch.setattr(image_module, "get_token_manager", fake_get_token_manager)
    monkeypatch.setattr(image_module, "get_config", fake_get_config)
    monkeypatch.setattr(image_module.image_service, "stream", fake_stream)
    manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]


def _clear_image_ws_circuit():
    if hasattr(image_module, "_IMAGE_WS_CIRCUIT_UNTIL"):
        image_module._IMAGE_WS_CIRCUIT_UNTIL.clear()
    if hasattr(image_module, "_IMAGE_WS_FAILURE_COUNT"):
        image_module._IMAGE_WS_FAILURE_COUNT.clear()


async def _create_image_ws():
    return await image_module.create_image(
        image_module.ImageGenerationRequest(
            prompt="draw a tiny blue circle",
            model="grok-imagine-image-lite",
            n=1,
            size="1024x1024",
            response_format="b64_json",
            stream=False,
        )
    )


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
        _clear_image_ws_circuit()
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

        _patch_image_ws(monkeypatch, manager, fake_stream)

        response = await _create_image_ws()
        payload = json.loads(response.body)

        assert calls == ["limited-basic", "good-super"]
        assert basic_pool.get("limited-basic").status == TokenStatus.COOLING
        assert len(payload["data"]) == 1
        assert payload["data"][0]["b64_json"] == "ZmFrZS1pbWFnZQ=="

    asyncio.run(_run())


def test_create_image_ws_stops_after_configured_token_attempts(monkeypatch):
    async def _run():
        _clear_image_ws_circuit()
        manager = _new_manager_with_basic_tokens(
            [
                ("limited-0", 80),
                ("limited-1", 79),
                ("limited-2", 78),
                ("limited-3", 77),
                ("limited-4", 76),
            ]
        )
        calls: list[str] = []

        def fake_stream(token, **kwargs):
            async def stream():
                calls.append(token)
                yield {
                    "type": "error",
                    "error_code": "rate_limit_exceeded",
                    "error": "Image rate limit exceeded",
                }

            return stream()

        _patch_image_ws(monkeypatch, manager, fake_stream)

        try:
            await _create_image_ws()
        except AppException as exc:
            assert exc.status_code == 429
            assert exc.code == "rate_limit_exceeded"
        else:
            raise AssertionError("expected rate limit error")

        basic_pool = manager.pools["ssoBasic"]
        assert calls == ["limited-0", "limited-1", "limited-2"]
        assert basic_pool.get("limited-0").status == TokenStatus.COOLING
        assert basic_pool.get("limited-1").status == TokenStatus.COOLING
        assert basic_pool.get("limited-2").status == TokenStatus.COOLING
        assert basic_pool.get("limited-3").status == TokenStatus.ACTIVE
        assert basic_pool.get("limited-4").status == TokenStatus.ACTIVE

    asyncio.run(_run())


def test_create_image_ws_circuit_breaker_skips_upstream_calls(monkeypatch):
    async def _run():
        _clear_image_ws_circuit()
        manager = _new_manager_with_basic_tokens(
            [
                ("limited-0", 80),
                ("limited-1", 79),
                ("limited-2", 78),
                ("limited-3", 77),
            ]
        )
        calls: list[str] = []

        def fake_stream(token, **kwargs):
            async def stream():
                calls.append(token)
                yield {
                    "type": "error",
                    "error_code": "rate_limit_exceeded",
                    "error": "Image rate limit exceeded",
                }

            return stream()

        _patch_image_ws(
            monkeypatch,
            manager,
            fake_stream,
            {
                "image.image_ws_max_token_attempts": 2,
                "image.image_ws_circuit_breaker_threshold": 2,
            },
        )

        for _ in range(2):
            try:
                await _create_image_ws()
            except AppException as exc:
                assert exc.status_code == 429
            else:
                raise AssertionError("expected rate limit error")

        assert calls == ["limited-0", "limited-1"]
        assert manager.pools["ssoBasic"].get("limited-2").status == TokenStatus.ACTIVE
        assert manager.pools["ssoBasic"].get("limited-3").status == TokenStatus.ACTIVE

    asyncio.run(_run())


def test_create_image_ws_records_401_and_tries_next_token(monkeypatch):
    async def _run():
        _clear_image_ws_circuit()
        manager = _new_manager_with_basic_tokens(
            [
                ("unauthorized-basic", 80),
                ("good-basic", 79),
            ]
        )
        calls: list[str] = []

        def fake_stream(token, **kwargs):
            async def stream():
                calls.append(token)
                if token == "unauthorized-basic":
                    yield {
                        "type": "error",
                        "error_code": "connection_failed",
                        "error": "401, message='Invalid response status'",
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

        _patch_image_ws(monkeypatch, manager, fake_stream)

        response = await _create_image_ws()
        payload = json.loads(response.body)
        unauthorized = manager.pools["ssoBasic"].get("unauthorized-basic")

        assert calls == ["unauthorized-basic", "good-basic"]
        assert unauthorized.status == TokenStatus.ACTIVE
        assert unauthorized.quota == 80
        assert unauthorized.fail_count == 1
        assert payload["data"][0]["b64_json"] == "ZmFrZS1pbWFnZQ=="

    asyncio.run(_run())
