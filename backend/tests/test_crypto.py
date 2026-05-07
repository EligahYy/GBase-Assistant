"""密码加密/解密测试。"""

from __future__ import annotations

from app.security.crypto import decrypt_password, encrypt_password


class TestPasswordEncryption:
    """AES-GCM 密码加密测试。"""

    def test_round_trip(self, monkeypatch):
        """加密后解密应还原原始密码。"""
        monkeypatch.setenv("DB_PASSWORD_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")  # 32字节 base64
        plain = "my_secret_password_123"
        cipher = encrypt_password(plain)
        assert cipher is not None
        assert cipher != plain
        decrypted = decrypt_password(cipher)
        assert decrypted == plain

    def test_none_input(self, monkeypatch):
        """None 输入应返回 None。"""
        monkeypatch.setenv("DB_PASSWORD_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
        assert encrypt_password(None) is None
        assert decrypt_password(None) is None

    def test_empty_string(self, monkeypatch):
        """空字符串应返回 None。"""
        monkeypatch.setenv("DB_PASSWORD_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
        assert encrypt_password("") is None
        assert decrypt_password("") is None

    def test_different_keys_dont_decrypt(self, monkeypatch):
        """不同密钥不能解密对方加密的数据。"""
        from app.security import crypto as crypto_module

        # 先清除全局缓存
        crypto_module._encryption_key = None
        monkeypatch.setenv("DB_PASSWORD_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
        plain = "secret"
        cipher = encrypt_password(plain)

        # 更换密钥并清除缓存
        crypto_module._encryption_key = None
        monkeypatch.setenv("DB_PASSWORD_KEY", "YW5vdGhlcmtleWFub3RoZXJrZXlhbm90aGVy")
        decrypted = decrypt_password(cipher)
        # 解密应失败，返回 None
        assert decrypted is None

    def test_unicode_password(self, monkeypatch):
        """中文密码应正确加密解密。"""
        monkeypatch.setenv("DB_PASSWORD_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
        plain = "中文密码_测试!@#"
        cipher = encrypt_password(plain)
        decrypted = decrypt_password(cipher)
        assert decrypted == plain
