"""Tests for the service checks: settings, failure handling, and live connections."""

import os

import pytest
from dotenv import load_dotenv

from scripts.check_services import (
    REQUIRED_SETTINGS,
    check_postgres,
    check_redis,
    load_settings,
    main,
    safe_error,
)

FAKE_PASSWORD = "fake-test-password-123"
# Port 1 is reserved and nothing listens on it, which simulates a stopped service.
CLOSED_PORT = "1"


# ===== Helpers =====
def fake_settings(**overrides):
    """Build complete settings that point at a closed port."""
    settings = {key: "matchday" for key in REQUIRED_SETTINGS}
    settings.update(
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=CLOSED_PORT,
        POSTGRES_PASSWORD=FAKE_PASSWORD,
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=CLOSED_PORT,
        REDIS_PASSWORD=FAKE_PASSWORD,
    )
    settings.update(overrides)
    return settings


@pytest.fixture
def live_settings():
    """Load real settings from .env, and fail clearly if they are missing."""
    load_dotenv()
    return load_settings(os.environ)


# ===== Settings tests =====
def test_load_settings_returns_required_values():
    settings = load_settings(fake_settings())
    assert set(settings) == set(REQUIRED_SETTINGS)


def test_load_settings_ignores_unrelated_values():
    settings = load_settings({**fake_settings(), "UNRELATED": "value"})
    assert "UNRELATED" not in settings


@pytest.mark.parametrize("key", REQUIRED_SETTINGS)
def test_load_settings_rejects_missing_value(key):
    env = fake_settings()
    del env[key]
    with pytest.raises(ValueError, match=key):
        load_settings(env)


def test_load_settings_rejects_empty_value():
    with pytest.raises(ValueError, match="REDIS_PASSWORD"):
        load_settings(fake_settings(REDIS_PASSWORD=""))


def test_load_settings_error_does_not_show_other_values():
    env = fake_settings()
    del env["POSTGRES_USER"]
    with pytest.raises(ValueError) as error:
        load_settings(env)
    assert FAKE_PASSWORD not in str(error.value)


# ===== Failure handling tests =====
def test_safe_error_removes_password():
    message = safe_error(Exception(f"failed with {FAKE_PASSWORD}"), FAKE_PASSWORD)
    assert FAKE_PASSWORD not in message
    assert "***" in message


def test_safe_error_handles_empty_message():
    assert safe_error(ValueError(), FAKE_PASSWORD) == "ValueError"


@pytest.mark.parametrize("check", [check_postgres, check_redis])
def test_stopped_service_fails_without_raising(check):
    result = check(fake_settings())
    assert result.ok is False
    assert FAKE_PASSWORD not in result.detail


@pytest.mark.parametrize(
    ("check", "override"),
    [(check_postgres, {"POSTGRES_PORT": "not-a-port"}), (check_redis, {"REDIS_PORT": "not-a-port"})],
)
def test_invalid_port_fails_without_raising(check, override):
    assert check(fake_settings(**override)).ok is False


def test_main_returns_1_when_settings_are_missing(monkeypatch, capsys):
    monkeypatch.setattr("scripts.check_services.load_dotenv", lambda: None)
    for key in REQUIRED_SETTINGS:
        monkeypatch.delenv(key, raising=False)
    assert main() == 1
    assert "[FAIL] settings" in capsys.readouterr().out


# ===== Live service tests =====
@pytest.mark.integration
def test_postgres_accepts_correct_password(live_settings):
    result = check_postgres(live_settings)
    assert result.ok is True, result.detail


@pytest.mark.integration
def test_redis_accepts_correct_password(live_settings):
    result = check_redis(live_settings)
    assert result.ok is True, result.detail


@pytest.mark.integration
def test_postgres_rejects_wrong_password(live_settings):
    result = check_postgres({**live_settings, "POSTGRES_PASSWORD": FAKE_PASSWORD})
    assert result.ok is False
    assert FAKE_PASSWORD not in result.detail


@pytest.mark.integration
def test_redis_rejects_wrong_password(live_settings):
    result = check_redis({**live_settings, "REDIS_PASSWORD": FAKE_PASSWORD})
    assert result.ok is False
    assert FAKE_PASSWORD not in result.detail
