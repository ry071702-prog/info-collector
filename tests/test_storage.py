"""Tests for JSONL-based storage operations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
from src.models import ProcessedItem, RawItem, Flags
from src import storage
from src import config as config_module


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary data directory and patch config."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    # Patch config functions to use our temporary directory
    def mock_raw_dir(date_str: str) -> Path:
        d = data_dir / "raw" / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d

    def mock_processed_dir(date_str: str) -> Path:
        d = data_dir / "processed" / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(config_module, "raw_dir", mock_raw_dir)
    monkeypatch.setattr(config_module, "processed_dir", mock_processed_dir)

    return data_dir


def test_write_atomic_creates_file(tmp_path: Path):
    """write_json_atomic should create a JSON file with proper formatting."""
    output_file = tmp_path / "test.json"
    data = {"key": "value", "number": 42}

    storage.write_json_atomic(output_file, data)

    assert output_file.exists()
    loaded = json.loads(output_file.read_text(encoding="utf-8"))
    assert loaded == data


def test_write_atomic_overwrites_existing_file(tmp_path: Path):
    """write_json_atomic should overwrite existing files atomically."""
    output_file = tmp_path / "test.json"
    old_data = {"old": "data"}
    new_data = {"new": "data"}

    storage.write_json_atomic(output_file, old_data)
    storage.write_json_atomic(output_file, new_data)

    loaded = json.loads(output_file.read_text(encoding="utf-8"))
    assert loaded == new_data


def test_write_atomic_creates_parent_dirs(tmp_path: Path):
    """write_json_atomic should create parent directories if needed."""
    output_file = tmp_path / "deep" / "nested" / "dir" / "test.json"
    data = {"nested": True}

    storage.write_json_atomic(output_file, data)

    assert output_file.exists()
    assert output_file.parent.exists()


def test_write_raw_creates_jsonl_file(tmp_data_dir: Path):
    """write_raw should append RawItem lines to JSONL file."""
    date_str = "2026-05-15"
    source_id = "test_source"
    items = [
        RawItem(
            source_id=source_id,
            content_id="id1",
            url="https://example.com/1",
            author="user1",
            timestamp=datetime.now(timezone.utc),
            raw_text="Text 1",
        ),
        RawItem(
            source_id=source_id,
            content_id="id2",
            url="https://example.com/2",
            author="user2",
            timestamp=datetime.now(timezone.utc),
            raw_text="Text 2",
        ),
    ]

    path = storage.write_raw(date_str, source_id, items)

    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    # Verify each line is valid JSON
    for line in lines:
        loaded = json.loads(line)
        assert "source_id" in loaded
        assert loaded["source_id"] == source_id


def test_read_raw_returns_all_items(tmp_data_dir: Path):
    """read_raw should return all RawItem objects from all source files."""
    date_str = "2026-05-15"
    items1 = [
        RawItem(
            source_id="src1",
            content_id="id1",
            url="https://example.com/1",
            author="user1",
            timestamp=datetime.now(timezone.utc),
            raw_text="Text 1",
        ),
    ]
    items2 = [
        RawItem(
            source_id="src2",
            content_id="id2",
            url="https://example.com/2",
            author="user2",
            timestamp=datetime.now(timezone.utc),
            raw_text="Text 2",
        ),
    ]

    storage.write_raw(date_str, "src1", items1)
    storage.write_raw(date_str, "src2", items2)

    read_items = list(storage.read_raw(date_str))

    assert len(read_items) == 2
    assert read_items[0].source_id == "src1"
    assert read_items[1].source_id == "src2"


def test_read_raw_empty_directory(tmp_data_dir: Path):
    """read_raw should return empty iterator for non-existent directory."""
    date_str = "2099-12-31"

    items = list(storage.read_raw(date_str))

    assert items == []


def test_write_and_read_processed(tmp_data_dir: Path):
    """write_processed and read_processed should roundtrip ProcessedItem objects."""
    date_str = "2026-05-15"
    flags = Flags(source_role="公式")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime.now(timezone.utc),
            url="https://example.com/1",
            author="user1",
            genre="games",
            subcategory_id="cat1",
            category_name="Category",
            importance="A",
            summary="Summary",
            flags=flags,
            dedup_key="key1",
        ),
    ]

    storage.write_processed(date_str, items)
    read_items = storage.read_processed(date_str)

    assert len(read_items) == 1
    assert read_items[0].source_id == "src1"
    assert read_items[0].importance == "A"


def test_read_processed_nonexistent_file(tmp_data_dir: Path):
    """read_processed should return empty list if file doesn't exist."""
    date_str = "2099-12-31"

    items = storage.read_processed(date_str)

    assert items == []


def test_read_processed_range(tmp_data_dir: Path):
    """read_processed_range should return items from all dates in range."""
    flags = Flags(source_role="メディア")

    for i, day_offset in enumerate([0, 1, 2]):
        date_str = (datetime(2026, 5, 15, tzinfo=timezone.utc) + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        items = [
            ProcessedItem(
                source_id="src1",
                raw_fingerprint=f"fp{i}",
                timestamp=datetime.now(timezone.utc),
                url=f"https://example.com/{i}",
                author="user1",
                genre="anime",
                subcategory_id="cat1",
                category_name="Category",
                importance="B",
                summary="Summary",
                flags=flags,
                dedup_key=f"key{i}",
            ),
        ]
        storage.write_processed(date_str, items)

    start = datetime(2026, 5, 15, tzinfo=timezone.utc)
    end = datetime(2026, 5, 17, tzinfo=timezone.utc)

    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 3


def test_read_processed_range_single_day(tmp_data_dir: Path):
    """read_processed_range should work with same start and end date."""
    date_str = "2026-05-15"
    flags = Flags(source_role="個人")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime.now(timezone.utc),
            url="https://example.com/1",
            author="user1",
            genre="disney",
            subcategory_id="cat1",
            category_name="Category",
            importance="C",
            summary="Summary",
            flags=flags,
            dedup_key="key1",
        ),
    ]
    storage.write_processed(date_str, items)

    start = datetime(2026, 5, 15, tzinfo=timezone.utc)
    end = datetime(2026, 5, 15, tzinfo=timezone.utc)

    read_items = storage.read_processed_range(start, end)

    assert len(read_items) == 1
