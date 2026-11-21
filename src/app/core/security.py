"""Small, fail-closed security dependencies for protected agent routes."""

from hmac import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings


bearer = HTTPBearer(auto_error=False)


def require_news_agent_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    configured = settings.news_agent_api_token
    if not configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="News Agent authentication is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer" or not compare_digest(credentials.credentials, configured.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return "news-agent-client"
