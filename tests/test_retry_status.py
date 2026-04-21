import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import UpstreamException
from app.services.grok.utils import retry as retry_module


def test_retry_on_status_can_disable_status_retries(monkeypatch):
    async def _run():
        calls = 0

        async def always_rate_limited():
            nonlocal calls
            calls += 1
            raise UpstreamException(
                "rate limited",
                details={"status": 429},
            )

        def extract_status(error: Exception) -> int | None:
            if isinstance(error, UpstreamException) and error.details:
                return error.details.get("status")
            return None

        config = {
            "retry.max_retry": 3,
            "retry.retry_status_codes": [401, 429, 403],
            "retry.retry_budget": 90,
            "retry.retry_backoff_base": 0.1,
            "retry.retry_backoff_factor": 2,
            "retry.retry_backoff_max": 1,
        }
        monkeypatch.setattr(retry_module, "get_config", config.get)

        with pytest.raises(UpstreamException):
            await retry_module.retry_on_status(
                always_rate_limited,
                extract_status=extract_status,
                retry_codes=[],
            )

        assert calls == 1

    asyncio.run(_run())
