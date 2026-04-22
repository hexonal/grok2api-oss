import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.grok.services import usage as usage_module


def test_usage_service_maps_remaining_queries_to_remaining_tokens(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "windowSizeSeconds": 7200,
                "remainingQueries": 40,
                "totalQueries": 40,
            }

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    def fake_get_config(key: str, default=None):
        if key == "performance.usage_max_concurrent":
            return 1
        if key == "security.browser":
            return "chrome136"
        if key == "network.timeout":
            return 30
        return default

    async def passthrough_retry(func, *args, **kwargs):
        return await func(*args)

    monkeypatch.setattr(usage_module, "AsyncSession", FakeSession)
    monkeypatch.setattr(usage_module, "get_config", fake_get_config)
    monkeypatch.setattr(usage_module, "retry_on_status", passthrough_retry)
    monkeypatch.setattr(usage_module, "resolve_security_profile", lambda: ("ua", ""))
    monkeypatch.setattr(usage_module, "apply_statsig", lambda headers: None)
    monkeypatch.setattr(usage_module, "build_sso_cookie", lambda token: f"sso={token}")

    service = usage_module.UsageService()
    result = asyncio.run(service.get("test-token"))

    assert result["remainingQueries"] == 40
    assert result["remainingTokens"] == 40
