"""Tests for src.timeutil — UTC time helpers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.timeutil import parse_utc, utc_now


class TestUtcNow:
    """Tests for utc_now()."""

    def test_returns_datetime(self) -> None:
        """utc_now() returns a datetime object."""
        result = utc_now()
        assert isinstance(result, datetime)

    def test_returns_tz_aware(self) -> None:
        """utc_now() returns a tz-aware datetime."""
        result = utc_now()
        assert result.tzinfo is not None

    def test_returns_utc_timezone(self) -> None:
        """utc_now() returns datetime in UTC timezone."""
        result = utc_now()
        assert result.tzinfo == timezone.utc

    def test_returns_current_time(self) -> None:
        """utc_now() returns approximately current time."""
        before = datetime.now(timezone.utc)
        result = utc_now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_multiple_calls_increase(self) -> None:
        """Multiple calls to utc_now() return increasing times."""
        time1 = utc_now()
        time2 = utc_now()
        assert time2 >= time1


class TestParseUtc:
    """Tests for parse_utc()."""

    def test_parse_tz_aware_iso_string(self) -> None:
        """parse_utc() handles tz-aware ISO strings."""
        result = parse_utc("2026-10-03T12:00:00+00:00")
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 3
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0
        assert result.tzinfo == timezone.utc

    def test_parse_tz_naive_iso_string(self) -> None:
        """parse_utc() converts tz-naive ISO strings to UTC."""
        result = parse_utc("2026-10-03T12:00:00")
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 3
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0
        assert result.tzinfo == timezone.utc

    def test_parse_iso_with_microseconds_tz_aware(self) -> None:
        """parse_utc() handles ISO strings with microseconds (tz-aware)."""
        result = parse_utc("2026-10-03T12:00:00.123456+00:00")
        assert result.microsecond == 123456
        assert result.tzinfo == timezone.utc

    def test_parse_iso_with_microseconds_tz_naive(self) -> None:
        """parse_utc() handles ISO strings with microseconds (tz-naive)."""
        result = parse_utc("2026-10-03T12:00:00.123456")
        assert result.microsecond == 123456
        assert result.tzinfo == timezone.utc

    def test_parse_different_utc_offset_formats(self) -> None:
        """parse_utc() accepts various UTC offset formats."""
        # Z suffix
        result1 = parse_utc("2026-10-03T12:00:00Z")
        assert result1.tzinfo is not None
        assert result1.tzinfo.utcoffset(result1) is not None

        # +00:00 format
        result2 = parse_utc("2026-10-03T12:00:00+00:00")
        assert result2.tzinfo is not None

    def test_parse_midnight(self) -> None:
        """parse_utc() correctly parses midnight."""
        result = parse_utc("2026-10-03T00:00:00")
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0

    def test_parse_end_of_day(self) -> None:
        """parse_utc() correctly parses end of day."""
        result = parse_utc("2026-10-03T23:59:59")
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59

    def test_parse_leap_year_date(self) -> None:
        """parse_utc() correctly parses leap year dates."""
        # 2024 is a leap year
        result = parse_utc("2024-02-29T12:00:00")
        assert result.month == 2
        assert result.day == 29

    def test_parse_invalid_format_raises(self) -> None:
        """parse_utc() raises ValueError for invalid format."""
        with pytest.raises(ValueError):
            parse_utc("not-a-date")

    def test_parse_invalid_date_raises(self) -> None:
        """parse_utc() raises ValueError for invalid date."""
        with pytest.raises(ValueError):
            parse_utc("2026-13-01T12:00:00")

    def test_parse_roundtrip_tz_aware(self) -> None:
        """parse_utc() roundtrips tz-aware ISO strings correctly."""
        original = utc_now()
        iso_str = original.isoformat()
        parsed = parse_utc(iso_str)
        # Compare up to microsecond precision (isoformat() includes them)
        assert parsed.year == original.year
        assert parsed.month == original.month
        assert parsed.day == original.day
        assert parsed.hour == original.hour
        assert parsed.minute == original.minute
        assert parsed.second == original.second
        assert abs((parsed - original).total_seconds()) < 0.001

    def test_parse_roundtrip_tz_naive_becomes_utc(self) -> None:
        """Parsing tz-naive ISO string makes it tz-aware UTC."""
        original = utc_now()
        # Create tz-naive version (remove tzinfo but keep the time values)
        naive_str = original.replace(tzinfo=None).isoformat()
        parsed = parse_utc(naive_str)
        assert parsed.tzinfo == timezone.utc
        assert parsed.year == original.year
        assert parsed.month == original.month
