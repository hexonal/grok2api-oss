import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.image import (
    _is_rate_limit_error,
    _raise_if_no_images,
    _select_images,
)
from app.core.exceptions import AppException


def test_is_rate_limit_error_by_message():
    exc = Exception("WebSocket error: rate_limit_exceeded - Image rate limit exceeded")
    assert _is_rate_limit_error(exc) is True


def test_is_rate_limit_error_by_code_attribute():
    class _FakeError(Exception):
        code = "rate_limit_exceeded"

    assert _is_rate_limit_error(_FakeError("x")) is True


def test_select_images_no_error_padding():
    images = ["img-a", "img-b"]
    selected = _select_images(images, 5)
    assert selected == images
    assert "error" not in selected


def test_raise_if_no_images_rate_limited():
    with pytest.raises(AppException) as exc_info:
        _raise_if_no_images([], rate_limited=True)

    exc = exc_info.value
    assert exc.status_code == 429
    assert exc.code == "rate_limit_exceeded"


def test_raise_if_no_images_upstream_error():
    with pytest.raises(AppException) as exc_info:
        _raise_if_no_images([], rate_limited=False)

    exc = exc_info.value
    assert exc.status_code == 502
    assert exc.code == "upstream_error"
