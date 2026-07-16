"""
令牌认证中间件

支持场景：
  - FastAPI / Starlette 请求拦截
  - Flask before_request 钩子
  - 通用 WSGI/ASGI 中间件
  - 手动函数式校验

用法：
  # FastAPI 集成：
  app.add_middleware(TokenAuthMiddleware)

  # 路由装饰器：
  @validate_token
  async def protected_endpoint(request):
      ...
"""

from __future__ import annotations

import re
from typing import Callable, Any
from functools import wraps

from auth.token import TokenManager, get_token_manager
from auth.exceptions import AuthError, TokenMissingError

# Bearer Token 提取正则
_BEARER_PATTERN = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


def extract_token(authorization_header: str | None) -> str:
    """
    从 Authorization 头中提取 Bearer Token

    Args:
        authorization_header: "Bearer xxxxxx"

    Returns:
        纯 token 字符串

    Raises:
        TokenMissingError: 头部缺失或格式不正确
    """
    if not authorization_header:
        raise TokenMissingError("Authorization header is missing")

    match = _BEARER_PATTERN.match(authorization_header.strip())
    if not match:
        raise TokenMissingError(
            "Invalid Authorization header format. Expected: Bearer <token>"
        )

    return match.group(1)


def validate_token(
    func: Callable | None = None,
    *,
    token_manager: TokenManager | None = None,
    require_roles: list[str] | None = None,
):
    """
    装饰器：验证请求令牌

    可用于 FastAPI 路由或任意异步函数。

    Args:
        token_manager: 可选，自定义 TokenManager 实例
        require_roles: 可选，要求的角色列表

    用法：
        @validate_token
        async def handler(request): ...

        @validate_token(require_roles=["admin"])
        async def admin_handler(request): ...
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            # 尝试从 kwargs 或 args 中获取 request / token
            request = kwargs.get("request") or (args[0] if args else None)
            token_str = _resolve_token_string(kwargs, request)

            mgr = token_manager or get_token_manager()
            payload = mgr.validate_access_token(token_str)

            # 角色校验
            if require_roles:
                user_roles = payload.get("roles", [])
                if not set(require_roles).issubset(set(user_roles)):
                    from auth.exceptions import AuthError
                    raise AuthError("Insufficient permissions", status_code=403)

            # 注入用户信息到 kwargs
            kwargs["_token_payload"] = payload
            return await fn(*args, **kwargs)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def _resolve_token_string(kwargs: dict, request: Any | None) -> str:
    """尝试多种方式获取 token"""
    # 方式1: 直接传入 token 参数
    token_str = kwargs.pop("token", None)
    if token_str:
        return token_str

    # 方式2: 从请求对象获取
    if request is None:
        raise TokenMissingError("No request object or token found")

    # FastAPI Request
    if hasattr(request, "headers"):
        auth_header = request.headers.get("Authorization")
        if auth_header:
            return extract_token(auth_header)

    # Flask Request
    if hasattr(request, "authorization"):
        try:
            token = request.authorization.get("token")
            if token:
                return token
        except Exception:
            pass

    raise TokenMissingError("Unable to extract token from request")


# ---------------------------------------------------------------------------
# FastAPI 中间件类
# ---------------------------------------------------------------------------

class TokenAuthMiddleware:
    """
    FastAPI / Starlette 中间件

    用法:
        from fastapi import FastAPI
        app = FastAPI()
        app.add_middleware(TokenAuthMiddleware)
    """

    def __init__(self, app, token_manager: TokenManager | None = None):
        self.app = app
        self.token_manager = token_manager or get_token_manager()
        # 无需认证的路径前缀（白名单）
        self.public_paths = {
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/auth/login",
            "/auth/register",
            "/auth/refresh",
        }

    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse
        from starlette.requests import Request

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path

        # 白名单路径跳过
        if any(path.startswith(p) for p in self.public_paths):
            await self.app(scope, receive, send)
            return

        try:
            auth_header = request.headers.get("Authorization")
            token_str = extract_token(auth_header)
            payload = self.token_manager.validate_access_token(token_str)

            # 将用户信息注入请求状态
            scope["user"] = {
                "sub": payload["sub"],
                "roles": payload.get("roles", []),
                "jti": payload.get("jti", ""),
            }

            await self.app(scope, receive, send)

        except TokenMissingError as e:
            response = JSONResponse(
                {"detail": e.detail}, status_code=401
            )
            await response(scope, receive, send)
        except AuthError as e:
            response = JSONResponse(
                {"detail": e.detail}, status_code=e.status_code
            )
            await response(scope, receive, send)
