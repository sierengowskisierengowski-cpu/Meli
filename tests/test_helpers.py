"""Tests for utility helpers."""
import pytest
from meli.utils.helpers import (
    is_valid_ip, is_private_ip, format_bytes, format_duration,
    severity_rank, country_flag_emoji, truncate,
)


class TestIpValidation:
    def test_valid_ipv4(self):
        assert is_valid_ip("192.168.1.1") is True
        assert is_valid_ip("8.8.8.8") is True
        assert is_valid_ip("0.0.0.0") is True

    def test_valid_ipv6(self):
        assert is_valid_ip("::1") is True
        assert is_valid_ip("2001:db8::1") is True

    def test_invalid_ip(self):
        assert is_valid_ip("256.0.0.1") is False
        assert is_valid_ip("not-an-ip") is False
        assert is_valid_ip("") is False

    def test_private_ips(self):
        assert is_private_ip("192.168.1.1") is True
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("127.0.0.1") is True

    def test_public_ips(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("203.0.113.1") is False


class TestFormatters:
    def test_format_bytes(self):
        assert format_bytes(0) == "0.0 B"
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1024 * 1024) == "1.0 MB"
        assert format_bytes(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_duration(self):
        assert format_duration(30) == "30s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(3661) == "1h 1m"

    def test_truncate(self):
        assert truncate("hello", 10) == "hello"
        assert truncate("a" * 100, 20) == "a" * 17 + "..."

    def test_severity_rank(self):
        assert severity_rank("INFO") < severity_rank("LOW")
        assert severity_rank("LOW") < severity_rank("MEDIUM")
        assert severity_rank("MEDIUM") < severity_rank("HIGH")
        assert severity_rank("HIGH") < severity_rank("CRITICAL")

    def test_country_flag_emoji(self):
        # US flag should be 🇺🇸
        flag = country_flag_emoji("US")
        assert len(flag) == 2  # two regional indicator symbols
        assert country_flag_emoji("") == "🏳"
        assert country_flag_emoji("X") == "🏳"


class TestCrypto:
    def test_encrypt_decrypt(self):
        from meli.utils.crypto import encrypt, decrypt
        plaintext = "super secret api key"
        password = "test_password_123"
        blob = encrypt(plaintext, password)
        assert decrypt(blob, password) == plaintext

    def test_wrong_password_fails(self):
        from meli.utils.crypto import encrypt, decrypt
        from cryptography.fernet import InvalidToken
        blob = encrypt("secret", "correct_password")
        with pytest.raises(Exception):
            decrypt(blob, "wrong_password")

    def test_hash_and_verify(self):
        from meli.utils.crypto import hash_password, verify_password
        pw = "MyPassword123!"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True
        assert verify_password("wrong", hashed) is False
