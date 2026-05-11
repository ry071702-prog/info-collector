"""Tests for structured logging module."""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from src import logger as logger_module


@pytest.fixture
def reset_logger_state(monkeypatch: pytest.MonkeyPatch):
    """Reset logger initialization state before each test."""
    monkeypatch.setattr(logger_module, "_initialized", False)
    yield
    monkeypatch.setattr(logger_module, "_initialized", False)


def test_setup_idempotent(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """setup() should be idempotent (callable multiple times safely)."""
    with patch("loguru.logger") as mock_logger:
        logger_module.setup()
        call_count_first = mock_logger.remove.call_count
        logger_module.setup()
        call_count_second = mock_logger.remove.call_count
        assert call_count_second == call_count_first


def test_get_returns_bound_logger(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """get() should return a logger bound with module name."""
    with patch("loguru.logger") as mock_logger:
        mock_bound = MagicMock()
        mock_logger.bind.return_value = mock_bound
        result = logger_module.get("test_module")
        mock_logger.bind.assert_called()
        assert result is not None


def test_setup_uses_env_log_level(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """setup() should use LOG_LEVEL environment variable."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    with patch("loguru.logger") as mock_logger:
        logger_module.setup()
        calls = [call[1] for call in mock_logger.add.call_args_list]
        assert any("DEBUG" in str(call) for call in calls)


def test_setup_default_log_level(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """setup() should default to INFO log level."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    with patch("loguru.logger") as mock_logger:
        logger_module.setup()
        calls = [call[1] for call in mock_logger.add.call_args_list]
        assert any("INFO" in str(call) for call in calls)


def test_setup_removes_default_handler(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """setup() should remove default loguru handler."""
    with patch("loguru.logger") as mock_logger:
        logger_module.setup()
        mock_logger.remove.assert_called_once()


def test_get_calls_setup(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """get() should trigger setup() initialization."""
    with patch.object(logger_module, "setup") as mock_setup:
        with patch("loguru.logger"):
            logger_module.get("test")
            mock_setup.assert_called()


def test_initialized_flag_set_after_setup(reset_logger_state, monkeypatch: pytest.MonkeyPatch):
    """_initialized should be True after setup()."""
    with patch("loguru.logger"):
        assert logger_module._initialized is False
        logger_module.setup()
        assert logger_module._initialized is True
