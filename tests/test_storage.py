"""Tests for storage.py - JSONL file I/O operations."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime

import pytest

from src.models import RawItem, ProcessedItem, Genre, Importance, SourceRole, Flags
from src import storage


@pytest.fixture
def tmp_raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary raw data directory and patch config.raw_dir()."""
    raw_base = tmp_path / "raw"
    raw_base.mkdir()

    def mock_raw_dir(date_str: str) -> Path:
        day_dir = raw_base / date_str
        day_dir.mkdir(exist_ok=True)
        return day_dir

    import src.config
    monkeypatch.setattr(src.config, "raw_dir", mock_raw_dir)
    return raw_base


@pytest.fixture
def tmp_processed_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary processed data directory and patch config.processed_dir()."""
    proc_base = tmp_path / "processed"
    proc_base.mkdir()

    def mock_processed_dir(date_str: str) -> Path:
        day_dir = proc_base / date_str
        day_dir.mkdir(exist_ok=True)
        return day_dir

    import src.config
    monkeypatch.setattr(src.config, "processed_dir", mock_processed_dir)
    return proc_base


@pytest.fixture
def sample_raw_item() -> RawItem:
    """Provide a sample RawItem for testing."""
    return RawItem(
        source_id="test_source",
        platform="X",
        author="testuser",
        account_type=SourceRole.個人,
        text="Test content",
        url="https://example.com",
        timestamp=datetime(2026, 6, 27, 12, 0, 0),
        extra={"key": "value"},
    )


@pytest.fixture
def sample_processed_item() -> ProcessedItem:
    """Provide a sample ProcessedItem for testing."""
    return ProcessedItem(
        source_id="test_source",
        raw_fingerprint="test_fp_123",
        timestamp=datetime(2026, 6, 27, 12, 0, 0),
        url="https://example.com",
        author="testuser",
        genre=Genre.games,
        subcategory_id="action",
        category_name="Action Game",
        importance=Importance.A,
        summary="Test summary",
        title_tags=["tag1", "tag2"],
        entity_tags=["entity1"],
        flags=Flags(),
        dedup_key="test_key_123",
    )


class TestWriteRaw:
    """Tests for write_raw function."""

    def test_write_raw_single_item(
        self, tmp_raw_dir: Path, sample_raw_item: RawItem
    ) -> None:
        """Test writing a single raw item."""
        date_str = "2026-06-27"
        result = storage.write_raw(date_str, "test_source", [sample_raw_item])

        assert result.exists()
        assert result.name == "test_source.jsonl"
        assert result.parent.name == date_str

        lines = result.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

    def test_write_raw_multiple_items(
        self, tmp_raw_dir: Path, sample_raw_item: RawItem
    ) -> None:
        """Test writing multiple raw items."""
        date_str = "2026-06-27"
        items = [sample_raw_item, sample_raw_item]
        result = storage.write_raw(date_str, "test_source", items)

        lines = result.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_write_raw_append_mode(
        self, tmp_raw_dir: Path, sample_raw_item: RawItem
    ) -> None:
        """Test that write_raw appends to existing files."""
        date_str = "2026-06-27"
        storage.write_raw(date_str, "test_source", [sample_raw_item])
        storage.write_raw(date_str, "test_source", [sample_raw_item])

        path = tmp_raw_dir / date_str / "test_source.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2


class TestReadRaw:
    """Tests for read_raw function."""

    def test_read_raw_single_file(
        self, tmp_raw_dir: Path, sample_raw_item: RawItem
    ) -> None:
        """Test reading raw items from a single file."""
        date_str = "2026-06-27"
        storage.write_raw(date_str, "source_a", [sample_raw_item])

        items = list(storage.read_raw(date_str))
        assert len(items) == 1
        assert items[0].source_id == "test_source"

    def test_read_raw_multiple_files(
        self, tmp_raw_dir: Path, sample_raw_item: RawItem
    ) -> None:
        """Test reading raw items from multiple files."""
        date_str = "2026-06-27"
        storage.write_raw(date_str, "source_a", [sample_raw_item])

        # Create a second item with different source
        item2 = RawItem(
            source_id="test_source2",
            platform="YouTube",
            author="testuser2",
            account_type=SourceRole.公式,
            text="Test content 2",
            url="https://example2.com",
            timestamp=datetime(2026, 6, 27, 12, 0, 0),
        )
        storage.write_raw(date_str, "source_b", [item2])

        items = list(storage.read_raw(date_str))
        assert len(items) == 2

    def test_read_raw_empty_directory(self, tmp_raw_dir: Path) -> None:
        """Test reading from a non-existent date returns empty."""
        items = list(storage.read_raw("2026-01-01"))
        assert len(items) == 0

    def test_read_raw_skips_empty_lines(self, tmp_raw_dir: Path) -> None:
        """Test that read_raw skips empty lines."""
        date_str = "2026-06-27"
        day_dir = tmp_raw_dir / date_str
        day_dir.mkdir(exist_ok=True)

        # Write a file with empty lines
        file_path = day_dir / "test.jsonl"
        file_path.write_text('{"source_id": "test"}\n\n\n', encoding="utf-8")

        items = list(storage.read_raw(date_str))
        assert len(items) >= 1


class TestWriteProcessed:
    """Tests for write_processed function."""

    def test_write_processed_single_item(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test writing a single processed item."""
        date_str = "2026-06-27"
        result = storage.write_processed(date_str, [sample_processed_item])

        assert result.exists()
        assert result.name == "items.jsonl"
        assert result.parent.name == date_str

        lines = result.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

    def test_write_processed_multiple_items(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test writing multiple processed items."""
        date_str = "2026-06-27"
        items = [sample_processed_item, sample_processed_item]
        result = storage.write_processed(date_str, items)

        lines = result.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_write_processed_append_mode(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test that write_processed appends to existing files."""
        date_str = "2026-06-27"
        storage.write_processed(date_str, [sample_processed_item])
        storage.write_processed(date_str, [sample_processed_item])

        path = tmp_processed_dir / date_str / "items.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2


class TestReadProcessed:
    """Tests for read_processed function."""

    def test_read_processed_single_file(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test reading processed items."""
        date_str = "2026-06-27"
        storage.write_processed(date_str, [sample_processed_item])

        items = storage.read_processed(date_str)
        assert len(items) == 1
        assert items[0].source_id == "test_source"

    def test_read_processed_nonexistent_date(self, tmp_processed_dir: Path) -> None:
        """Test that read_processed returns empty list for nonexistent date."""
        items = storage.read_processed("2026-01-01")
        assert items == []

    def test_read_processed_type(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test that read_processed returns ProcessedItem instances."""
        date_str = "2026-06-27"
        storage.write_processed(date_str, [sample_processed_item])

        items = storage.read_processed(date_str)
        assert all(isinstance(item, ProcessedItem) for item in items)


class TestReadProcessedRange:
    """Tests for read_processed_range function."""

    def test_read_processed_range_single_day(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test reading processed items for a single day."""
        date_str = "2026-06-27"
        storage.write_processed(date_str, [sample_processed_item])

        start = datetime(2026, 6, 27, 0, 0, 0)
        end = datetime(2026, 6, 27, 23, 59, 59)
        items = storage.read_processed_range(start, end)
        assert len(items) == 1

    def test_read_processed_range_multiple_days(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test reading processed items across multiple days."""
        storage.write_processed("2026-06-26", [sample_processed_item])
        storage.write_processed("2026-06-27", [sample_processed_item])
        storage.write_processed("2026-06-28", [sample_processed_item])

        start = datetime(2026, 6, 26, 0, 0, 0)
        end = datetime(2026, 6, 28, 23, 59, 59)
        items = storage.read_processed_range(start, end)
        assert len(items) == 3

    def test_read_processed_range_no_data(self, tmp_processed_dir: Path) -> None:
        """Test reading empty range."""
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 31, 23, 59, 59)
        items = storage.read_processed_range(start, end)
        assert items == []

    def test_read_processed_range_partial_overlap(
        self, tmp_processed_dir: Path, sample_processed_item: ProcessedItem
    ) -> None:
        """Test reading range that partially overlaps with available data."""
        storage.write_processed("2026-06-27", [sample_processed_item])
        storage.write_processed("2026-06-28", [sample_processed_item])

        start = datetime(2026, 6, 26, 0, 0, 0)
        end = datetime(2026, 6, 27, 23, 59, 59)
        items = storage.read_processed_range(start, end)
        assert len(items) == 1
