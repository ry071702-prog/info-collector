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


def test_watch_source_disabled():
    """WatchSource should support disabled flag."""
    source = WatchSource(
        id="disabled_src",
        name="Disabled Source",
        platform="Twitch",
        genre="games",
        source_type="VTuber",
        enabled=False,
    )
    assert source.enabled is False


def test_raw_item_with_extra_data():
    """RawItem should accept and preserve extra metadata."""
    extra_data = {"view_count": 1000, "retweet_count": 50}
    item = RawItem(
        source_id="src2",
        platform="YouTube",
        author="channel1",
        account_type="公式",
        text="Video description",
        url="https://youtube.com/watch?v=abc123",
        timestamp=datetime(2026, 9, 19, 15, 30, 0),
        extra=extra_data,
    )
    assert item.extra == extra_data
    assert item.extra["view_count"] == 1000


def test_flags_cross_genre_options():
    """Flags should support all cross_genre combinations."""
    cross_genre_values = [
        "ゲーム単独",
        "アニメ単独",
        "Disney単独",
        "両方",
        "ゲーム+Disney",
        "アニメ+Disney",
        "その他",
    ]
    for genre in cross_genre_values:
        flags = Flags(source_role="個人", cross_genre=genre)
        assert flags.cross_genre == genre


def test_processed_item_scoring_fields():
    """ProcessedItem should accept all scoring fields."""
    flags = Flags(source_role="メディア")
    item = ProcessedItem(
        source_id="scored_src",
        raw_fingerprint="fp_scored",
        timestamp=datetime(2026, 9, 19, 12, 0, 0),
        url="https://example.com/article",
        author="news_outlet",
        genre="games",
        subcategory_id="cat_gamedebut",
        category_name="ゲーム新情報",
        importance="S",
        summary="Big announcement",
        flags=flags,
        dedup_key="dedup_scored",
        streamer_influence_score=85,
        clip_virality_score=72,
        game_trend_from_streamers_score=90,
        live_trend_score=65,
        video_trend_score=78,
        freshness_score=95,
        final_priority="A",
        risk_level="high",
        streamer_name="SHAKA",
        streamer_group="Crazy Raccoon",
        is_clip=True,
        related_game_title="Valorant",
    )
    assert item.streamer_influence_score == 85
    assert item.clip_virality_score == 72
    assert item.game_trend_from_streamers_score == 90
    assert item.live_trend_score == 65
    assert item.video_trend_score == 78
    assert item.freshness_score == 95
    assert item.final_priority == "A"
    assert item.risk_level == "high"
    assert item.streamer_name == "SHAKA"
    assert item.is_clip is True


def test_raw_item_fingerprint_empty_string_url():
    """RawItem.fingerprint should treat empty string URL as no URL."""
    item = RawItem(
        source_id="src3",
        platform="RSS",
        author="rss_feed",
        account_type="メディア",
        text="Article content",
        url="",
        timestamp=datetime(2026, 9, 19, 10, 15, 0),
    )
    expected = "rss_feed|2026-09-19T10:15:00"
    assert item.fingerprint == expected
