"""Test circuit breaker functionality."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.circuit_breaker as cb
from src.timeutil import utc_now, parse_utc


@pytest.fixture
def reset_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear BREAKER_RESET env var."""
    monkeypatch.delenv("BREAKER_RESET", raising=False)


def test_is_open_closed_breaker(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test that is_open returns False for breaker without a state file."""
    assert cb.is_open("test_breaker") is False


def test_trip_breaker(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test tripping a circuit breaker."""
    cb.trip("test_breaker", "test reason")

    state_file = tmp_cache_dir / "circuit_breakers.json"
    assert state_file.exists()

    data = json.loads(state_file.read_text())
    assert "test_breaker" in data
    assert data["test_breaker"]["state"] == "open"
    assert data["test_breaker"]["reason"] == "test reason"
    assert "tripped_at" in data["test_breaker"]


def test_is_open_tripped_breaker(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test that is_open returns True for a tripped breaker."""
    cb.trip("test_breaker", "test reason")
    assert cb.is_open("test_breaker") is True


def test_clear_breaker(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test clearing a circuit breaker."""
    cb.trip("test_breaker", "test reason")
    assert cb.is_open("test_breaker") is True

    cb.clear("test_breaker")
    assert cb.is_open("test_breaker") is False


def test_auto_reset_expired(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test that auto_reset_at in the past allows breaker to close."""
    past_time = (utc_now() - timedelta(hours=1)).isoformat()

    state_file = tmp_cache_dir / "circuit_breakers.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "test_breaker": {
            "state": "open",
            "tripped_at": utc_now().isoformat(),
            "reason": "test",
            "auto_reset_at": past_time,
        }
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    assert cb.is_open("test_breaker") is False


def test_auto_reset_pending(tmp_cache_dir: Path, reset_breaker: None) -> None:
    """Test that auto_reset_at in the future keeps breaker open."""
    future_time = (utc_now() + timedelta(hours=1)).isoformat()

    state_file = tmp_cache_dir / "circuit_breakers.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "test_breaker": {
            "state": "open",
            "tripped_at": utc_now().isoformat(),
            "reason": "test",
            "auto_reset_at": future_time,
        }
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    assert cb.is_open("test_breaker") is True


def test_manual_reset_via_env(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test manual reset via BREAKER_RESET env var."""
    cb.trip("test_breaker", "test reason")
    assert cb.is_open("test_breaker") is True

    monkeypatch.setenv("BREAKER_RESET", "test_breaker")
    assert cb.is_open("test_breaker") is False


def test_manual_reset_multiple_breakers(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test manual reset with comma-separated list."""
    cb.trip("breaker1", "reason1")
    cb.trip("breaker2", "reason2")

    monkeypatch.setenv("BREAKER_RESET", "breaker1,breaker2")
    assert cb.is_open("breaker1") is False
    assert cb.is_open("breaker2") is False


def test_trip_with_auto_reset_hours(
    tmp_cache_dir: Path, reset_breaker: None
) -> None:
    """Test tripping with auto_reset_hours."""
    cb.trip("test_breaker", "test reason", auto_reset_hours=2)

    state_file = tmp_cache_dir / "circuit_breakers.json"
    data = json.loads(state_file.read_text())

    assert "auto_reset_at" in data["test_breaker"]
    auto_reset = parse_utc(data["test_breaker"]["auto_reset_at"])
    assert auto_reset > utc_now()
