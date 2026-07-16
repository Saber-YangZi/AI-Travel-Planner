"""认证异常类"""


class AuthError(Exception):
    """认证基类异常"""
    status_code: int = 401
    detail: str = "Authentication failed"

    def __init__(self, detail: str | None = None, status_code: int | None = None):
        self.detail = detail or self.__class__.detail
        self.status_code = status_code or self.__class__.status_code
        super().__init__(self.detail)


class TokenExpiredError(AuthError):
    """令牌已过期"""
    status_code = 401
    detail = "Token has expired"


class TokenInvalidError(AuthError):
    """令牌无效（签名错误、格式错误、负载篡改）"""
    status_code = 401
    detail = "Token is invalid"


class TokenRevokedError(AuthError):
    """令牌已被撤销（登出后使用）"""
    status_code = 401
    detail = "Token has been revoked"


class TokenMissingError(AuthError):
    """请求中缺少令牌"""
    status_code = 401
    detail = "Authorization token is missing"


class TokenTypeError(AuthError):
    """令牌类型不匹配（如用 refresh_token 访问资源接口）"""
    status_code = 401
    detail = "Token type is incorrect"
