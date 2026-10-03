"""Tests for storage operations (read/write raw and processed items)."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from src.models import RawItem, ProcessedItem, Flags
from src import storage


def test_write_and_read_raw(tmp_data_dir: Path):
    """write_raw and read_raw should handle items correctly."""
    items = [
        RawItem(
            source_id="test_x_1",
            platform="X",
            author="user1",
            account_type="個人",
            text="Test tweet 1",
            url="https://twitter.com/user1/status/123",
            timestamp=datetime(2026, 6, 5, 10, 0, 0),
        ),
        RawItem(
            source_id="test_x_1",
            platform="X",
            author="user2",
            account_type="公式",
            text="Test tweet 2",
            url="https://twitter.com/user2/status/124",
            timestamp=datetime(2026, 6, 5, 11, 0, 0),
        ),
    ]

    date_str = "2026-06-05"
    written_path = storage.write_raw(date_str, "test_x_1", items)
    assert written_path.exists()
    assert written_path.name == "test_x_1.jsonl"

    read_items = list(storage.read_raw(date_str))
    assert len(read_items) == 2
    assert read_items[0].text == "Test tweet 1"
    assert read_items[1].text == "Test tweet 2"


def test_read_raw_empty_directory(tmp_data_dir: Path):
    """read_raw should return empty iterator for non-existent date."""
    date_str = "2026-06-05"
    items = list(storage.read_raw(date_str))
    assert items == []


def test_write_raw_append(tmp_data_dir: Path):
    """Multiple write_raw calls should append to the same file."""
    date_str = "2026-06-05"
    source_id = "test_src"

    batch1 = [
        RawItem(
            source_id=source_id,
            platform="X",
            author="user1",
            account_type="個人",
            text="Batch 1",
            url="https://example.com/1",
            timestamp=datetime(2026, 6, 5, 10, 0, 0),
        )
    ]
    batch2 = [
        RawItem(
            source_id=source_id,
            platform="X",
            author="user2",
            account_type="公式",
            text="Batch 2",
            url="https://example.com/2",
            timestamp=datetime(2026, 6, 5, 11, 0, 0),
        )
    ]

    storage.write_raw(date_str, source_id, batch1)
    storage.write_raw(date_str, source_id, batch2)

    read_items = list(storage.read_raw(date_str))
    assert len(read_items) == 2
    assert read_items[0].text == "Batch 1"
    assert read_items[1].text == "Batch 2"


def test_write_and_read_processed(tmp_data_dir: Path):
    """write_processed and read_processed should handle items correctly."""
    flags = Flags(source_role="公式")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 6, 5, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="action",
            category_name="アクション",
            importance="A",
            summary="Good game news",
            flags=flags,
            dedup_key="key1",
        ),
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 6, 5, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="drama",
            category_name="ドラマ",
            importance="B",
            summary="Anime announcement",
            flags=flags,
            dedup_key="key2",
        ),
    ]

    date_str = "2026-06-05"
    written_path = storage.write_processed(date_str, items)
    assert written_path.exists()
    assert written_path.name == "items.jsonl"

    read_items = storage.read_processed(date_str)
    assert len(read_items) == 2
    assert read_items[0].summary == "Good game news"
    assert read_items[1].summary == "Anime announcement"
    assert read_items[0].importance == "A"
    assert read_items[1].importance == "B"


def test_read_processed_missing_file(tmp_data_dir: Path):
    """read_processed should return empty list for non-existent file."""
    date_str = "2026-06-05"
    items = storage.read_processed(date_str)
    assert items == []


def test_write_processed_append(tmp_data_dir: Path):
    """Multiple write_processed calls should append to the same file."""
    flags = Flags(source_role="メディア")
    date_str = "2026-06-05"

    batch1 = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 6, 5, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="action",
            category_name="アクション",
            importance="A",
            summary="First batch",
            flags=flags,
            dedup_key="key1",
        )
    ]
    batch2 = [
        ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 6, 5, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="drama",
            category_name="ドラマ",
            importance="B",
            summary="Second batch",
            flags=flags,
            dedup_key="key2",
        )
    ]

    storage.write_processed(date_str, batch1)
    storage.write_processed(date_str, batch2)

    read_items = storage.read_processed(date_str)
    assert len(read_items) == 2
    assert read_items[0].summary == "First batch"
    assert read_items[1].summary == "Second batch"


def test_read_processed_range(tmp_data_dir: Path):
    """read_processed_range should read from multiple dates."""
    flags = Flags(source_role="個人")

    dates = ["2026-06-03", "2026-06-04", "2026-06-05"]
    for i, date_str in enumerate(dates):
        items = [
            ProcessedItem(
                source_id=f"src{i}",
                raw_fingerprint=f"fp{i}",
                timestamp=datetime.fromisoformat(f"{date_str}T10:00:00"),
                url=f"https://example.com/{i}",
                author=f"author{i}",
                genre="games",
                subcategory_id="rpg",
                category_name="RPG",
                importance="B",
                summary=f"Item from {date_str}",
                flags=flags,
                dedup_key=f"key{i}",
            )
        ]
        storage.write_processed(date_str, items)

    start = datetime(2026, 6, 3, 0, 0, 0)
    end = datetime(2026, 6, 5, 23, 59, 59)
    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 3
    summaries = [item.summary for item in read_items]
    assert "Item from 2026-06-03" in summaries
    assert "Item from 2026-06-04" in summaries
    assert "Item from 2026-06-05" in summaries


def test_read_processed_range_partial(tmp_data_dir: Path):
    """read_processed_range should handle partial date ranges."""
    flags = Flags(source_role="リーカー")

    for i, date_str in enumerate(["2026-06-03", "2026-06-04", "2026-06-05"]):
        items = [
            ProcessedItem(
                source_id=f"src{i}",
                raw_fingerprint=f"fp{i}",
                timestamp=datetime.fromisoformat(f"{date_str}T10:00:00"),
                url=f"https://example.com/{i}",
                author=f"author{i}",
                genre="anime",
                subcategory_id="comedy",
                category_name="コメディ",
                importance="C",
                summary=f"Date {date_str}",
                flags=flags,
                dedup_key=f"key{i}",
            )
        ]
        storage.write_processed(date_str, items)

    start = datetime(2026, 6, 4, 0, 0, 0)
    end = datetime(2026, 6, 5, 23, 59, 59)
    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 2
    assert all("2026-06-0[45]" in item.summary for item in read_items)


def test_raw_item_fingerprint_with_url():
    """RawItem.fingerprint should prefer URL when available."""
    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="Test",
        url="https://example.com/1",
        timestamp=datetime.now(),
    )
    assert item.fingerprint == "https://example.com/1"


def test_raw_item_fingerprint_without_url():
    """RawItem.fingerprint should use author+timestamp when URL is absent."""
    ts = datetime(2026, 6, 5, 10, 30, 45)
    item = RawItem(
        source_id="src1",
        platform="X",
        author="user1",
        account_type="個人",
        text="Test",
        url="",
        timestamp=ts,
    )
    assert item.fingerprint == f"user1|{ts.isoformat()}"
