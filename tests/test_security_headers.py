import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import config
from app.services.grok.utils.headers import build_sso_cookie, resolve_security_profile


def test_resolve_security_profile_prefers_legacy_grok_values():
    old_config = config._config
    config._config = {
        "security": {
            "cf_clearance": "security-clearance",
            "user_agent": "security-user-agent",
        },
        "grok": {
            "cf_clearance": "legacy-clearance",
            "user_agent": "legacy-user-agent",
        },
    }

    try:
        assert resolve_security_profile() == (
            "legacy-user-agent",
            "legacy-clearance",
        )
    finally:
        config._config = old_config


def test_build_sso_cookie_falls_back_to_legacy_clearance():
    old_config = config._config
    config._config = {
        "security": {
            "cf_clearance": "",
            "user_agent": "security-user-agent",
        },
        "grok": {
            "cf_clearance": "legacy-clearance",
            "user_agent": "legacy-user-agent",
        },
    }

    try:
        assert (
            build_sso_cookie("token-123")
            == "sso-rw=token-123; sso=token-123;cf_clearance=legacy-clearance"
        )
    finally:
        config._config = old_config
