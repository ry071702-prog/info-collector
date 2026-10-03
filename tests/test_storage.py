"""Tests for src/storage.py (JSONL storage)."""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.models import RawItem, ProcessedItem, Flags
from src.storage import (
    write_json_atomic,
    write_raw,
    read_raw,
    write_processed,
    read_processed,
    read_processed_range,
)


@pytest.fixture
def tmp_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch config.raw_dir() and config.processed_dir() to use tmp_path."""
    raw_base = tmp_path / "raw"
    processed_base = tmp_path / "processed"
    raw_base.mkdir(parents=True)
    processed_base.mkdir(parents=True)

    import src.config

    def mock_raw_dir(date_str: str):
        return raw_base / date_str

    def mock_processed_dir(date_str: str):
        return processed_base / date_str

    monkeypatch.setattr(src.config, "raw_dir", mock_raw_dir)
    monkeypatch.setattr(src.config, "processed_dir", mock_processed_dir)
    return raw_base, processed_base


@pytest.fixture
def sample_raw_items():
    """Create sample RawItem objects."""
    return [
        RawItem(
            source_id="test_source_1",
            platform="X",
            author="author1",
            account_type="個人",
            text="test text 1",
            url="https://example.com/1",
            timestamp=datetime(2026, 8, 29, 10, 0, 0),
        ),
        RawItem(
            source_id="test_source_2",
            platform="YouTube",
            author="author2",
            account_type="公式",
            text="test text 2",
            url="https://example.com/2",
            timestamp=datetime(2026, 8, 29, 11, 0, 0),
        ),
    ]


@pytest.fixture
def sample_processed_items():
    """Create sample ProcessedItem objects."""
    flags = Flags(source_role="公式", content_type="video")
    return [
        ProcessedItem(
            source_id="test_source_1",
            raw_fingerprint="https://example.com/1",
            timestamp=datetime(2026, 8, 29, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="sub1",
            category_name="RPG",
            importance="A",
            summary="test summary 1",
            flags=flags,
            dedup_key="key1",
        ),
        ProcessedItem(
            source_id="test_source_2",
            raw_fingerprint="https://example.com/2",
            timestamp=datetime(2026, 8, 29, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="sub2",
            category_name="Action",
            importance="B",
            summary="test summary 2",
            flags=flags,
            dedup_key="key2",
        ),
    ]


class TestWriteJsonAtomic:
    """Test atomic JSON writing."""

    def test_write_json_atomic_creates_file(self, tmp_path: Path):
        """write_json_atomic should create a JSON file."""
        target = tmp_path / "test.json"
        data = {"key": "value", "nested": {"a": 1}}
        write_json_atomic(target, data)
        assert target.exists()
        assert json.loads(target.read_text()) == data

    def test_write_json_atomic_creates_parent_dirs(self, tmp_path: Path):
        """write_json_atomic should create parent directories."""
        target = tmp_path / "deep" / "nested" / "path" / "file.json"
        data = {"test": "data"}
        write_json_atomic(target, data)
        assert target.exists()
        assert json.loads(target.read_text()) == data

    def test_write_json_atomic_overwrites_existing(self, tmp_path: Path):
        """write_json_atomic should overwrite existing files."""
        target = tmp_path / "test.json"
        target.write_text('{"old": "data"}')
        new_data = {"new": "data"}
        write_json_atomic(target, new_data)
        assert json.loads(target.read_text()) == new_data

    def test_write_json_atomic_no_temp_file_on_success(self, tmp_path: Path):
        """No .tmp files should be left after successful write."""
        target = tmp_path / "test.json"
        write_json_atomic(target, {"data": "test"})
        tmp_files = list(tmp_path.glob(".test.json*.tmp"))
        assert len(tmp_files) == 0

    def test_write_json_atomic_handles_unicode(self, tmp_path: Path):
        """write_json_atomic should handle unicode correctly."""
        target = tmp_path / "unicode.json"
        data = {"ja": "日本語", "emoji": "🎮"}
        write_json_atomic(target, data)
        assert json.loads(target.read_text(encoding="utf-8")) == data


class TestRawStorage:
    """Test RawItem JSONL storage."""

    def test_write_read_raw(self, tmp_dirs, sample_raw_items):
        """write_raw and read_raw should round-trip RawItem objects."""
        date_str = "2026-08-29"
        write_raw(date_str, "source1", sample_raw_items)
        items = list(read_raw(date_str))
        assert len(items) == 2
        assert items[0].author == "author1"
        assert items[1].author == "author2"

    def test_write_multiple_sources(self, tmp_dirs, sample_raw_items):
        """write_raw from multiple sources should create separate files."""
        date_str = "2026-08-29"
        write_raw(date_str, "source1", [sample_raw_items[0]])
        write_raw(date_str, "source2", [sample_raw_items[1]])
        items = list(read_raw(date_str))
        assert len(items) == 2

    def test_read_raw_append_mode(self, tmp_dirs, sample_raw_items):
        """write_raw should append to existing files."""
        date_str = "2026-08-29"
        write_raw(date_str, "source1", [sample_raw_items[0]])
        write_raw(date_str, "source1", [sample_raw_items[1]])
        items = list(read_raw(date_str))
        assert len(items) == 2

    def test_read_raw_empty_dir(self, tmp_dirs):
        """read_raw should return empty for non-existent date."""
        items = list(read_raw("2026-12-31"))
        assert len(items) == 0

    def test_read_raw_preserves_extra_fields(self, tmp_dirs):
        """read_raw should preserve extra fields in RawItem."""
        date_str = "2026-08-29"
        item = RawItem(
            source_id="test",
            platform="X",
            author="user",
            account_type="個人",
            text="text",
            url="https://example.com",
            timestamp=datetime(2026, 8, 29, 10, 0, 0),
            extra={"custom_field": "custom_value"},
        )
        write_raw(date_str, "source1", [item])
        items = list(read_raw(date_str))
        assert items[0].extra == {"custom_field": "custom_value"}


class TestProcessedStorage:
    """Test ProcessedItem JSONL storage."""

    def test_write_read_processed(self, tmp_dirs, sample_processed_items):
        """write_processed and read_processed should round-trip items."""
        date_str = "2026-08-29"
        write_processed(date_str, sample_processed_items)
        items = read_processed(date_str)
        assert len(items) == 2
        assert items[0].importance == "A"
        assert items[1].importance == "B"

    def test_read_processed_nonexistent(self, tmp_dirs):
        """read_processed should return empty list for non-existent date."""
        items = read_processed("2026-12-31")
        assert items == []

    def test_read_processed_range(self, tmp_dirs, sample_processed_items):
        """read_processed_range should read multiple dates."""
        write_processed("2026-08-29", [sample_processed_items[0]])
        write_processed("2026-08-30", [sample_processed_items[1]])
        items = read_processed_range(
            datetime(2026, 8, 29, 0, 0, 0),
            datetime(2026, 8, 30, 23, 59, 59),
        )
        assert len(items) == 2

    def test_read_processed_range_single_day(self, tmp_dirs, sample_processed_items):
        """read_processed_range should handle single-day ranges."""
        write_processed("2026-08-29", sample_processed_items)
        items = read_processed_range(
            datetime(2026, 8, 29, 10, 0, 0),
            datetime(2026, 8, 29, 23, 59, 59),
        )
        assert len(items) == 2

    def test_read_processed_append_mode(self, tmp_dirs, sample_processed_items):
        """write_processed should append to existing files."""
        date_str = "2026-08-29"
        write_processed(date_str, [sample_processed_items[0]])
        write_processed(date_str, [sample_processed_items[1]])
        items = read_processed(date_str)
        assert len(items) == 2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_read_raw_with_blank_lines(self, tmp_dirs):
        """read_raw should skip blank lines in JSONL files."""
        date_str = "2026-08-29"
        raw_dir = tmp_dirs[0] / date_str
        raw_dir.mkdir(parents=True)
        file_path = raw_dir / "source1.jsonl"

        item = RawItem(
            source_id="test",
            platform="X",
            author="user",
            account_type="個人",
            text="text",
            url="https://example.com",
            timestamp=datetime(2026, 8, 29, 10, 0, 0),
        )
        # Write with blank lines
        file_path.write_text(
            item.model_dump_json() + "\n\n" + item.model_dump_json() + "\n"
        )
        items = list(read_raw(date_str))
        assert len(items) == 2

    def test_read_processed_with_blank_lines(self, tmp_dirs, sample_processed_items):
        """read_processed should skip blank lines in JSONL files."""
        date_str = "2026-08-29"
        processed_dir = tmp_dirs[1] / date_str
        processed_dir.mkdir(parents=True)
        file_path = processed_dir / "items.jsonl"

        item = sample_processed_items[0]
        file_path.write_text(
            item.model_dump_json() + "\n\n" + item.model_dump_json() + "\n"
        )
        items = read_processed(date_str)
        assert len(items) == 2
