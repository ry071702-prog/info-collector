"""Tests for UTC time utilities."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.timeutil import parse_utc, utc_now


class TestUtcNow:
    """Tests for utc_now()."""

    def test_utc_now_returns_timezone_aware(self) -> None:
        """utc_now() should return a timezone-aware datetime."""
        now = utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_utc_now_is_current(self) -> None:
        """utc_now() should return current time (within 1 second)."""
        before = datetime.now(timezone.utc)
        now = utc_now()
        after = datetime.now(timezone.utc)

        assert before <= now <= after


class TestParseUtc:
    """Tests for parse_utc()."""

    def test_parse_utc_naive_string(self) -> None:
        """parse_utc() should treat naive ISO strings as UTC."""
        iso_naive = "2026-03-15T12:34:56"
        parsed = parse_utc(iso_naive)

        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc
        assert parsed.year == 2026
        assert parsed.month == 3
        assert parsed.day == 15
        assert parsed.hour == 12
        assert parsed.minute == 34
        assert parsed.second == 56

    def test_parse_utc_aware_string_with_plus_offset(self) -> None:
        """parse_utc() should handle +00:00 offset strings."""
        iso_aware = "2026-03-15T12:34:56+00:00"
        parsed = parse_utc(iso_aware)

        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc
        assert parsed.year == 2026
        assert parsed.month == 3
        assert parsed.day == 15

    def test_parse_utc_aware_string_with_z_suffix(self) -> None:
        """parse_utc() should handle Z suffix (ISO 8601 UTC)."""
        iso_z = "2026-03-15T12:34:56Z"
        parsed = parse_utc(iso_z)

        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc
        assert parsed.year == 2026

    def test_parse_utc_naive_to_aware_equivalence(self) -> None:
        """Naive and aware UTC strings should represent the same moment."""
        iso_naive = "2026-03-15T12:34:56"
        iso_aware = "2026-03-15T12:34:56+00:00"

        parsed_naive = parse_utc(iso_naive)
        parsed_aware = parse_utc(iso_aware)

        assert parsed_naive == parsed_aware
        assert parsed_naive.tzinfo == parsed_aware.tzinfo
