"""Shared pytest fixtures for Meli tests."""
import pytest
import os


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(tmp_path_factory):
    """Set up isolated test environment for the entire test session."""
    tmp = tmp_path_factory.mktemp("meli_test")
    os.environ["MELI_CONFIG_DIR"] = str(tmp / "config")
    os.environ["MELI_DATA_DIR"] = str(tmp / "data")
    (tmp / "config").mkdir()
    (tmp / "data").mkdir()
    yield
    # Cleanup happens automatically


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all config/auth singletons between tests."""
    import meli.config as cfg_mod
    import meli.auth as auth_mod
    cfg_mod._config = None
    auth_mod._session.authenticated = False
    auth_mod._session.failed_attempts = 0
    auth_mod._session.locked_until = 0.0
    auth_mod._session.master_key_cache = None
    yield
    cfg_mod._config = None
