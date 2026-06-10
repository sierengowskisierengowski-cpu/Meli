"""Tests for the authentication module."""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect config/data dirs to temp paths for all tests."""
    monkeypatch.setenv("MELI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MELI_DATA_DIR", str(tmp_path / "data"))
    # Reload config singleton
    import meli.config as cfg_mod
    cfg_mod._config = None
    yield
    cfg_mod._config = None


class TestPasswordManagement:
    def test_set_and_verify_password(self):
        from meli.auth import set_master_password, verify_master_password
        set_master_password("MySecurePassword123!")
        assert verify_master_password("MySecurePassword123!") is True
        assert verify_master_password("WrongPassword") is False

    def test_change_password(self):
        from meli.auth import set_master_password, change_master_password, verify_master_password
        set_master_password("OldPassword123!")
        result = change_master_password("OldPassword123!", "NewPassword456!")
        assert result is True
        assert verify_master_password("NewPassword456!") is True
        assert verify_master_password("OldPassword123!") is False

    def test_change_password_wrong_current(self):
        from meli.auth import set_master_password, change_master_password
        set_master_password("CorrectPassword123!")
        result = change_master_password("WrongCurrent", "NewPass456!")
        assert result is False

    def test_is_setup_complete_false_initially(self):
        from meli.auth import is_setup_complete
        assert is_setup_complete() is False

    def test_is_setup_complete_true_after_set(self):
        from meli.auth import set_master_password, is_setup_complete
        set_master_password("Password123!")
        assert is_setup_complete() is True


class TestSessionManagement:
    def test_attempt_login_success(self):
        from meli.auth import set_master_password, attempt_login, _session
        _session.failed_attempts = 0
        _session.locked_until = 0.0
        set_master_password("TestPassword123!")
        success, msg = attempt_login("TestPassword123!")
        assert success is True
        assert "Authenticated" in msg

    def test_attempt_login_failure(self):
        from meli.auth import set_master_password, attempt_login, _session
        _session.failed_attempts = 0
        _session.locked_until = 0.0
        set_master_password("CorrectPassword!")
        success, msg = attempt_login("WrongPassword")
        assert success is False

    def test_lock_session(self):
        from meli.auth import set_master_password, attempt_login, lock_session, is_authenticated, _session
        _session.failed_attempts = 0
        _session.locked_until = 0.0
        set_master_password("TestPassword123!")
        attempt_login("TestPassword123!")
        assert is_authenticated() is True
        lock_session()
        assert is_authenticated() is False

    def test_reset_auth(self):
        from meli.auth import set_master_password, reset_auth, is_setup_complete
        set_master_password("Password123!")
        assert is_setup_complete() is True
        reset_auth()
        assert is_setup_complete() is False


class TestTOTP:
    def test_setup_and_verify_totp(self):
        import pyotp
        from meli.auth import setup_totp, confirm_totp_setup, verify_totp, is_totp_enabled
        secret, uri = setup_totp()
        assert len(secret) > 0
        assert "otpauth://" in uri

        # Generate valid code
        totp = pyotp.TOTP(secret)
        code = totp.now()

        assert confirm_totp_setup(code) is True
        assert is_totp_enabled() is True
        assert verify_totp(totp.now()) is True

    def test_verify_totp_invalid_code(self):
        import pyotp
        from meli.auth import setup_totp, confirm_totp_setup, verify_totp
        secret, _ = setup_totp()
        totp = pyotp.TOTP(secret)
        confirm_totp_setup(totp.now())
        assert verify_totp("000000") is False
