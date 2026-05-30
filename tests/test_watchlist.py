"""Tests for watchlist module."""
from __future__ import annotations
from pathlib import Path
import csv

import pytest

from src.models import WatchSource
from src import watchlist


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a sample watchlist CSV file."""
    csv_path = tmp_path / "watchlist.csv"
    fieldnames = list(WatchSource.model_fields.keys())
    rows = [
        {
            "id": "x_official_001",
            "name": "Nintendo Official",
            "handle": "@Nintendo",
            "url": "https://x.com/Nintendo",
            "platform": "X",
            "genre": "games",
            "source_type": "公式",
            "subcategory_hints": "Switch,Zelda",
            "priority": "high",
            "enabled": "TRUE",
            "check_frequency": "realtime",
            "language": "en",
            "notes": "Official Nintendo account",
        },
        {
            "id": "yt_ch_001",
            "name": "Tokyo Anime TV",
            "handle": "",
            "url": "https://www.youtube.com/c/TokyoAnimeTV",
            "platform": "YouTube",
            "genre": "anime",
            "source_type": "メディア",
            "subcategory_hints": "新作",
            "priority": "medium",
            "enabled": "TRUE",
            "check_frequency": "hourly",
            "language": "ja",
            "notes": "",
        },
        {
            "id": "x_personal_001",
            "name": "Game Streamer A",
            "handle": "@GameStreamerA",
            "url": "https://x.com/GameStreamerA",
            "platform": "X",
            "genre": "games",
            "source_type": "個人",
            "subcategory_hints": "",
            "priority": "low",
            "enabled": "FALSE",
            "check_frequency": "6h",
            "language": "ja",
            "notes": "Disabled for testing",
        },
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def test_parse_row_with_all_fields():
    """_parse_row should parse all CSV fields correctly."""
    row = {
        "id": "test_1",
        "name": "Test Source",
        "handle": "@testsource",
        "url": "https://example.com",
        "platform": "X",
        "genre": "games",
        "source_type": "メディア",
        "subcategory_hints": "hint1, hint2",
        "priority": "high",
        "enabled": "TRUE",
        "check_frequency": "realtime",
        "language": "en",
        "notes": "test notes",
    }

    source = watchlist._parse_row(row)

    assert source.id == "test_1"
    assert source.name == "Test Source"
    assert source.handle == "@testsource"
    assert source.platform == "X"
    assert source.genre == "games"
    assert source.enabled is True
    assert source.priority == "high"
    assert source.check_frequency == "realtime"
    assert source.language == "en"
    assert source.subcategory_hints == ["hint1", "hint2"]


def test_parse_row_with_defaults():
    """_parse_row should use defaults for missing optional fields."""
    row = {
        "id": "test_2",
        "name": "Minimal",
        "platform": "YouTube",
        "genre": "anime",
        "source_type": "公式",
    }

    source = watchlist._parse_row(row)

    assert source.id == "test_2"
    assert source.handle == ""
    assert source.url == ""
    assert source.priority == "medium"
    assert source.enabled is True
    assert source.check_frequency == "6h"
    assert source.language == "ja"
    assert source.subcategory_hints == []


def test_parse_row_enabled_variations():
    """_parse_row should handle various enabled string formats."""
    for enabled_str, expected in [
        ("TRUE", True),
        ("true", False),
        ("True", False),
        ("FALSE", False),
        ("false", False),
        ("1", True),
        ("0", False),
        ("YES", True),
        ("NO", False),
    ]:
        row = {
            "id": f"test_{enabled_str}",
            "name": "Test",
            "platform": "X",
            "genre": "games",
            "source_type": "公式",
            "enabled": enabled_str,
        }
        source = watchlist._parse_row(row)
        assert source.enabled == expected, f"enabled={enabled_str} should be {expected}"


def test_load_from_csv(sample_csv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_from_csv should parse all rows from CSV file."""
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", sample_csv)

    sources = watchlist._load_from_csv(sample_csv)

    assert len(sources) == 3
    assert sources[0].id == "x_official_001"
    assert sources[0].platform == "X"
    assert sources[1].id == "yt_ch_001"
    assert sources[2].enabled is False


def test_load_from_csv_not_found() -> None:
    """_load_from_csv should return empty list if file not found."""
    non_existent = Path("/nonexistent/watchlist.csv")
    sources = watchlist._load_from_csv(non_existent)
    assert sources == []


def test_source_to_csv_row():
    """_source_to_csv_row should convert WatchSource to CSV dict."""
    source = WatchSource(
        id="test",
        name="Test",
        handle="@test",
        url="https://example.com",
        platform="X",
        genre="games",
        source_type="メディア",
        subcategory_hints=["hint1", "hint2"],
        priority="high",
        enabled=True,
        check_frequency="realtime",
        language="ja",
        notes="test",
    )

    row = watchlist._source_to_csv_row(source)

    assert row["id"] == "test"
    assert row["subcategory_hints"] == "hint1,hint2"
    assert row["enabled"] == "TRUE"


def test_source_to_csv_row_disabled():
    """_source_to_csv_row should convert enabled=False to 'FALSE'."""
    source = WatchSource(
        id="disabled",
        name="Disabled",
        platform="YouTube",
        genre="anime",
        source_type="公式",
        enabled=False,
    )

    row = watchlist._source_to_csv_row(source)

    assert row["enabled"] == "FALSE"


def test_by_frequency_realtime():
    """by_frequency('realtime') should return only realtime sources."""
    sources = [
        WatchSource(
            id="real",
            name="Realtime",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="realtime",
        ),
        WatchSource(
            id="hourly",
            name="Hourly",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="hourly",
        ),
        WatchSource(
            id="6h",
            name="6h",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="6h",
        ),
    ]

    result = watchlist.by_frequency(sources, "realtime")

    assert len(result) == 1
    assert result[0].id == "real"


def test_by_frequency_hourly():
    """by_frequency('hourly') should return realtime and hourly sources."""
    sources = [
        WatchSource(
            id="real",
            name="Realtime",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="realtime",
        ),
        WatchSource(
            id="hourly",
            name="Hourly",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="hourly",
        ),
        WatchSource(
            id="6h",
            name="6h",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="6h",
        ),
    ]

    result = watchlist.by_frequency(sources, "hourly")

    assert len(result) == 2
    assert {s.id for s in result} == {"real", "hourly"}


def test_by_frequency_6h():
    """by_frequency('6h') should return realtime, hourly, and 6h sources."""
    sources = [
        WatchSource(
            id="real",
            name="Realtime",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="realtime",
        ),
        WatchSource(
            id="hourly",
            name="Hourly",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="hourly",
        ),
        WatchSource(
            id="6h",
            name="6h",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="6h",
        ),
        WatchSource(
            id="daily",
            name="Daily",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="daily",
        ),
    ]

    result = watchlist.by_frequency(sources, "6h")

    assert len(result) == 3
    assert {s.id for s in result} == {"real", "hourly", "6h"}


def test_by_frequency_daily():
    """by_frequency('daily') should return all sources."""
    sources = [
        WatchSource(
            id="real",
            name="Realtime",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="realtime",
        ),
        WatchSource(
            id="daily",
            name="Daily",
            platform="X",
            genre="games",
            source_type="公式",
            check_frequency="daily",
        ),
    ]

    result = watchlist.by_frequency(sources, "daily")

    assert len(result) == 2


def test_load_filters_disabled(
    sample_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load() should filter out disabled sources."""
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", sample_csv)
    monkeypatch.setenv("SYNC_SHEETS_FROM_CSV", "false")

    sources = watchlist.load()

    assert len(sources) == 2
    assert all(s.enabled for s in sources)
    assert not any(s.id == "x_personal_001" for s in sources)


def test_load_skips_sheets_sync(
    sample_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load() should skip Sheets sync if SYNC_SHEETS_FROM_CSV is false."""
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", sample_csv)
    monkeypatch.setenv("SYNC_SHEETS_FROM_CSV", "false")

    sources = watchlist.load()

    assert len(sources) == 2
    assert sources[0].id == "x_official_001"
    assert sources[1].id == "yt_ch_001"
