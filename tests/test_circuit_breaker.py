"""Tests for circuit breaker module."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src import circuit_breaker


def test_is_open_when_not_tripped(tmp_circuit_breaker: Path) -> None:
    """is_open should return False when breaker is not tripped."""
    result = circuit_breaker.is_open("test_breaker")
    assert result is False


def test_trip_opens_breaker(tmp_circuit_breaker: Path) -> None:
    """trip() should open a breaker."""
    circuit_breaker.trip("test_breaker", "Test failure")

    assert circuit_breaker.is_open("test_breaker") is True


def test_trip_stores_state(tmp_circuit_breaker: Path) -> None:
    """trip() should store breaker state with tripped_at and reason."""
    circuit_breaker.trip("test_breaker", "Test failure reason")

    state = circuit_breaker._load()
    assert "test_breaker" in state
    assert state["test_breaker"]["state"] == "open"
    assert state["test_breaker"]["reason"] == "Test failure reason"
    assert "tripped_at" in state["test_breaker"]


def test_clear_closes_breaker(tmp_circuit_breaker: Path) -> None:
    """clear() should close an open breaker."""
    circuit_breaker.trip("test_breaker", "Test failure")
    assert circuit_breaker.is_open("test_breaker") is True

    circuit_breaker.clear("test_breaker")

    assert circuit_breaker.is_open("test_breaker") is False


def test_clear_nonexistent_breaker(tmp_circuit_breaker: Path) -> None:
    """clear() should not raise error when clearing nonexistent breaker."""
    circuit_breaker.clear("nonexistent_breaker")

    state = circuit_breaker._load()
    assert "nonexistent_breaker" not in state


def test_auto_reset_before_time(tmp_circuit_breaker: Path) -> None:
    """is_open should return True when auto_reset_at has not been reached."""
    future_time = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    state = {
        "test_breaker": {
            "state": "open",
            "tripped_at": datetime.utcnow().isoformat(),
            "reason": "Test",
            "auto_reset_at": future_time,
        }
    }
    circuit_breaker._save(state)

    assert circuit_breaker.is_open("test_breaker") is True


def test_auto_reset_after_time(tmp_circuit_breaker: Path) -> None:
    """is_open should return False and clear when auto_reset_at has passed."""
    past_time = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    state = {
        "test_breaker": {
            "state": "open",
            "tripped_at": datetime.utcnow().isoformat(),
            "reason": "Test",
            "auto_reset_at": past_time,
        }
    }
    circuit_breaker._save(state)

    assert circuit_breaker.is_open("test_breaker") is False


def test_trip_with_auto_reset_hours(tmp_circuit_breaker: Path) -> None:
    """trip() should set auto_reset_at when auto_reset_hours is provided."""
    circuit_breaker.trip("test_breaker", "Test failure", auto_reset_hours=2)

    state = circuit_breaker._load()
    assert "auto_reset_at" in state["test_breaker"]
    assert state["test_breaker"]["auto_reset_at"] is not None


def test_trip_without_auto_reset_hours(tmp_circuit_breaker: Path) -> None:
    """trip() should not set auto_reset_at when auto_reset_hours is None."""
    circuit_breaker.trip("test_breaker", "Test failure", auto_reset_hours=None)

    state = circuit_breaker._load()
    assert state["test_breaker"]["auto_reset_at"] is None


def test_manual_reset_via_env(tmp_circuit_breaker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_open should return False when BREAKER_RESET env contains breaker name."""
    circuit_breaker.trip("test_breaker", "Test failure")
    assert circuit_breaker.is_open("test_breaker") is True

    monkeypatch.setenv("BREAKER_RESET", "test_breaker")

    assert circuit_breaker.is_open("test_breaker") is False


def test_manual_reset_multiple_breakers(tmp_circuit_breaker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_open should handle multiple breaker names in BREAKER_RESET."""
    circuit_breaker.trip("breaker1", "Failure 1")
    circuit_breaker.trip("breaker2", "Failure 2")
    circuit_breaker.trip("breaker3", "Failure 3")

    monkeypatch.setenv("BREAKER_RESET", "breaker1, breaker3")

    assert circuit_breaker.is_open("breaker1") is False
    assert circuit_breaker.is_open("breaker2") is True
    assert circuit_breaker.is_open("breaker3") is False


def test_load_nonexistent_file(tmp_circuit_breaker: Path) -> None:
    """_load() should return empty dict when file does not exist."""
    if tmp_circuit_breaker.exists():
        tmp_circuit_breaker.unlink()

    state = circuit_breaker._load()

    assert state == {}


def test_load_invalid_json(tmp_circuit_breaker: Path) -> None:
    """_load() should return empty dict when JSON is invalid."""
    tmp_circuit_breaker.write_text("{invalid json")

    state = circuit_breaker._load()

    assert state == {}


def test_multiple_breakers(tmp_circuit_breaker: Path) -> None:
    """Multiple breakers should be stored and retrieved independently."""
    circuit_breaker.trip("breaker1", "Failure 1")
    circuit_breaker.trip("breaker2", "Failure 2")

    assert circuit_breaker.is_open("breaker1") is True
    assert circuit_breaker.is_open("breaker2") is True

    circuit_breaker.clear("breaker1")

    assert circuit_breaker.is_open("breaker1") is False
    assert circuit_breaker.is_open("breaker2") is True
