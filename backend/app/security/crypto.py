"""AES-GCM 密码加密/解密工具。

密钥来源优先级：
1. DB_PASSWORD_KEY 环境变量（32 字节 base64）
2. SECRET_KEY 环境变量派生（降级方案，重启后密钥不变）
3. 随机生成（应急方案，重启后无法解密）
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_SIZE: Final[int] = 12
_TAG_SIZE: Final[int] = 16
_KEY_SIZE: Final[int] = 32


def _get_encryption_key() -> bytes:
    """获取 AES-256 加密密钥，32 字节。"""
    raw = os.getenv("DB_PASSWORD_KEY", "")
    if raw:
        try:
            key = base64.b64decode(raw)
            if len(key) == _KEY_SIZE:
                return key
            logger.warning("DB_PASSWORD_KEY 解码后长度不为 32 字节，将使用派生密钥")
        except Exception:
            logger.warning("DB_PASSWORD_KEY 不是有效的 base64，将使用派生密钥")

    # 降级：从 Settings.secret_key 派生
    from app.config import get_settings

    secret = get_settings().secret_key
    if secret:
        return hashlib.sha256(secret.encode()).digest()

    # 应急：随机生成（重启后无法解密）
    logger.warning("未配置 DB_PASSWORD_KEY 或 SECRET_KEY，使用随机密钥（重启后密码将失效）")
    return os.urandom(_KEY_SIZE)


_encryption_key: bytes | None = None


def _lazy_key() -> bytes:
    global _encryption_key
    if _encryption_key is None:
        _encryption_key = _get_encryption_key()
    return _encryption_key


def encrypt_password(plain: str | None) -> str | None:
    """加密明文密码，返回 base64 编码的密文（nonce + ciphertext + tag）。"""
    if not plain:
        return None
    key = _lazy_key()
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plain.encode("utf-8"), None)
    # nonce + ciphertext (含 tag)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_password(cipher_b64: str | None) -> str | None:
    """解密密码。"""
    if not cipher_b64:
        return None
    key = _lazy_key()
    try:
        data = base64.b64decode(cipher_b64)
        if len(data) < _NONCE_SIZE + _TAG_SIZE:
            return None
        nonce = data[:_NONCE_SIZE]
        ciphertext = data[_NONCE_SIZE:]
        aesgcm = AESGCM(key)
        plain = aesgcm.decrypt(nonce, ciphertext, None)
        return plain.decode("utf-8")
    except Exception:
        logger.warning("密码解密失败，密钥可能已变更")
        return None
