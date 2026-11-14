from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.middleware import NewsAgentRateLimiter, validate_agent_message
from app.core import security


def test_message_validation_rejects_blank_and_oversized_input():
    assert validate_agent_message("  news  ") == "news"
    with pytest.raises(HTTPException) as blank:
        validate_agent_message("   ")
    assert blank.value.status_code == 400
    with pytest.raises(HTTPException) as oversized:
        validate_agent_message("x" * 4001)
    assert oversized.value.status_code == 400


def test_rate_limiter_returns_429_after_limit():
    limiter = NewsAgentRateLimiter(limit=1, window_seconds=60)
    limiter.check("client")
    with pytest.raises(HTTPException) as exc:
        limiter.check("client")
    assert exc.value.status_code == 429


def test_authentication_fails_closed_without_configured_token(monkeypatch):
    monkeypatch.setattr(security.settings, "news_agent_api_token", None)
    with pytest.raises(HTTPException) as exc:
        security.require_news_agent_auth(None)
    assert exc.value.status_code == 503


def test_authentication_requires_matching_bearer_token(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(security.settings, "news_agent_api_token", SecretStr("secret"))
    bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
    with pytest.raises(HTTPException) as exc:
        security.require_news_agent_auth(bad)
    assert exc.value.status_code == 401
