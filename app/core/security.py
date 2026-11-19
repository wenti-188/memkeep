"""鉴权：可选的 API Key（Bearer 或 X-API-Key）。未配置 key 时自动放行，方便本地调试。"""
from fastapi import Header, Request

from app.core import config, exceptions


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    expected = config.settings.api_key
    if not expected:
        return None
    token = x_api_key or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise exceptions.UnauthorizedError()
    return None
