"""Tests for JSONL storage module."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from src.models import RawItem, ProcessedItem, Flags
from src import storage
from src import config


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary data directory and patch config functions."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    # Patch config.raw_dir and config.processed_dir to use tmp_data_dir
    def mock_raw_dir(date_str: str):
        p = data_dir / "raw" / date_str
        p.mkdir(parents=True, exist_ok=True)
        return p

    def mock_processed_dir(date_str: str):
        p = data_dir / "processed" / date_str
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(config, "raw_dir", mock_raw_dir)
    monkeypatch.setattr(config, "processed_dir", mock_processed_dir)
    monkeypatch.setattr(storage, "raw_dir", mock_raw_dir)
    monkeypatch.setattr(storage, "processed_dir", mock_processed_dir)

    return data_dir


def test_write_raw_single_item(tmp_data_dir: Path):
    """write_raw should append a single RawItem to a JSONL file."""
    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="test content",
        url="https://example.com/1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
    )

    path = storage.write_raw("2026-05-16", "src1", [item])

    assert path.exists()
    assert path.name == "src1.jsonl"
    assert path.parent.name == "2026-05-16"

    # Verify the content
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_write_raw_multiple_items(tmp_data_dir: Path):
    """write_raw should handle multiple items."""
    items = [
        RawItem(
            source_id="src1",
            platform="X",
            author="user1",
            account_type="個人",
            text="content 1",
            url="https://example.com/1",
            timestamp=datetime(2026, 5, 16, 12, 0, 0),
        ),
        RawItem(
            source_id="src1",
            platform="X",
            author="user2",
            account_type="公式",
            text="content 2",
            url="https://example.com/2",
            timestamp=datetime(2026, 5, 16, 12, 30, 0),
        ),
    ]

    path = storage.write_raw("2026-05-16", "src1", items)

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_write_raw_append_mode(tmp_data_dir: Path):
    """write_raw should append to existing file."""
    item1 = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="content 1",
        url="https://example.com/1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
    )
    item2 = RawItem(
        source_id="src1",
        platform="X",
        author="user2",
        account_type="公式",
        text="content 2",
        url="https://example.com/2",
        timestamp=datetime(2026, 5, 16, 12, 30, 0),
    )

    storage.write_raw("2026-05-16", "src1", [item1])
    storage.write_raw("2026-05-16", "src1", [item2])

    path = tmp_data_dir / "raw" / "2026-05-16" / "src1.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_read_raw_empty_directory(tmp_data_dir: Path):
    """read_raw should return empty iterator when directory is empty."""
    items = list(storage.read_raw("2026-05-16"))
    assert items == []


def test_read_raw_single_file(tmp_data_dir: Path):
    """read_raw should read items from a single JSONL file."""
    items = [
        RawItem(
            source_id="src1",
            platform="X",
            author="user1",
            account_type="個人",
            text="content 1",
            url="https://example.com/1",
            timestamp=datetime(2026, 5, 16, 12, 0, 0),
        ),
        RawItem(
            source_id="src1",
            platform="X",
            author="user2",
            account_type="公式",
            text="content 2",
            url="https://example.com/2",
            timestamp=datetime(2026, 5, 16, 12, 30, 0),
        ),
    ]
    storage.write_raw("2026-05-16", "src1", items)

    read_items = list(storage.read_raw("2026-05-16"))
    assert len(read_items) == 2
    assert read_items[0].author == "user1"
    assert read_items[1].author == "user2"


def test_read_raw_multiple_files(tmp_data_dir: Path):
    """read_raw should read from multiple JSONL files in sorted order."""
    item1 = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="content 1",
        url="https://example.com/1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
    )
    item2 = RawItem(
        source_id="src2",
        platform="YouTube",
        author="channel1",
        account_type="公式",
        text="content 2",
        url="https://example.com/2",
        timestamp=datetime(2026, 5, 16, 12, 30, 0),
    )

    storage.write_raw("2026-05-16", "src1", [item1])
    storage.write_raw("2026-05-16", "src2", [item2])

    read_items = list(storage.read_raw("2026-05-16"))
    assert len(read_items) == 2
    # src1 should come before src2 (sorted)
    assert read_items[0].source_id == "src1"
    assert read_items[1].source_id == "src2"


def test_read_raw_with_blank_lines(tmp_data_dir: Path):
    """read_raw should skip blank lines."""
    raw_dir = tmp_data_dir / "raw" / "2026-05-16"
    raw_dir.mkdir(parents=True, exist_ok=True)

    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="content",
        url="https://example.com/1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
    )

    # Manually write with blank lines
    path = raw_dir / "src1.jsonl"
    path.write_text(item.model_dump_json() + "\n\n" + item.model_dump_json() + "\n", encoding="utf-8")

    read_items = list(storage.read_raw("2026-05-16"))
    assert len(read_items) == 2


def test_write_processed_single_item(tmp_data_dir: Path):
    """write_processed should write ProcessedItem to JSONL."""
    flags = Flags(source_role="公式")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="games",
        subcategory_id="cat1",
        category_name="アクション",
        importance="A",
        summary="Summary text",
        flags=flags,
        dedup_key="key1",
    )

    path = storage.write_processed("2026-05-16", [item])

    assert path.exists()
    assert path.name == "items.jsonl"
    assert path.parent.name == "2026-05-16"

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_write_processed_multiple_items(tmp_data_dir: Path):
    """write_processed should handle multiple items."""
    flags = Flags(source_role="メディア")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 16, 12, 0, 0),
            url="https://example.com/1",
            author="user1",
            genre="anime",
            subcategory_id="cat1",
            category_name="新作発表",
            importance="S",
            summary="Summary 1",
            flags=flags,
            dedup_key="key1",
        ),
        ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 16, 12, 30, 0),
            url="https://example.com/2",
            author="user2",
            genre="disney",
            subcategory_id="cat2",
            category_name="映画公開",
            importance="B",
            summary="Summary 2",
            flags=flags,
            dedup_key="key2",
        ),
    ]

    path = storage.write_processed("2026-05-16", items)

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_write_processed_append_mode(tmp_data_dir: Path):
    """write_processed should append to existing file."""
    flags = Flags(source_role="個人")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="both",
        subcategory_id="cat1",
        category_name="News",
        importance="C",
        summary="Summary 1",
        flags=flags,
        dedup_key="key1",
    )
    item2 = ProcessedItem(
        source_id="src2",
        raw_fingerprint="fp2",
        timestamp=datetime(2026, 5, 16, 12, 30, 0),
        url="https://example.com/2",
        author="user2",
        genre="games",
        subcategory_id="cat2",
        category_name="News",
        importance="A",
        summary="Summary 2",
        flags=flags,
        dedup_key="key2",
    )

    storage.write_processed("2026-05-16", [item1])
    storage.write_processed("2026-05-16", [item2])

    path = tmp_data_dir / "processed" / "2026-05-16" / "items.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_read_processed_empty_directory(tmp_data_dir: Path):
    """read_processed should return empty list when file doesn't exist."""
    items = storage.read_processed("2026-05-16")
    assert items == []


def test_read_processed_single_file(tmp_data_dir: Path):
    """read_processed should read ProcessedItem from JSONL."""
    flags = Flags(source_role="リーカー")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 16, 12, 0, 0),
            url="https://example.com/1",
            author="user1",
            genre="games",
            subcategory_id="cat1",
            category_name="Info",
            importance="S",
            summary="Summary 1",
            flags=flags,
            dedup_key="key1",
        ),
        ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 16, 12, 30, 0),
            url="https://example.com/2",
            author="user2",
            genre="anime",
            subcategory_id="cat2",
            category_name="Info",
            importance="B",
            summary="Summary 2",
            flags=flags,
            dedup_key="key2",
        ),
    ]
    storage.write_processed("2026-05-16", items)

    read_items = storage.read_processed("2026-05-16")
    assert len(read_items) == 2
    assert read_items[0].author == "user1"
    assert read_items[1].author == "user2"
    assert read_items[0].importance == "S"
    assert read_items[1].importance == "B"


def test_read_processed_with_blank_lines(tmp_data_dir: Path):
    """read_processed should skip blank lines."""
    processed_dir = tmp_data_dir / "processed" / "2026-05-16"
    processed_dir.mkdir(parents=True, exist_ok=True)

    flags = Flags(source_role="大会")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="games",
        subcategory_id="cat1",
        category_name="Tournament",
        importance="A",
        summary="Summary",
        flags=flags,
        dedup_key="key1",
    )

    # Manually write with blank lines
    path = processed_dir / "items.jsonl"
    path.write_text(item.model_dump_json() + "\n\n" + item.model_dump_json() + "\n", encoding="utf-8")

    read_items = storage.read_processed("2026-05-16")
    assert len(read_items) == 2


def test_read_processed_range_single_day(tmp_data_dir: Path):
    """read_processed_range should read from a single day when start == end."""
    flags = Flags(source_role="VTuber")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="games",
        subcategory_id="cat1",
        category_name="VTuber News",
        importance="B",
        summary="Summary",
        flags=flags,
        dedup_key="key1",
    )
    storage.write_processed("2026-05-16", [item])

    start = datetime(2026, 5, 16)
    end = datetime(2026, 5, 16)
    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 1
    assert read_items[0].author == "user1"


def test_read_processed_range_multiple_days(tmp_data_dir: Path):
    """read_processed_range should read from multiple days."""
    flags = Flags(source_role="メディア")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 15, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="anime",
        subcategory_id="cat1",
        category_name="News",
        importance="A",
        summary="Summary 1",
        flags=flags,
        dedup_key="key1",
    )
    item2 = ProcessedItem(
        source_id="src2",
        raw_fingerprint="fp2",
        timestamp=datetime(2026, 5, 16, 12, 0, 0),
        url="https://example.com/2",
        author="user2",
        genre="games",
        subcategory_id="cat2",
        category_name="News",
        importance="S",
        summary="Summary 2",
        flags=flags,
        dedup_key="key2",
    )
    item3 = ProcessedItem(
        source_id="src3",
        raw_fingerprint="fp3",
        timestamp=datetime(2026, 5, 17, 12, 0, 0),
        url="https://example.com/3",
        author="user3",
        genre="disney",
        subcategory_id="cat3",
        category_name="News",
        importance="C",
        summary="Summary 3",
        flags=flags,
        dedup_key="key3",
    )

    storage.write_processed("2026-05-15", [item1])
    storage.write_processed("2026-05-16", [item2])
    storage.write_processed("2026-05-17", [item3])

    start = datetime(2026, 5, 15)
    end = datetime(2026, 5, 17)
    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 3
    assert read_items[0].author == "user1"
    assert read_items[1].author == "user2"
    assert read_items[2].author == "user3"


def test_read_processed_range_with_gaps(tmp_data_dir: Path):
    """read_processed_range should handle missing days in the range."""
    flags = Flags(source_role="公式")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 5, 15, 12, 0, 0),
        url="https://example.com/1",
        author="user1",
        genre="games",
        subcategory_id="cat1",
        category_name="News",
        importance="A",
        summary="Summary 1",
        flags=flags,
        dedup_key="key1",
    )
    item2 = ProcessedItem(
        source_id="src3",
        raw_fingerprint="fp3",
        timestamp=datetime(2026, 5, 17, 12, 0, 0),
        url="https://example.com/3",
        author="user3",
        genre="anime",
        subcategory_id="cat3",
        category_name="News",
        importance="B",
        summary="Summary 3",
        flags=flags,
        dedup_key="key3",
    )

    storage.write_processed("2026-05-15", [item1])
    storage.write_processed("2026-05-17", [item2])

    start = datetime(2026, 5, 15)
    end = datetime(2026, 5, 17)
    read_items = storage.read_processed_range(start, end)

    # Should only get items from days that exist
    assert len(read_items) == 2
    assert read_items[0].author == "user1"
    assert read_items[1].author == "user3"


def test_roundtrip_raw(tmp_data_dir: Path):
    """write_raw and read_raw should roundtrip correctly."""
    original_items = [
        RawItem(
            source_id="src1",
            platform="Twitch",
            author="streamer1",
            account_type="個人",
            text="stream announce",
            url="https://twitch.tv/1",
            timestamp=datetime(2026, 5, 16, 14, 30, 0),
            extra={"duration": 120},
        ),
        RawItem(
            source_id="src2",
            platform="RSS",
            author="blog",
            account_type="メディア",
            text="blog post",
            url="https://blog.example.com/post1",
            timestamp=datetime(2026, 5, 16, 15, 0, 0),
            extra={"category": "tech"},
        ),
    ]

    storage.write_raw("2026-05-16", "src1", [original_items[0]])
    storage.write_raw("2026-05-16", "src2", [original_items[1]])

    read_items = list(storage.read_raw("2026-05-16"))

    assert len(read_items) == 2
    assert read_items[0].source_id == original_items[0].source_id
    assert read_items[0].platform == original_items[0].platform
    assert read_items[0].author == original_items[0].author
    assert read_items[0].extra == original_items[0].extra
    assert read_items[1].extra == original_items[1].extra


def test_roundtrip_processed(tmp_data_dir: Path):
    """write_processed and read_processed should roundtrip correctly."""
    flags = Flags(
        source_role="リーカー",
        speed="速報",
        spoiler="軽微",
        language="en",
        content_type="video",
    )
    original_item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_complex_1",
        timestamp=datetime(2026, 5, 16, 16, 45, 30),
        url="https://example.com/video/123",
        author="creator_name",
        genre="both",
        subcategory_id="subcat_123",
        category_name="新作アニメ＆ゲーム発表",
        importance="S",
        summary="New anime and game collaboration announced",
        title_tags=["新作", "アニメ", "ゲーム"],
        entity_tags=["Studio A", "Developer B"],
        flags=flags,
        dedup_key="dedup_key_complex",
        raw_text="Original raw text here",
        risk_level="high",
        streamer_influence_score=85,
        clip_virality_score=72,
        game_trend_from_streamers_score=68,
    )

    storage.write_processed("2026-05-16", [original_item])
    read_items = storage.read_processed("2026-05-16")

    assert len(read_items) == 1
    read_item = read_items[0]

    assert read_item.source_id == original_item.source_id
    assert read_item.category_name == original_item.category_name
    assert read_item.importance == original_item.importance
    assert read_item.genre == original_item.genre
    assert read_item.flags.speed == original_item.flags.speed
    assert read_item.streamer_influence_score == original_item.streamer_influence_score
    assert read_item.title_tags == original_item.title_tags
