import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.image import (
    DEFAULT_IMAGE_EDIT_MODEL,
    ImageEditRequest,
    ImageGenerationRequest,
    normalize_edit_model,
    normalize_generation_model,
    resolve_generation_runtime_model,
    validate_edit_request,
    validate_generation_request,
)
from app.api.v1.video import (
    _normalize_video_resolution_name,
    _normalize_video_size,
    _validate_video_preset,
    _validate_video_seconds,
    normalize_video_model,
)
from app.core.exceptions import ValidationException
from app.services.grok.models.model import ModelService


def test_model_service_recognizes_public_media_models():
    assert ModelService.valid("grok-imagine-image-lite")
    assert ModelService.valid("grok-imagine-image")
    assert ModelService.valid("grok-imagine-image-pro")
    assert ModelService.valid("grok-imagine-image-edit")
    assert ModelService.valid("grok-imagine-video")
    assert not ModelService.valid("grok-4.1")


def test_generation_model_normalizes_legacy_alias():
    request = ImageGenerationRequest(
        prompt="make it cinematic",
        model="grok-imagine-1.0",
    )

    assert normalize_generation_model(request.model) == "grok-imagine-image"


def test_edit_model_normalizes_legacy_alias():
    request = ImageEditRequest(
        prompt="add a rainbow",
        model="grok-imagine-1.0-edit",
    )

    assert normalize_edit_model(request.model) == "grok-imagine-image-edit"


def test_video_model_normalizes_legacy_alias():
    assert normalize_video_model("grok-imagine-1.0-video") == "grok-imagine-video"


def test_lite_image_model_limits_n_to_four():
    request = ImageGenerationRequest(
        prompt="draw a dragon",
        model="grok-imagine-image-lite",
        n=5,
        size="1024x1024",
    )

    with pytest.raises(ValidationException):
        validate_generation_request(request)


def test_image_edit_requires_dedicated_edit_model():
    request = ImageEditRequest(
        prompt="sharpen this image",
        model="grok-imagine-image",
        image=["https://example.com/ref.png"],
        n=1,
        size="1024x1024",
    )

    with pytest.raises(ValidationException):
        validate_edit_request(request)


def test_image_edit_accepts_public_edit_model():
    request = ImageEditRequest(
        prompt="sharpen this image",
        model="grok-imagine-image-edit",
        image=["https://example.com/ref.png"],
        n=2,
        size="1024x1024",
    )

    validate_edit_request(request)


def test_image_edit_requires_json_image_list():
    request = ImageEditRequest(
        prompt="sharpen this image",
        model="grok-imagine-image-edit",
        image=[],
        n=1,
        size="1024x1024",
    )

    with pytest.raises(ValidationException):
        validate_edit_request(request)


def test_generation_size_is_restricted_for_official_imagine_models():
    request = ImageGenerationRequest(
        prompt="draw a dragon",
        model="grok-imagine-image",
        n=1,
        size="1536x1024",
    )

    with pytest.raises(ValidationException):
        validate_generation_request(request)


def test_img2img_uses_edit_runtime_model():
    request = ImageGenerationRequest(
        prompt="draw a dragon",
        model="grok-imagine-image",
        image=["https://example.com/ref.jpg"],
        n=1,
        size="1024x1024",
    )

    runtime_model = resolve_generation_runtime_model(request)

    assert runtime_model.model_id == DEFAULT_IMAGE_EDIT_MODEL


def test_img2img_streaming_allows_url_response_format():
    request = ImageGenerationRequest(
        prompt="draw a dragon",
        model="grok-imagine-image",
        image=["https://example.com/ref.jpg"],
        n=1,
        size="1024x1024",
        stream=True,
        response_format="url",
    )

    validate_generation_request(request)


def test_img2img_limits_n_to_two():
    request = ImageGenerationRequest(
        prompt="draw a dragon",
        model="grok-imagine-image",
        image=["https://example.com/ref.jpg"],
        n=3,
        size="1024x1024",
    )

    with pytest.raises(ValidationException):
        validate_generation_request(request)


def test_video_parameters_follow_official_shapes():
    assert _normalize_video_size("1792x1024", None) == "1792x1024"
    assert _normalize_video_resolution_name("1792x1024", "720p") == "720p"
    assert _validate_video_preset("spicy") == "spicy"
    _validate_video_seconds(10)


def test_legacy_video_resolution_and_ratio_still_normalize():
    assert _normalize_video_size("720p", "3:2") == "1792x1024"
    assert _normalize_video_resolution_name("720p", None) == "720p"
