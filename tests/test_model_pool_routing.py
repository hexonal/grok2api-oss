import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.grok.models.model import ModelService
from app.services.token.manager import TokenManager, _describe_token_for_log
from app.services.token.models import TokenInfo
from app.services.token.pool import TokenPool


def test_grok_4_heavy_is_super_only():
    assert ModelService.pool_candidates_for_model("grok-4-heavy") == ["ssoSuper"]


def test_grok_4_1_expert_prefers_super_then_basic():
    assert ModelService.pool_candidates_for_model("grok-4.1-expert") == [
        "ssoSuper",
        "ssoBasic",
    ]


def test_grok_4_prefers_basic_then_super():
    assert ModelService.pool_candidates_for_model("grok-4") == [
        "ssoBasic",
        "ssoSuper",
    ]


def test_image_lite_prefers_basic_then_super():
    assert ModelService.pool_candidates_for_model("grok-imagine-image-lite") == [
        "ssoBasic",
        "ssoSuper",
    ]


def test_image_pro_prefers_super_then_basic():
    assert ModelService.pool_candidates_for_model("grok-imagine-image-pro") == [
        "ssoSuper",
        "ssoBasic",
    ]


def test_video_token_routing_keeps_super_first_candidates_for_normal_jobs():
    manager = TokenManager()

    basic_pool = TokenPool("ssoBasic")
    basic_pool.add(TokenInfo(token="basic-token", quota=80))
    super_pool = TokenPool("ssoSuper")
    super_pool.add(TokenInfo(token="super-token", quota=140))

    manager.pools = {
        "ssoBasic": basic_pool,
        "ssoSuper": super_pool,
    }

    token_info = manager.get_token_for_video(
        resolution="480p",
        video_length=6,
        pool_candidates=ModelService.pool_candidates_for_model("grok-imagine-video"),
    )

    assert token_info is not None
    assert token_info.token == "super-token"


def test_token_log_description_includes_note_when_available():
    token_info = TokenInfo(token="super-token-abcdef", quota=140, note="徐凌霄")

    description = _describe_token_for_log(token_info)

    assert description == "token=super-toke..., note=徐凌霄"


def test_token_log_description_omits_empty_note():
    token_info = TokenInfo(token="basic-token-abcdef", quota=80)

    description = _describe_token_for_log(token_info)

    assert description == "token=basic-toke..."
