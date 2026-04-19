import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.token.manager import TokenManager
from app.services.token.models import TokenInfo, TokenStatus
from app.services.token.pool import TokenPool


def test_cleanup_expired_tokens_removes_only_expired_entries():
    async def _run():
        manager = TokenManager()

        basic_pool = TokenPool("ssoBasic")
        basic_pool.add(TokenInfo(token="expired-basic", status=TokenStatus.EXPIRED))
        basic_pool.add(TokenInfo(token="active-basic", status=TokenStatus.ACTIVE))

        super_pool = TokenPool("ssoSuper")
        super_pool.add(TokenInfo(token="expired-super", status=TokenStatus.EXPIRED))
        super_pool.add(TokenInfo(token="cooling-super", status=TokenStatus.COOLING))

        manager.pools = {
            "ssoBasic": basic_pool,
            "ssoSuper": super_pool,
        }

        saves: list[str] = []

        async def fake_save():
            saves.append("saved")

        manager._save = fake_save  # type: ignore[method-assign]

        result = await manager.cleanup_expired_tokens()

        assert result == {"checked": 4, "removed": 2}
        assert basic_pool.get("expired-basic") is None
        assert super_pool.get("expired-super") is None
        assert basic_pool.get("active-basic") is not None
        assert super_pool.get("cooling-super") is not None
        assert saves == ["saved"]

    asyncio.run(_run())
