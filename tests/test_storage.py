"""Test storage.py functions for atomic writes and JSONL operations."""
from __future__ import annotations
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.models import RawItem, ProcessedItem, Importance, Genre, SourceRole
from src.storage import (
    write_json_atomic,
    write_raw,
    read_raw,
    write_processed,
    read_processed,
    read_processed_range,
)


@pytest.fixture
def tmp_storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up temporary data directories and patch config."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import src.config
    monkeypatch.setattr(src.config, "raw_dir", lambda d: data_dir / "raw" / d)
    monkeypatch.setattr(src.config, "processed_dir", lambda d: data_dir / "processed" / d)

    return data_dir


class TestWriteJsonAtomic:
    """Test atomic JSON writing."""

    def test_write_json_atomic_creates_file(self, tmp_path: Path) -> None:
        """Verify atomic write creates valid JSON file."""
        target = tmp_path / "state.json"
        data = {"key": "value", "count": 42}

        write_json_atomic(target, data)

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == data

    def test_write_json_atomic_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Verify parent directories are created if missing."""
        target = tmp_path / "a" / "b" / "c" / "state.json"
        data = {"nested": True}

        write_json_atomic(target, data)

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == data

    def test_write_json_atomic_handles_unicode(self, tmp_path: Path) -> None:
        """Verify Unicode is correctly encoded."""
        target = tmp_path / "unicode.json"
        data = {"text": "日本語テキスト", "emoji": "🎮"}

        write_json_atomic(target, data)

        result = json.loads(target.read_text(encoding="utf-8"))
        assert result == data

    def test_write_json_atomic_overwrites_existing(self, tmp_path: Path) -> None:
        """Verify atomic write replaces existing file."""
        target = tmp_path / "state.json"
        target.write_text(json.dumps({"old": "data"}), encoding="utf-8")

        new_data = {"new": "data"}
        write_json_atomic(target, new_data)

        assert json.loads(target.read_text(encoding="utf-8")) == new_data


class TestRawItemStorage:
    """Test raw item write/read cycle."""

    @staticmethod
    def make_sample_raw_items() -> list[RawItem]:
        """Create sample RawItem instances for testing."""
        now = datetime(2026, 8, 1, 12, 0, 0)
        return [
            RawItem(
                source_id="test_source_1",
                platform="X",
                author="@testuser1",
                account_type="個人",
                text="Test post 1",
                url="https://x.com/test/1",
                timestamp=now,
            ),
            RawItem(
                source_id="test_source_2",
                platform="YouTube",
                author="Test Channel",
                account_type="公式",
                text="Test video",
                url="https://youtube.com/watch?v=test",
                timestamp=now + timedelta(hours=1),
            ),
        ]

    def test_write_raw_creates_jsonl(self, tmp_storage_dir: Path) -> None:
        """Verify raw items are written to JSONL file."""
        items = self.make_sample_raw_items()
        date_str = "2026-08-01"

        path = write_raw(date_str, "test_source_1", [items[0]])

        assert path.exists()
        assert path.suffix == ".jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["author"] == "@testuser1"

    def test_read_raw_retrieves_items(self, tmp_storage_dir: Path) -> None:
        """Verify raw items are correctly read back."""
        items = self.make_sample_raw_items()
        date_str = "2026-08-01"
        write_raw(date_str, "source_1", [items[0]])
        write_raw(date_str, "source_2", [items[1]])

        read_items = list(read_raw(date_str))

        assert len(read_items) == 2
        assert read_items[0].author == "@testuser1"
        assert read_items[1].author == "Test Channel"

    def test_read_raw_empty_directory(self, tmp_storage_dir: Path) -> None:
        """Verify read_raw handles missing directory gracefully."""
        read_items = list(read_raw("2026-08-02"))
        assert read_items == []

    def test_write_raw_appends(self, tmp_storage_dir: Path) -> None:
        """Verify subsequent writes append to the same file."""
        items = self.make_sample_raw_items()
        date_str = "2026-08-01"

        write_raw(date_str, "source_1", [items[0]])
        write_raw(date_str, "source_1", [items[1]])

        read_items = list(read_raw(date_str))
        assert len(read_items) == 2


class TestProcessedItemStorage:
    """Test processed item write/read cycle."""

    @staticmethod
    def make_sample_processed_items() -> list[ProcessedItem]:
        """Create sample ProcessedItem instances for testing."""
        now = datetime(2026, 8, 1, 12, 0, 0)
        return [
            ProcessedItem(
                source_id="test_source_1",
                raw_fingerprint="fp1",
                timestamp=now,
                title="Game Announcement",
                summary="New game announced",
                genre="games",
                importance="S",
                url="https://example.com/1",
                author="Official",
                source_role="公式",
                tags=[],
                risk_level="low",
                final_priority=100,
            ),
            ProcessedItem(
                source_id="test_source_2",
                raw_fingerprint="fp2",
                timestamp=now + timedelta(hours=1),
                title="Anime News",
                summary="New episode released",
                genre="anime",
                importance="A",
                url="https://example.com/2",
                author="News Site",
                source_role="メディア",
                tags=[],
                risk_level="low",
                final_priority=80,
            ),
        ]

    def test_write_processed_creates_jsonl(self, tmp_storage_dir: Path) -> None:
        """Verify processed items are written to JSONL."""
        items = self.make_sample_processed_items()
        date_str = "2026-08-01"

        path = write_processed(date_str, [items[0]])

        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["title"] == "Game Announcement"

    def test_read_processed_retrieves_items(self, tmp_storage_dir: Path) -> None:
        """Verify processed items are correctly read back."""
        items = self.make_sample_processed_items()
        date_str = "2026-08-01"
        write_processed(date_str, items)

        read_items = read_processed(date_str)

        assert len(read_items) == 2
        assert read_items[0].title == "Game Announcement"
        assert read_items[1].importance == "A"

    def test_read_processed_empty_file(self, tmp_storage_dir: Path) -> None:
        """Verify read_processed returns empty list when file doesn't exist."""
        result = read_processed("2026-08-02")
        assert result == []

    def test_read_processed_range_spans_dates(self, tmp_storage_dir: Path) -> None:
        """Verify read_processed_range correctly reads multiple dates."""
        items = self.make_sample_processed_items()
        write_processed("2026-08-01", [items[0]])
        write_processed("2026-08-02", [items[1]])

        start = datetime(2026, 8, 1, 0, 0, 0)
        end = datetime(2026, 8, 2, 23, 59, 59)
        read_items = read_processed_range(start, end)

        assert len(read_items) == 2

    def test_read_processed_range_single_date(self, tmp_storage_dir: Path) -> None:
        """Verify read_processed_range works with single date range."""
        items = self.make_sample_processed_items()
        write_processed("2026-08-01", items)

        start = datetime(2026, 8, 1, 0, 0, 0)
        end = datetime(2026, 8, 1, 23, 59, 59)
        read_items = read_processed_range(start, end)

        assert len(read_items) == 2

    def test_read_processed_range_with_gaps(self, tmp_storage_dir: Path) -> None:
        """Verify read_processed_range handles missing dates gracefully."""
        items = self.make_sample_processed_items()
        write_processed("2026-08-01", [items[0]])
        write_processed("2026-08-03", [items[1]])

        start = datetime(2026, 8, 1, 0, 0, 0)
        end = datetime(2026, 8, 03, 23, 59, 59)
        read_items = read_processed_range(start, end)

        assert len(read_items) == 2
