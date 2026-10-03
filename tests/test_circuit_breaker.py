"""Tests for file-based circuit breaker module."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json
import os

import pytest
from src.circuit_breaker import is_open, trip, clear


class TestCircuitBreaker:
    """Tests for circuit breaker state management."""

    def test_is_open_no_state_file(self, tmp_cache_dir: Path):
        """is_open should return False when no state file exists."""
        assert not is_open("test_breaker")

    def test_trip_creates_state_file(self, tmp_cache_dir: Path):
        """trip should create state file and mark breaker as open."""
        trip("test_breaker", "Test trip reason")
        assert is_open("test_breaker")

    def test_is_open_without_auto_reset(self, tmp_cache_dir: Path):
        """Breaker should remain open without auto_reset_at."""
        trip("persistent_breaker", "Should stay open", auto_reset_hours=None)
        assert is_open("persistent_breaker")

    def test_clear_resets_breaker(self, tmp_cache_dir: Path):
        """clear should remove breaker state and return is_open to False."""
        trip("temp_breaker", "Temporary trip")
        assert is_open("temp_breaker")
        clear("temp_breaker")
        assert not is_open("temp_breaker")

    def test_clear_nonexistent_breaker(self, tmp_cache_dir: Path):
        """clear should handle nonexistent breaker gracefully."""
        clear("nonexistent")
        assert not is_open("nonexistent")

    def test_multiple_breakers(self, tmp_cache_dir: Path):
        """Multiple breakers should maintain independent state."""
        trip("breaker_1", "First trip")
        trip("breaker_2", "Second trip")
        assert is_open("breaker_1")
        assert is_open("breaker_2")
        clear("breaker_1")
        assert not is_open("breaker_1")
        assert is_open("breaker_2")

    def test_trip_with_auto_reset(self, tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """Breaker with auto_reset_hours should auto-reset after duration."""
        # Mock current time
        mock_now = datetime(2026, 5, 13, 12, 0, 0)

        def mock_utcnow():
            return mock_now

        monkeypatch.setattr("src.circuit_breaker.datetime", type('obj', (), {
            'utcnow': mock_utcnow,
            'timedelta': timedelta,
        })())
        monkeypatch.setattr("src.circuit_breaker.datetime.utcnow", mock_utcnow)

        # Trip breaker with 1-hour auto-reset
        trip("auto_reset_breaker", "Auto-resetting trip", auto_reset_hours=1)
        assert is_open("auto_reset_breaker")

    def test_trip_stores_metadata(self, tmp_cache_dir: Path):
        """trip should store reason and timestamps in state file."""
        trip("info_breaker", "Test reason for recording")

        # Read the state file directly
        import src.circuit_breaker
        state = json.loads((src.circuit_breaker.STATE_FILE).read_text(encoding="utf-8"))

        assert "info_breaker" in state
        assert state["info_breaker"]["state"] == "open"
        assert state["info_breaker"]["reason"] == "Test reason for recording"
        assert "tripped_at" in state["info_breaker"]

    def test_is_open_with_auto_reset_not_yet_due(self, tmp_cache_dir: Path):
        """Breaker should stay open if auto-reset time not reached."""
        # Trip with future auto-reset
        import src.circuit_breaker
        breaker_state = {
            "test_breaker": {
                "state": "open",
                "tripped_at": datetime.utcnow().isoformat(),
                "reason": "Future reset",
                "auto_reset_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            }
        }
        src.circuit_breaker.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        src.circuit_breaker.STATE_FILE.write_text(
            json.dumps(breaker_state, indent=2), encoding="utf-8"
        )
        assert is_open("test_breaker")

    def test_is_open_with_auto_reset_due(self, tmp_cache_dir: Path):
        """Breaker should auto-reset when auto-reset time is reached."""
        import src.circuit_breaker
        # Trip with past auto-reset time
        breaker_state = {
            "expired_breaker": {
                "state": "open",
                "tripped_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                "reason": "Expired reset",
                "auto_reset_at": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            }
        }
        src.circuit_breaker.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        src.circuit_breaker.STATE_FILE.write_text(
            json.dumps(breaker_state, indent=2), encoding="utf-8"
        )
        assert not is_open("expired_breaker")

    def test_manual_reset_via_env(self, tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """BREAKER_RESET env var should clear specified breaker."""
        trip("env_reset_breaker", "Trip for env reset test")
        assert is_open("env_reset_breaker")

        monkeypatch.setenv("BREAKER_RESET", "env_reset_breaker")
        assert not is_open("env_reset_breaker")

    def test_manual_reset_multiple_names(self, tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """BREAKER_RESET should handle comma-separated names."""
        trip("breaker_a", "Trip A")
        trip("breaker_b", "Trip B")
        trip("breaker_c", "Trip C")

        monkeypatch.setenv("BREAKER_RESET", "breaker_a,breaker_b")

        # First call checks breaker_a (should be reset)
        assert not is_open("breaker_a")
        # Breaker c should still be open since it's not in BREAKER_RESET
        assert is_open("breaker_c")

    def test_state_file_invalid_json(self, tmp_cache_dir: Path):
        """_load should return empty dict on invalid JSON."""
        import src.circuit_breaker
        src.circuit_breaker.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        src.circuit_breaker.STATE_FILE.write_text("{ invalid json }", encoding="utf-8")

        assert not is_open("any_breaker")
