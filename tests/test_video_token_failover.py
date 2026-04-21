import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import UpstreamException
from app.api.v1 import video as video_route_module
from app.services.grok.services import media as media_module
from app.services.token.manager import TokenManager
from app.services.token.models import TokenInfo, TokenStatus
from app.services.token.pool import TokenPool


def test_video_completions_routes_to_next_token_after_429(monkeypatch):
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

        manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]
        manager._schedule_save = lambda: None  # type: ignore[method-assign]
        monkeypatch.setattr(media_module, "get_token_manager", fake_get_token_manager)

        calls: list[str] = []

        async def fake_generate(
            self,
            token,
            prompt,
            aspect_ratio="3:2",
            video_length=6,
            resolution_name="480p",
            preset="normal",
        ):
            calls.append(token)
            if token == "limited-super":
                raise UpstreamException(
                    "Video generation failed: 429",
                    details={"status": 429},
                )

            async def stream():
                if False:
                    yield b""

            return stream()

        class FakeVideoCollectProcessor:
            def __init__(self, model, token):
                self.model = model
                self.token = token

            async def process(self, response):
                return {"video": f"generated via {self.token}"}

        monkeypatch.setattr(media_module.VideoService, "generate", fake_generate)
        monkeypatch.setattr(
            media_module,
            "VideoCollectProcessor",
            FakeVideoCollectProcessor,
        )

        result = await media_module.VideoService.completions(
            model="grok-imagine-video",
            messages=[{"role": "user", "content": "make a fox video"}],
            stream=False,
        )

        assert calls == ["limited-super", "good-basic"]
        assert super_pool.get("limited-super").status == TokenStatus.COOLING
        assert result == {"video": "generated via good-basic"}

    asyncio.run(_run())


def test_async_video_task_routes_to_next_token_after_429(monkeypatch):
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

        manager.reload_if_stale = fake_reload_if_stale  # type: ignore[method-assign]
        manager._schedule_save = lambda: None  # type: ignore[method-assign]
        monkeypatch.setattr(
            video_route_module,
            "get_token_manager",
            fake_get_token_manager,
        )
        monkeypatch.setattr(video_route_module, "get_config", lambda key: 0)

        calls: list[str] = []

        async def fake_generate(
            self,
            token,
            prompt,
            aspect_ratio="3:2",
            video_length=6,
            resolution_name="480p",
            preset="normal",
        ):
            calls.append(token)
            if token == "limited-super":
                raise UpstreamException(
                    "Video generation failed: 429",
                    details={"status": 429},
                )

            async def stream():
                if False:
                    yield b""

            return stream()

        monkeypatch.setattr(video_route_module.VideoService, "generate", fake_generate)

        task = video_route_module.VideoTask(
            id="task-1",
            model="grok-imagine-video",
            prompt="make a fox video",
        )

        await video_route_module._run_video_generation(
            task=task,
            image_data_uri=None,
            size="1024x1024",
            seconds=6,
            resolution_name="480p",
            preset="normal",
        )

        assert calls == ["limited-super", "good-basic"]
        assert super_pool.get("limited-super").status == TokenStatus.COOLING
        assert task.error == "Video generation stream ended without completion"

    asyncio.run(_run())
