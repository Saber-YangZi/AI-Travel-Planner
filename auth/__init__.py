"""认证与授权模块。

提供 JWT 令牌的完整生命周期管理：
- access_token / refresh_token 的生成与校验
- 自动刷新与过期处理
- 请求拦截中间件
"""
from auth.token import TokenManager, TokenPair, TokenConfig
from auth.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    AuthError,
)
from auth.middleware import TokenAuthMiddleware

__all__ = [
    "TokenManager",
    "TokenPair",
    "TokenConfig",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    "AuthError",
    "TokenAuthMiddleware",
]
