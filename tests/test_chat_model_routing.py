import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.chat import ChatCompletionRequest, validate_request
from app.core.exceptions import ValidationException
from app.services.grok.services import chat as chat_module


def test_chat_request_accepts_text_model():
    request = ChatCompletionRequest(
        model="grok-4",
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    validate_request(request)


@pytest.mark.parametrize(
    ("model_id", "expected_endpoint"),
    [
        ("grok-imagine-image", "/v1/images/generations"),
        ("grok-imagine-video", "/v1/videos"),
    ],
)
def test_chat_request_rejects_media_models(model_id: str, expected_endpoint: str):
    request = ChatCompletionRequest(
        model=model_id,
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    with pytest.raises(ValidationException) as exc_info:
        validate_request(request)

    assert exc_info.value.code == "model_not_supported"
    assert expected_endpoint in exc_info.value.message


@pytest.mark.parametrize(
    ("model_id", "expected_endpoint"),
    [
        ("grok-imagine-image", "/v1/images/generations"),
        ("grok-imagine-video", "/v1/videos"),
    ],
)
def test_chat_service_rejects_media_models(model_id: str, expected_endpoint: str):
    async def _run():
        with pytest.raises(ValidationException) as exc_info:
            await chat_module.ChatService.completions(
                model=model_id,
                messages=[{"role": "user", "content": "hello"}],
                stream=False,
            )

        assert exc_info.value.code == "model_not_supported"
        assert expected_endpoint in exc_info.value.message

    asyncio.run(_run())
