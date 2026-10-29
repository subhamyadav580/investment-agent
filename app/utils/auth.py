import secrets

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    # Fail closed: if no key is configured, private endpoints are unavailable rather than open.
    if not settings.api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_KEY is not configured on the server")
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Key")
