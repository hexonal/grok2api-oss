import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import UpstreamException
from app.services.grok.services import usage as usage_module
from app.services.token.manager import FAIL_THRESHOLD, TokenManager
from app.services.token.models import TokenInfo, TokenStatus
from app.services.token.pool import TokenPool


def test_sync_usage_marks_403_as_expired(monkeypatch):
    async def _run():
        manager = TokenManager()

        basic_pool = TokenPool("ssoBasic")
        token = TokenInfo(token="forbidden-token", status=TokenStatus.COOLING, quota=0)
        basic_pool.add(token)
        manager.pools = {"ssoBasic": basic_pool}

        saves: list[str] = []

        def fake_schedule_save():
            saves.append("scheduled")

        async def fake_get(self, token_str: str, model_name: str = "grok-3"):
            raise UpstreamException(
                message="Failed to get usage stats: 403",
                details={"status": 403},
            )

        async def unexpected_consume(*args, **kwargs):
            raise AssertionError("403 should not fall back to local consume")

        monkeypatch.setattr(usage_module.UsageService, "get", fake_get)
        manager._schedule_save = fake_schedule_save  # type: ignore[method-assign]
        manager.consume = unexpected_consume  # type: ignore[method-assign]

        result = await manager.sync_usage(
            "forbidden-token",
            "grok-3",
            consume_on_fail=True,
            is_usage=False,
        )

        assert result is False
        assert token.status == TokenStatus.EXPIRED
        assert token.fail_count == FAIL_THRESHOLD
        assert token.last_sync_at is not None
        assert saves == ["scheduled"]

    asyncio.run(_run())


def test_refresh_cooling_tokens_marks_403_as_expired(monkeypatch):
    async def _run():
        manager = TokenManager()

        basic_pool = TokenPool("ssoBasic")
        token = TokenInfo(token="cooling-token", status=TokenStatus.COOLING, quota=0)
        basic_pool.add(token)
        manager.pools = {"ssoBasic": basic_pool}

        saves: list[str] = []

        async def fake_save():
            saves.append("saved")

        async def fake_get(self, token_str: str, model_name: str = "grok-3"):
            raise UpstreamException(
                message="Failed to get usage stats: 403",
                details={"status": 403},
            )

        monkeypatch.setattr(usage_module.UsageService, "get", fake_get)
        manager._save = fake_save  # type: ignore[method-assign]

        result = await manager.refresh_cooling_tokens()

        assert result == {"checked": 1, "refreshed": 1, "recovered": 0, "expired": 1}
        assert token.status == TokenStatus.EXPIRED
        assert token.fail_count == FAIL_THRESHOLD
        assert token.last_sync_at is not None
        assert saves == ["saved"]

    asyncio.run(_run())
