"""Tests for JSONL-based storage module."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from src.models import RawItem, ProcessedItem, Flags
from src.storage import (
    write_raw,
    read_raw,
    write_processed,
    read_processed,
    read_processed_range,
)


class TestRawItemStorage:
    """Tests for raw item read/write operations."""

    def test_write_raw_creates_file(self, tmp_data_dirs: dict):
        """write_raw should create JSONL file with RawItem."""
        item = RawItem(
            source_id="test_source",
            platform="X",
            author="user1",
            account_type="個人",
            text="Test content",
            url="https://example.com/post/1",
            timestamp=datetime(2026, 5, 12, 10, 30, 0),
        )
        path = write_raw("2026-05-12", "test_source", [item])
        assert path.exists()
        assert path.name == "test_source.jsonl"

    def test_write_raw_appends_multiple(self, tmp_data_dirs: dict):
        """write_raw should append multiple items to same file."""
        item1 = RawItem(
            source_id="src1",
            platform="X",
            author="user1",
            account_type="個人",
            text="Content 1",
            url="",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
        )
        item2 = RawItem(
            source_id="src1",
            platform="X",
            author="user2",
            account_type="公式",
            text="Content 2",
            url="https://example.com",
            timestamp=datetime(2026, 5, 12, 11, 0, 0),
        )
        path = write_raw("2026-05-12", "src1", [item1, item2])
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_read_raw_empty_directory(self, tmp_data_dirs: dict):
        """read_raw should return empty iterator for empty directory."""
        items = list(read_raw("2026-05-12"))
        assert items == []

    def test_read_raw_single_file(self, tmp_data_dirs: dict):
        """read_raw should deserialize RawItem from JSONL."""
        item = RawItem(
            source_id="src1",
            platform="YouTube",
            author="channel1",
            account_type="公式",
            text="Video description",
            url="https://youtube.com/watch?v=abc123",
            timestamp=datetime(2026, 5, 12, 14, 0, 0),
        )
        write_raw("2026-05-12", "src1", [item])
        items = list(read_raw("2026-05-12"))
        assert len(items) == 1
        assert items[0].source_id == "src1"
        assert items[0].platform == "YouTube"
        assert items[0].author == "channel1"

    def test_read_raw_multiple_files(self, tmp_data_dirs: dict):
        """read_raw should read from all .jsonl files in directory."""
        item1 = RawItem(
            source_id="src1",
            platform="X",
            author="user1",
            account_type="個人",
            text="Post 1",
            url="",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
        )
        item2 = RawItem(
            source_id="src2",
            platform="RSS",
            author="feed1",
            account_type="メディア",
            text="Article 1",
            url="https://example.com/article",
            timestamp=datetime(2026, 5, 12, 12, 0, 0),
        )
        write_raw("2026-05-12", "src1", [item1])
        write_raw("2026-05-12", "src2", [item2])
        items = list(read_raw("2026-05-12"))
        assert len(items) == 2
        assert items[0].source_id == "src1"
        assert items[1].source_id == "src2"


class TestProcessedItemStorage:
    """Tests for processed item read/write operations."""

    def test_write_processed_creates_file(self, tmp_data_dirs: dict):
        """write_processed should create items.jsonl file."""
        flags = Flags(source_role="メディア")
        item = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="A",
            summary="Test summary",
            flags=flags,
            dedup_key="key1",
        )
        path = write_processed("2026-05-12", [item])
        assert path.exists()
        assert path.name == "items.jsonl"

    def test_write_processed_appends(self, tmp_data_dirs: dict):
        """write_processed should append to existing items.jsonl."""
        flags = Flags(source_role="公式")
        item1 = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="A",
            summary="Summary 1",
            flags=flags,
            dedup_key="key1",
        )
        item2 = ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 12, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="cat_002",
            category_name="アニメ情報",
            importance="B",
            summary="Summary 2",
            flags=flags,
            dedup_key="key2",
        )
        write_processed("2026-05-12", [item1])
        write_processed("2026-05-12", [item2])
        items = read_processed("2026-05-12")
        assert len(items) == 2

    def test_read_processed_empty(self, tmp_data_dirs: dict):
        """read_processed should return empty list for non-existent date."""
        items = read_processed("2026-05-12")
        assert items == []

    def test_read_processed_single_date(self, tmp_data_dirs: dict):
        """read_processed should deserialize ProcessedItem from single date."""
        flags = Flags(source_role="個人")
        item = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="S",
            summary="High priority item",
            flags=flags,
            dedup_key="key1",
        )
        write_processed("2026-05-12", [item])
        items = read_processed("2026-05-12")
        assert len(items) == 1
        assert items[0].importance == "S"
        assert items[0].genre == "games"

    def test_read_processed_range_multiple_days(self, tmp_data_dirs: dict):
        """read_processed_range should aggregate across date range."""
        flags = Flags(source_role="公式")
        item1 = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 10, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="A",
            summary="Item from May 10",
            flags=flags,
            dedup_key="key1",
        )
        item2 = ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 11, 10, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="cat_002",
            category_name="アニメ情報",
            importance="B",
            summary="Item from May 11",
            flags=flags,
            dedup_key="key2",
        )
        item3 = ProcessedItem(
            source_id="src3",
            raw_fingerprint="fp3",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com/3",
            author="author3",
            genre="disney",
            subcategory_id="cat_003",
            category_name="Disney情報",
            importance="C",
            summary="Item from May 12",
            flags=flags,
            dedup_key="key3",
        )
        write_processed("2026-05-10", [item1])
        write_processed("2026-05-11", [item2])
        write_processed("2026-05-12", [item3])

        start = datetime(2026, 5, 10)
        end = datetime(2026, 5, 12)
        items = read_processed_range(start, end)
        assert len(items) == 3
        genres = {item.genre for item in items}
        assert genres == {"games", "anime", "disney"}

    def test_read_processed_range_single_day(self, tmp_data_dirs: dict):
        """read_processed_range should work with single day."""
        flags = Flags(source_role="公式")
        item = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="A",
            summary="Single day item",
            flags=flags,
            dedup_key="key1",
        )
        write_processed("2026-05-12", [item])

        start = datetime(2026, 5, 12)
        end = datetime(2026, 5, 12)
        items = read_processed_range(start, end)
        assert len(items) == 1
        assert items[0].source_id == "src1"

    def test_read_processed_range_empty(self, tmp_data_dirs: dict):
        """read_processed_range should return empty list for date range with no data."""
        start = datetime(2026, 5, 10)
        end = datetime(2026, 5, 15)
        items = read_processed_range(start, end)
        assert items == []

    def test_read_processed_range_skip_missing_days(self, tmp_data_dirs: dict):
        """read_processed_range should skip missing days in range."""
        flags = Flags(source_role="公式")
        item1 = ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 10, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="cat_001",
            category_name="ゲーム発表",
            importance="A",
            summary="Item 1",
            flags=flags,
            dedup_key="key1",
        )
        item2 = ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 12, 10, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="cat_002",
            category_name="アニメ情報",
            importance="B",
            summary="Item 2",
            flags=flags,
            dedup_key="key2",
        )
        write_processed("2026-05-10", [item1])
        write_processed("2026-05-12", [item2])

        start = datetime(2026, 5, 10)
        end = datetime(2026, 5, 12)
        items = read_processed_range(start, end)
        assert len(items) == 2
