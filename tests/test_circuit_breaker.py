"""Tests for circuit_breaker module."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src import circuit_breaker
from src.circuit_breaker import is_open, trip, clear


@pytest.fixture
def breaker_state_file(tmp_cache_dir: Path) -> Path:
    """Provide the circuit breaker state file path."""
    state_file = tmp_cache_dir / "circuit_breakers.json"
    circuit_breaker.STATE_FILE = state_file
    return state_file


def test_is_open_no_state_file(breaker_state_file: Path) -> None:
    """Test is_open returns False when no state file exists."""
    assert not is_open("test_breaker")


def test_trip_creates_state(breaker_state_file: Path) -> None:
    """Test trip() creates a state file with open status."""
    trip("test_breaker", "test reason")

    assert breaker_state_file.exists()
    state = json.loads(breaker_state_file.read_text())
    assert "test_breaker" in state
    assert state["test_breaker"]["state"] == "open"
    assert state["test_breaker"]["reason"] == "test reason"


def test_is_open_returns_true_when_open(breaker_state_file: Path) -> None:
    """Test is_open returns True when breaker is open."""
    trip("test_breaker", "test reason")
    assert is_open("test_breaker")


def test_clear_removes_breaker(breaker_state_file: Path) -> None:
    """Test clear() removes breaker from state."""
    trip("test_breaker", "test reason")
    assert is_open("test_breaker")

    clear("test_breaker")
    assert not is_open("test_breaker")


def test_clear_nonexistent_breaker(breaker_state_file: Path) -> None:
    """Test clear() on nonexistent breaker doesn't raise error."""
    clear("nonexistent_breaker")
    assert breaker_state_file.exists()


def test_trip_with_auto_reset_hours(breaker_state_file: Path) -> None:
    """Test trip() with auto_reset_hours sets auto_reset_at."""
    trip("test_breaker", "test reason", auto_reset_hours=2)

    state = json.loads(breaker_state_file.read_text())
    assert "auto_reset_at" in state["test_breaker"]
    assert state["test_breaker"]["auto_reset_at"] is not None


def test_auto_reset_when_time_expired(breaker_state_file: Path) -> None:
    """Test breaker auto-resets when time expires."""
    trip("test_breaker", "test reason", auto_reset_hours=1)
    assert is_open("test_breaker")

    # Mock time to be after auto_reset_at
    future = datetime.utcnow() + timedelta(hours=2)
    with patch("src.circuit_breaker.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = future
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        assert not is_open("test_breaker")


def test_manual_reset_via_env(breaker_state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test manual reset via BREAKER_RESET environment variable."""
    trip("test_breaker", "test reason")
    assert is_open("test_breaker")

    monkeypatch.setenv("BREAKER_RESET", "test_breaker")
    assert not is_open("test_breaker")


def test_manual_reset_multiple_breakers(
    breaker_state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test manual reset with multiple breakers in BREAKER_RESET."""
    trip("breaker1", "reason1")
    trip("breaker2", "reason2")
    assert is_open("breaker1")
    assert is_open("breaker2")

    monkeypatch.setenv("BREAKER_RESET", "breaker1,breaker2")
    assert not is_open("breaker1")
    assert not is_open("breaker2")


def test_multiple_breakers_independent(breaker_state_file: Path) -> None:
    """Test multiple breakers are independent."""
    trip("breaker1", "reason1")
    trip("breaker2", "reason2")

    assert is_open("breaker1")
    assert is_open("breaker2")

    clear("breaker1")
    assert not is_open("breaker1")
    assert is_open("breaker2")
