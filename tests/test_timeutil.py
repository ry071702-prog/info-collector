"""Tests for UTC time utilities."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.timeutil import parse_utc, utc_now


def test_utc_now_is_tz_aware():
    """utc_now() returns a tz-aware UTC datetime."""
    now = utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


def test_utc_now_is_recent():
    """utc_now() returns a current time (roughly)."""
    before = datetime.now(timezone.utc)
    now = utc_now()
    after = datetime.now(timezone.utc)
    assert before <= now <= after


def test_parse_utc_with_offset():
    """parse_utc() parses ISO string with timezone offset."""
    result = parse_utc("2026-09-26T12:00:00+00:00")
    assert result == datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_parse_utc_with_different_offset():
    """parse_utc() preserves non-UTC timezone info."""
    # Parse a string with +09:00 offset (JST)
    result = parse_utc("2026-09-26T12:00:00+09:00")
    # Should preserve the original offset
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 9 * 3600  # type: ignore


def test_parse_utc_naive_treated_as_utc():
    """parse_utc() treats tz-naive strings as UTC (legacy compatibility)."""
    # Old cache values from datetime.utcnow().isoformat() have no tz info
    result = parse_utc("2026-09-26T12:00:00")
    assert result == datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


def test_parse_utc_roundtrip_from_utc_now():
    """parse_utc() can round-trip a value from utc_now().isoformat()."""
    now = utc_now()
    iso_str = now.isoformat()
    parsed = parse_utc(iso_str)
    assert parsed == now
