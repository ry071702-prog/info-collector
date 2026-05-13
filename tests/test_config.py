"""Tests for configuration module."""
from __future__ import annotations
import pytest
from src import config


def test_env_with_default(monkeypatch: pytest.MonkeyPatch):
    """env() should return default when key is not set."""
    monkeypatch.delenv("TEST_MISSING_VAR", raising=False)
    result = config.env("TEST_MISSING_VAR", default="default_value")
    assert result == "default_value"


def test_env_with_value(monkeypatch: pytest.MonkeyPatch):
    """env() should return the set value."""
    monkeypatch.setenv("TEST_VAR", "test_value")
    result = config.env("TEST_VAR")
    assert result == "test_value"


def test_env_required_missing(monkeypatch: pytest.MonkeyPatch):
    """env() with required=True should raise when missing."""
    monkeypatch.delenv("TEST_REQUIRED_VAR", raising=False)
    with pytest.raises(RuntimeError, match="Required env var TEST_REQUIRED_VAR is not set"):
        config.env("TEST_REQUIRED_VAR", required=True)


def test_env_required_present(monkeypatch: pytest.MonkeyPatch):
    """env() with required=True should return value when present."""
    monkeypatch.setenv("TEST_REQUIRED_VAR", "required_value")
    result = config.env("TEST_REQUIRED_VAR", required=True)
    assert result == "required_value"


def test_env_json_valid(monkeypatch: pytest.MonkeyPatch):
    """env_json() should parse valid JSON."""
    monkeypatch.setenv("TEST_JSON_VAR", '{"key": "value"}')
    result = config.env_json("TEST_JSON_VAR")
    assert result == {"key": "value"}


def test_env_json_missing_with_default(monkeypatch: pytest.MonkeyPatch):
    """env_json() should return default when missing."""
    monkeypatch.delenv("TEST_JSON_MISSING", raising=False)
    result = config.env_json("TEST_JSON_MISSING", default={"default": "data"})
    assert result == {"default": "data"}


def test_env_json_invalid(monkeypatch: pytest.MonkeyPatch):
    """env_json() should raise on invalid JSON."""
    monkeypatch.setenv("TEST_JSON_INVALID", "not json")
    with pytest.raises(Exception):
        config.env_json("TEST_JSON_INVALID")


def test_env_json_required_missing(monkeypatch: pytest.MonkeyPatch):
    """env_json() with required=True should raise when missing."""
    monkeypatch.delenv("TEST_JSON_REQUIRED", raising=False)
    with pytest.raises(RuntimeError):
        config.env_json("TEST_JSON_REQUIRED", required=True)


def test_env_bool_true_values(monkeypatch: pytest.MonkeyPatch):
    """env_bool() should recognize '1', 'true', 'yes', 'on' as True."""
    for val in ["1", "true", "yes", "on", "TRUE", "YES"]:
        monkeypatch.setenv("TEST_BOOL_VAR", val)
        assert config.env_bool("TEST_BOOL_VAR") is True


def test_env_bool_false_values(monkeypatch: pytest.MonkeyPatch):
    """env_bool() should return False for unrecognized values."""
    for val in ["0", "false", "no", "off", ""]:
        monkeypatch.setenv("TEST_BOOL_VAR", val)
        assert config.env_bool("TEST_BOOL_VAR") is False


def test_env_bool_default(monkeypatch: pytest.MonkeyPatch):
    """env_bool() should use default when variable is not set."""
    monkeypatch.delenv("TEST_BOOL_DEFAULT", raising=False)
    assert config.env_bool("TEST_BOOL_DEFAULT", default=True) is True
    assert config.env_bool("TEST_BOOL_DEFAULT", default=False) is False


def test_is_dry_run_default(monkeypatch: pytest.MonkeyPatch):
    """is_dry_run() should default to False."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert config.is_dry_run() is False


def test_is_dry_run_enabled(monkeypatch: pytest.MonkeyPatch):
    """is_dry_run() should return True when DRY_RUN is set."""
    monkeypatch.setenv("DRY_RUN", "true")
    assert config.is_dry_run() is True


def test_is_dry_run_disabled(monkeypatch: pytest.MonkeyPatch):
    """is_dry_run() should return False when DRY_RUN is explicitly false."""
    monkeypatch.setenv("DRY_RUN", "false")
    assert config.is_dry_run() is False
