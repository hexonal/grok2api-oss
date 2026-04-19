"""
Common header helpers for Grok services.
"""

from __future__ import annotations

import uuid
from typing import Dict, Tuple

from app.core.config import get_config
from app.services.grok.utils.statsig import StatsigService


def _normalize_token(token: str) -> str:
    return token[4:] if token.startswith("sso=") else token


def _pick_config_value(*keys: str) -> str:
    for key in keys:
        value = get_config(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_security_profile() -> Tuple[str, str]:
    user_agent = _pick_config_value("grok.user_agent", "security.user_agent")
    cf_clearance = _pick_config_value(
        "grok.cf_clearance",
        "security.cf_clearance",
    )
    return user_agent, cf_clearance


def build_sso_cookie(token: str, include_rw: bool = True) -> str:
    token = _normalize_token(token)
    _user_agent, cf = resolve_security_profile()
    cookie = f"sso={token}"
    if include_rw:
        cookie = f"sso-rw={token}; {cookie}"
    if cf:
        cookie = f"{cookie};cf_clearance={cf}"
    return cookie


def apply_statsig(headers: Dict[str, str]) -> None:
    headers["x-statsig-id"] = StatsigService.gen_id()
    headers["x-xai-request-id"] = str(uuid.uuid4())


__all__ = ["apply_statsig", "build_sso_cookie", "resolve_security_profile"]
