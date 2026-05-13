"""Tests for Pydantic data models."""
from __future__ import annotations
from datetime import datetime
from src.models import (
    WatchSource,
    RawItem,
    ProcessedItem,
    Flags,
    FilterResult,
    Genre,
)


def test_watch_source_valid():
    """WatchSource should validate with required fields."""
    source = WatchSource(
        id="test_1",
        name="Test Source",
        platform="X",
        genre="games",
        source_type="メディア",
    )
    assert source.id == "test_1"
    assert source.platform == "X"
    assert source.enabled is True
    assert source.check_frequency == "6h"


def test_watch_source_defaults():
    """WatchSource should provide sensible defaults."""
    source = WatchSource(
        id="test_2",
        name="Test",
        platform="YouTube",
        genre="anime",
        source_type="公式",
    )
    assert source.priority == "medium"
    assert source.language == "ja"
    assert source.handle == ""
    assert source.subcategory_hints == []


def test_raw_item_fingerprint_with_url():
    """RawItem.fingerprint should prefer URL over author|timestamp."""
    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="Hello",
        url="https://example.com/post/123",
        timestamp=datetime(2026, 5, 11, 10, 0, 0),
    )
    assert item.fingerprint == "https://example.com/post/123"


def test_raw_item_fingerprint_without_url():
    """RawItem.fingerprint should fallback to author|timestamp when no URL."""
    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="Hello",
        url="",
        timestamp=datetime(2026, 5, 11, 10, 0, 0),
    )
    expected = "user1|2026-05-11T10:00:00"
    assert item.fingerprint == expected


def test_flags_defaults():
    """Flags should provide appropriate defaults."""
    flags = Flags(source_role="公式")
    assert flags.speed == "通常"
    assert flags.spoiler == "なし"
    assert flags.language == "ja"
    assert flags.content_type == "text"
    assert flags.source_reliability == "公式確定"


def test_filter_result_creation():
    """FilterResult should accept required fields."""
    result = FilterResult(
        spam=False,
        genre="games",
        confidence=0.95,
    )
    assert result.spam is False
    assert result.genre == "games"
    assert result.confidence == 0.95
    assert result.reason == ""


def test_processed_item_creation():
    """ProcessedItem should accept all fields."""
    flags = Flags(source_role="メディア")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp123",
        timestamp=datetime(2026, 5, 11, 10, 0, 0),
        url="https://example.com",
        author="author1",
        genre="games",
        subcategory_id="cat_game_01",
        category_name="ゲーム発表",
        importance="A",
        summary="Summary",
        flags=flags,
        dedup_key="dedup_key_123",
    )
    assert item.source_id == "src1"
    assert item.importance == "A"
    assert item.genre == "games"
    assert item.risk_level == "low"
    assert item.final_priority == "C"


def test_genre_literal_validation():
    """Genre should only accept valid values."""
    source = WatchSource(
        id="test",
        name="Test",
        platform="X",
        genre="games",
        source_type="公式",
    )
    assert source.genre == "games"

    source2 = WatchSource(
        id="test",
        name="Test",
        platform="X",
        genre="both",
        source_type="公式",
    )
    assert source2.genre == "both"


def test_importance_values():
    """Processed items should accept all importance levels."""
    flags = Flags(source_role="公式")
    for importance in ["S", "A", "B", "C"]:
        item = ProcessedItem(
            source_id="src",
            raw_fingerprint="fp",
            timestamp=datetime.now(),
            url="",
            author="",
            genre="games",
            subcategory_id="cat",
            category_name="cat",
            importance=importance,
            summary="",
            flags=flags,
            dedup_key="key",
        )
        assert item.importance == importance
