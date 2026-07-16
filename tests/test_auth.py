"""
JWT 令牌模块 — 完整测试套件

覆盖场景:
  - access_token / refresh_token 生成与校验
  - 过期令牌处理
  - 签名伪造检测
  - 类型混用检测
  - 令牌刷新（refresh grant）
  - 撤销列表机制
  - 缺失令牌
  - 角色校验
  - 边界情况

运行:
  pytest tests/test_auth.py -v
  pytest tests/test_auth.py -v --cov=auth --cov-report=term-missing
"""

import time
import pytest
from unittest.mock import patch

from auth.token import TokenManager, TokenConfig, TokenPair, get_token_manager
from auth.middleware import TokenAuthMiddleware, validate_token, extract_token
from auth.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    TokenMissingError,
    TokenTypeError,
    AuthError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    """基础配置：短有效期便于测试"""
    return TokenConfig(
        secret_key="test-secret-key-for-pytest-only",
        algorithm="HS256",
        access_token_expire_minutes=1,
        refresh_token_expire_days=1,
        issuer="test-issuer",
        audience="test-audience",
        leeway_seconds=0,
    )


@pytest.fixture
def token_manager(config):
    """TokenManager 实例"""
    mgr = TokenManager(config)
    # 确保测试前撤销列表是干净的
    mgr._revoked_tokens.clear()
    return mgr


@pytest.fixture
def token_pair(token_manager):
    """预先生成的令牌对"""
    return token_manager.create_token_pair(
        user_id="user_001",
        extra_claims={"roles": ["user"], "email": "test@example.com"},
    )


# ===================================================================
# 1. 令牌生成测试
# ===================================================================

class TestTokenCreation:
    """令牌生成"""

    def test_create_token_pair_returns_valid_structure(self, token_pair):
        """生成令牌对，返回格式正确"""
        assert isinstance(token_pair, TokenPair)
        assert len(token_pair.access_token) > 20
        assert len(token_pair.refresh_token) > 20
        assert token_pair.token_type == "Bearer"
        assert token_pair.expires_in == 60  # 1 minute

    def test_access_token_contains_standard_claims(self, token_manager, config):
        """access_token 包含标准声明"""
        pair = token_manager.create_token_pair("user_001")
        payload = token_manager._decode(pair.access_token)

        assert payload["sub"] == "user_001"
        assert payload["iss"] == config.issuer
        assert payload["aud"] == config.audience
        assert payload["typ"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
        assert "nbf" in payload

    def test_extra_claims_preserved(self, token_manager):
        """额外声明被保留"""
        pair = token_manager.create_token_pair(
            "user_001",
            extra_claims={"roles": ["admin"], "tenant": "org-123"},
        )
        payload = token_manager._decode(pair.access_token)
        assert payload["roles"] == ["admin"]
        assert payload["tenant"] == "org-123"

    def test_unique_jti_per_token(self, token_manager):
        """每个令牌有唯一的 jti"""
        pair1 = token_manager.create_token_pair("user_001")
        pair2 = token_manager.create_token_pair("user_001")

        jti1 = token_manager._decode(pair1.access_token)["jti"]
        jti2 = token_manager._decode(pair2.access_token)["jti"]
        assert jti1 != jti2

    def test_expiry_set_correctly(self, token_manager, config):
        """过期时间设置正确"""
        pair = token_manager.create_token_pair("user_001")
        payload = token_manager._decode(pair.access_token)

        expected_exp = payload["iat"] + (config.access_token_expire_minutes * 60)
        assert abs(payload["exp"] - expected_exp) <= 1  # 1秒容忍


# ===================================================================
# 2. 令牌校验测试
# ===================================================================

class TestTokenValidation:
    """令牌校验"""

    def test_valid_access_token_passes(self, token_manager, token_pair):
        """有效 access_token 通过校验"""
        payload = token_manager.validate_access_token(token_pair.access_token)
        assert payload["sub"] == "user_001"
        assert payload["typ"] == "access"

    def test_valid_refresh_token_passes(self, token_manager, token_pair):
        """有效 refresh_token 通过校验"""
        payload = token_manager.validate_refresh_token(token_pair.refresh_token)
        assert payload["sub"] == "user_001"
        assert payload["typ"] == "refresh"

    def test_empty_token_raises(self, token_manager):
        """空令牌抛出异常"""
        with pytest.raises(TokenMissingError):
            token_manager.validate_access_token("")

        with pytest.raises(TokenMissingError):
            token_manager.validate_access_token(None)

    def test_expired_token_raises(self, config):
        """过期令牌抛出 TokenExpiredError"""
        # 使用 0 秒有效期
        expired_config = TokenConfig(
            **{**config.__dict__,
               "access_token_expire_minutes": -1,  # 立刻过期
               "leeway_seconds": 0}
        )
        mgr = TokenManager(expired_config)
        pair = mgr.create_token_pair("user_001")

        with pytest.raises(TokenExpiredError):
            mgr.validate_access_token(pair.access_token)

    def test_tampered_signature_raises(self, token_manager, token_pair):
        """签名被篡改抛出 TokenInvalidError"""
        # 篡改 payload 部分（第二部分），使签名失效
        parts = token_pair.access_token.split(".")
        payload = __import__("json").loads(
            __import__("base64").urlsafe_b64decode(parts[1] + "==").decode()
        )
        payload["sub"] = "hacker"
        import base64, json
        new_payload = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        tampered = f"{parts[0]}.{new_payload}.{parts[2]}"

        with pytest.raises(TokenInvalidError) as exc:
            token_manager.validate_access_token(tampered)
        assert "signature" in str(exc.value).lower() or "invalid" in str(exc.value).lower()

    def test_wrong_issuer_rejected(self, token_manager, token_pair):
        """错误签发者被拒绝"""
        payload = token_manager._decode(token_pair.access_token)
        payload["iss"] = "evil-issuer"

        wrong_token = token_manager._encode(
            "user_001", "access",
            expires_delta=__import__("datetime").timedelta(minutes=1),
            extra_claims={"iss": "evil-issuer"},
        )
        with pytest.raises(TokenInvalidError):
            token_manager.validate_access_token(wrong_token)

    def test_garbage_token_raises(self, token_manager):
        """乱码令牌抛出 TokenInvalidError"""
        with pytest.raises(TokenInvalidError):
            token_manager.validate_access_token("not.a.valid.jwt.token")

    def test_none_token_raises(self, token_manager):
        """None 令牌抛出 TokenMissingError"""
        with pytest.raises(TokenMissingError):
            token_manager.validate_access_token(None)


# ===================================================================
# 3. 令牌类型校验
# ===================================================================

class TestTokenType:
    """令牌类型混用检测"""

    def test_refresh_as_access_raises(self, token_manager, token_pair):
        """refresh_token 当作 access_token 使用被拒绝"""
        with pytest.raises(TokenTypeError) as exc:
            token_manager.validate_access_token(token_pair.refresh_token)
        assert "access_token" in str(exc.value).lower()

    def test_access_as_refresh_raises(self, token_manager, token_pair):
        """access_token 当作 refresh_token 使用被拒绝"""
        with pytest.raises(TokenTypeError) as exc:
            token_manager.validate_refresh_token(token_pair.access_token)
        assert "refresh_token" in str(exc.value).lower()


# ===================================================================
# 4. 令牌刷新测试
# ===================================================================

class TestTokenRefresh:
    """令牌刷新"""

    def test_refresh_returns_new_pair(self, token_manager, token_pair):
        """刷新操作返回新的令牌对"""
        new_pair = token_manager.refresh(token_pair.refresh_token)

        assert new_pair.access_token != token_pair.access_token
        assert new_pair.refresh_token != token_pair.refresh_token
        assert isinstance(new_pair, TokenPair)

    def test_old_refresh_revoked_after_refresh(self, token_manager, token_pair):
        """刷新后旧 refresh_token 被撤销"""
        token_manager.refresh(token_pair.refresh_token)

        with pytest.raises(TokenRevokedError):
            token_manager.validate_refresh_token(token_pair.refresh_token)

    def test_double_refresh_fails(self, token_manager, token_pair):
        """二次刷新被拒绝"""
        token_manager.refresh(token_pair.refresh_token)

        with pytest.raises(TokenRevokedError):
            token_manager.refresh(token_pair.refresh_token)

    def test_refresh_preserves_extra_claims(self, token_manager):
        """刷新后保留额外声明"""
        pair = token_manager.create_token_pair(
            "user_001", extra_claims={"roles": ["user"], "tenant": "abc"}
        )
        new_pair = token_manager.refresh(pair.refresh_token)
        payload = token_manager.validate_access_token(new_pair.access_token)

        assert payload["roles"] == ["user"]
        assert payload["tenant"] == "abc"


# ===================================================================
# 5. 撤销机制测试
# ===================================================================

class TestRevocation:
    """撤销机制"""

    def test_revoked_token_rejected(self, token_manager, token_pair):
        """被撤销的令牌在校验时被拒绝"""
        token_manager.revoke(token_pair.access_token)

        with pytest.raises(TokenRevokedError) as exc:
            token_manager.validate_access_token(token_pair.access_token)
        assert "revoked" in str(exc.value).lower()

    def test_revoke_invalid_token_no_error(self, token_manager):
        """撤销无效令牌不抛异常"""
        token_manager.revoke("invalid-token-string")  # 不应抛异常

    def test_cleanup_expired_revocations(self, token_manager):
        """撤销列表清理"""
        for i in range(15000):
            token_manager._revoked_tokens.add(f"jti_{i}")

        removed = token_manager._cleanup_expired_revocations()
        assert removed > 0
        assert 9000 <= len(token_manager._revoked_tokens) <= 10000


# ===================================================================
# 6. Bearer Token 提取
# ===================================================================

class TestTokenExtraction:
    """Bearer Token 提取"""

    def test_extract_valid_bearer(self):
        """正确提取 Bearer Token"""
        token = extract_token("Bearer abc123xyz")
        assert token == "abc123xyz"

    def test_extract_with_extra_spaces(self):
        """带额外空格"""
        token = extract_token("  Bearer   abc123xyz  ")
        assert token == "abc123xyz"

    def test_extract_missing_header(self):
        """缺失 Authorization 头"""
        with pytest.raises(TokenMissingError):
            extract_token(None)

    def test_extract_empty_header(self):
        """空 Authorization 头"""
        with pytest.raises(TokenMissingError):
            extract_token("")

    def test_extract_no_bearer_prefix(self):
        """没有 Bearer 前缀"""
        with pytest.raises(TokenMissingError):
            extract_token("abc123xyz")

    def test_extract_case_insensitive(self):
        """大小写不敏感"""
        token = extract_token("bearer abc123xyz")
        assert token == "abc123xyz"


# ===================================================================
# 7. 装饰器校验
# ===================================================================

class TestValidateTokenDecorator:
    """装饰器校验"""

    @pytest.mark.asyncio
    async def test_validate_with_token_in_kwargs(self, token_manager, token_pair):
        """通过 kwargs 传入 token，校验通过"""

        @validate_token(token_manager=token_manager)
        async def handler(request=None, **kwargs):
            return kwargs.get("_token_payload", {})

        result = await handler(token=token_pair.access_token)
        assert result["sub"] == "user_001"

    @pytest.mark.asyncio
    async def test_validate_invalid_token_raises(self, token_manager):
        """无效 token 抛异常"""

        @validate_token(token_manager=token_manager)
        async def handler(request=None, **kwargs):
            return "ok"

        with pytest.raises(AuthError):
            await handler(token="invalid-token")


# ===================================================================
# 8. 边界与安全测试
# ===================================================================

class TestEdgeCases:
    """边界与安全"""

    def test_very_long_user_id(self, token_manager):
        """超长用户ID"""
        long_id = "u" * 500
        pair = token_manager.create_token_pair(long_id)
        payload = token_manager.validate_access_token(pair.access_token)
        assert payload["sub"] == long_id

    def test_special_chars_in_claims(self, token_manager):
        """特殊字符在声明中"""
        pair = token_manager.create_token_pair(
            "user_001",
            extra_claims={"nickname": "用户<>\"'", "score": 999},
        )
        payload = token_manager.validate_access_token(pair.access_token)
        assert payload["nickname"] == "用户<>\"'"
        assert payload["score"] == 999

    def test_token_without_jti(self, token_manager):
        """缺少 jti 的令牌被拒绝"""
        token_manager._revoked_tokens.clear()

        import jwt
        payload = {
            "sub": "user_001",
            "iss": token_manager.config.issuer,
            "aud": token_manager.config.audience,
            "typ": "access",
            "iat": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "exp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc) +
                    __import__("datetime").timedelta(minutes=1),
        }
        bad_token = jwt.encode(
            payload,
            token_manager.config.secret_key,
            algorithm="HS256",
        )
        with pytest.raises(TokenInvalidError):
            token_manager.validate_access_token(bad_token)

    def test_get_token_manager_singleton(self):
        """全局单例测试"""
        mgr1 = get_token_manager()
        mgr2 = get_token_manager()
        assert mgr1 is mgr2

    @pytest.mark.parametrize("role,required,expected", [
        (["user"], ["user"], True),           # 足够权限
        (["user"], ["admin"], False),         # 权限不足
        (["admin", "user"], ["admin"], True), # 多角色包含目标
        ([], ["user"], False),                # 无角色
    ])
    def test_role_check_logic(self, role, required, expected):
        """角色校验逻辑"""
        result = set(required).issubset(set(role))
        assert result == expected
