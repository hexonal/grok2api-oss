import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import UpstreamException
from app.services.grok.services import chat as chat_module
from app.services.token.manager import TokenManager
from app.services.token.models import TokenInfo, TokenStatus
from app.services.token.pool import TokenPool


def test_chat_completions_falls_back_after_super_token_403(monkeypatch):
    async def _run():
        manager = TokenManager()

        super_pool = TokenPool("ssoSuper")
        super_pool.add(TokenInfo(token="bad-super", quota=140))

        basic_pool = TokenPool("ssoBasic")
        basic_pool.add(TokenInfo(token="good-basic", quota=80))

        manager.pools = {
            "ssoSuper": super_pool,
            "ssoBasic": basic_pool,
        }
        manager.initialized = True

        async def fake_reload_if_stale():
            return None

        async def fake_get_token_manager():
            return manager

        monkeypatch.setattr(chat_module, "get_token_manager", fake_get_token_manager)
        manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]
        manager._schedule_save = lambda: None  # type: ignore[method-assign]

        calls: list[str] = []

        async def fake_chat_openai(self, token, request):
            calls.append(token)
            if token == "bad-super":
                await manager.record_fail(token, 403, "forbidden")
                raise UpstreamException(
                    "Grok API request failed: 403",
                    details={"status": 403, "body": "forbidden"},
                )
            return object(), False, request.model

        class FakeCollectProcessor:
            def __init__(self, model_name, token):
                self.model_name = model_name
                self.token = token

            async def process(self, response):
                return {
                    "choices": [
                        {"message": {"content": f"pong via {self.token}"}},
                    ]
                }

        monkeypatch.setattr(chat_module.GrokChatService, "chat_openai", fake_chat_openai)
        monkeypatch.setattr(chat_module, "CollectProcessor", FakeCollectProcessor)

        result = await chat_module.ChatService.completions(
            model="grok-4.1-expert",
            messages=[{"role": "user", "content": "Reply with exactly pong."}],
            stream=False,
        )

        assert calls == ["bad-super", "good-basic"]
        assert super_pool.get("bad-super").status == TokenStatus.EXPIRED
        assert result["choices"][0]["message"]["content"] == "pong via good-basic"

    asyncio.run(_run())


def test_chat_completions_falls_back_after_token_429(monkeypatch):
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
        manager.initialized = True

        async def fake_reload_if_stale():
            return None

        async def fake_get_token_manager():
            return manager

        monkeypatch.setattr(chat_module, "get_token_manager", fake_get_token_manager)
        manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]
        manager._schedule_save = lambda: None  # type: ignore[method-assign]

        calls: list[str] = []

        async def fake_chat_openai(self, token, request):
            calls.append(token)
            if token == "limited-super":
                await manager.record_fail(token, 429, "too many requests")
                raise UpstreamException(
                    "Grok API request failed: 429",
                    details={"status": 429, "body": "too many requests"},
                )
            return object(), False, request.model

        class FakeCollectProcessor:
            def __init__(self, model_name, token):
                self.model_name = model_name
                self.token = token

            async def process(self, response):
                return {
                    "choices": [
                        {"message": {"content": f"pong via {self.token}"}},
                    ]
                }

        monkeypatch.setattr(chat_module.GrokChatService, "chat_openai", fake_chat_openai)
        monkeypatch.setattr(chat_module, "CollectProcessor", FakeCollectProcessor)

        result = await chat_module.ChatService.completions(
            model="grok-4.1-expert",
            messages=[{"role": "user", "content": "Reply with exactly pong."}],
            stream=False,
        )

        assert calls == ["limited-super", "good-basic"]
        assert super_pool.get("limited-super").status == TokenStatus.COOLING
        assert result["choices"][0]["message"]["content"] == "pong via good-basic"

    asyncio.run(_run())
