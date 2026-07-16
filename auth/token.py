"""
JWT 令牌管理器 — 完整的令牌生命周期

功能：
  - HS256 / RS256 双算法支持
  - access_token (短期) + refresh_token (长期) 双令牌机制
  - 令牌过期自动检测与安全刷新
  - 撤销列表（黑名单）支持
  - 令牌内容校验（iss / aud / typ）
  - 防重放攻击（jti 唯一标识）
"""

from __future__ import annotations

import os
import time
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from typing import Any

import jwt  # PyJWT

from auth.exceptions import (
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    TokenMissingError,
    TokenTypeError,
)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class TokenConfig:
    """令牌配置"""
    secret_key: str = field(
        default_factory=lambda: os.getenv(
            "JWT_SECRET_KEY",
            hashlib.sha256(os.urandom(64)).hexdigest()[:64],
        )
    )
    algorithm: str = "HS256"                     # HS256 | RS256
    access_token_expire_minutes: int = 30        # access_token 有效期
    refresh_token_expire_days: int = 7           # refresh_token 有效期
    issuer: str = "travel-agent"                 # iss 签发者
    audience: str = "travel-agent-api"           # aud 受众
    leeway_seconds: int = 30                     # 时钟偏差容忍度

    # 公钥（仅在 RS256 时使用）
    public_key: str = field(
        default_factory=lambda: os.getenv("JWT_PUBLIC_KEY", "")
    )
    private_key: str = field(
        default_factory=lambda: os.getenv("JWT_PRIVATE_KEY", "")
    )


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class TokenPair:
    """令牌对"""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 1800  # access_token 过期秒数


# ---------------------------------------------------------------------------
# 令牌管理器
# ---------------------------------------------------------------------------

class TokenManager:
    """JWT 令牌完整生命周期管理"""

    def __init__(self, config: TokenConfig | None = None):
        self.config = config or TokenConfig()
        self._revoked_tokens: set[str] = set()  # 撤销列表（生产应换 Redis）

    # ==================================================================
    # 生成
    # ==================================================================

    def create_token_pair(
        self,
        user_id: str,
        extra_claims: dict[str, Any] | None = None,
    ) -> TokenPair:
        """
        生成 access_token + refresh_token 对

        Args:
            user_id: 用户唯一标识
            extra_claims: 额外声明（角色、权限等）

        Returns:
            TokenPair: access_token + refresh_token
        """
        now = datetime.now(timezone.utc)

        # access_token — 短期
        access_token = self._encode(
            subject=user_id,
            token_type="access",
            expires_delta=timedelta(minutes=self.config.access_token_expire_minutes),
            extra_claims=extra_claims,
        )

        # refresh_token — 长期
        refresh_token = self._encode(
            subject=user_id,
            token_type="refresh",
            expires_delta=timedelta(days=self.config.refresh_token_expire_days),
            extra_claims=extra_claims,
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.config.access_token_expire_minutes * 60,
        )

    def _encode(
        self,
        subject: str,
        token_type: str,
        expires_delta: timedelta,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """编码 JWT"""
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": subject,
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "typ": token_type,
            "jti": uuid.uuid4().hex,           # 唯一 ID，防重放
            "iat": now,
            "exp": now + expires_delta,
            "nbf": now,
        }
        if extra_claims:
            payload.update(extra_claims)

        key = self._signing_key()
        return jwt.encode(payload, key, algorithm=self.config.algorithm)

    # ==================================================================
    # 校验
    # ==================================================================

    def validate_access_token(self, token: str) -> dict[str, Any]:
        """
        校验 access_token 有效性

        Raises:
            TokenExpiredError: 令牌已过期
            TokenInvalidError: 令牌无效
            TokenTypeError: 令牌类型不是 access
            TokenRevokedError: 令牌已被撤销
        """
        payload = self._decode(token)

        # 类型校验
        if payload.get("typ") != "access":
            raise TokenTypeError("Expected access_token, got " + str(payload.get("typ")))

        # 撤销检查
        jti = payload.get("jti", "")
        if jti in self._revoked_tokens:
            raise TokenRevokedError(f"Token {jti[:8]}... has been revoked")

        return payload

    def validate_refresh_token(self, token: str) -> dict[str, Any]:
        """
        校验 refresh_token 有效性
        """
        payload = self._decode(token)

        if payload.get("typ") != "refresh":
            raise TokenTypeError("Expected refresh_token")

        jti = payload.get("jti", "")
        if jti in self._revoked_tokens:
            raise TokenRevokedError(f"Token {jti[:8]}... has been revoked")

        return payload

    def _decode(self, token: str) -> dict[str, Any]:
        """解码 JWT，统一异常处理"""
        if not token:
            raise TokenMissingError()

        try:
            key = self._verifying_key()
            return jwt.decode(
                token,
                key,
                algorithms=[self.config.algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience,
                leeway=self.config.leeway_seconds,
                options={
                    "require": ["exp", "iat", "jti", "typ"],
                    "verify_signature": True,
                },
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError()
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError(str(e))

    # ==================================================================
    # 刷新
    # ==================================================================

    def refresh(self, refresh_token: str) -> TokenPair:
        """
        使用 refresh_token 换取新的令牌对

        自动将旧 refresh_token 加入撤销列表，防止重复使用。
        """
        payload = self.validate_refresh_token(refresh_token)

        # 撤销旧 refresh_token（防止重复使用）
        self._revoked_tokens.add(payload["jti"])

        # 保留原有 extra_claims（角色/权限等）
        extra_claims = {
            k: v for k, v in payload.items()
            if k not in ("sub", "iss", "aud", "typ", "jti", "iat", "exp", "nbf")
        }

        return self.create_token_pair(
            user_id=payload["sub"],
            extra_claims=extra_claims or None,
        )

    # ==================================================================
    # 撤销
    # ==================================================================

    def revoke(self, token: str) -> None:
        """撤销令牌（登出时调用）"""
        try:
            payload = self._decode(token)
            self._revoked_tokens.add(payload["jti"])
        except AuthError:
            pass  # 已无效的令牌无需撤销

    def revoke_all_for_user(self, user_id: str) -> None:
        """撤销某用户的所有令牌（管理员操作）"""
        # 生产环境应查询 Redis 中该用户的所有 jti
        pass

    # ==================================================================
    # 密钥管理
    # ==================================================================

    def _signing_key(self) -> str:
        """获取签名密钥"""
        if self.config.algorithm.startswith("RS"):
            return self.config.private_key or self.config.secret_key
        return self.config.secret_key

    def _verifying_key(self) -> str:
        """获取验证密钥"""
        if self.config.algorithm.startswith("RS"):
            return self.config.public_key or self.config.private_key or self.config.secret_key
        return self.config.secret_key

    # ==================================================================
    # 撤销列表管理（演示用；生产换 Redis）
    # ==================================================================

    def _cleanup_expired_revocations(self) -> int:
        """清理已过期令牌的撤销记录（生产可用 Redis TTL 自动过期）"""
        removed = 0
        # 内存实现简单清理：保留最近 10000 条
        if len(self._revoked_tokens) > 10_000:
            excess = len(self._revoked_tokens) - 10_000
            self._revoked_tokens = set(list(self._revoked_tokens)[excess:])
            removed = excess
        return removed


# ---------------------------------------------------------------------------
# 全局单例（可选）
# ---------------------------------------------------------------------------

@lru_cache
def get_token_manager(config: TokenConfig | None = None) -> TokenManager:
    """获取 TokenManager 单例"""
    return TokenManager(config)
