import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.token.models import FAIL_THRESHOLD, TokenInfo, TokenStatus


def test_403_failure_expires_token_immediately():
    token = TokenInfo(token="forbidden-token", status=TokenStatus.ACTIVE, quota=80)

    token.record_fail(403, "forbidden")

    assert token.status == TokenStatus.EXPIRED
    assert token.fail_count == FAIL_THRESHOLD
    assert token.last_fail_reason == "forbidden"


def test_401_failure_still_requires_threshold():
    token = TokenInfo(token="unauthorized-token", status=TokenStatus.ACTIVE, quota=80)

    for _ in range(FAIL_THRESHOLD - 1):
        token.record_fail(401, "unauthorized")

    assert token.status == TokenStatus.ACTIVE
    assert token.fail_count == FAIL_THRESHOLD - 1

    token.record_fail(401, "unauthorized")

    assert token.status == TokenStatus.EXPIRED
    assert token.fail_count == FAIL_THRESHOLD
