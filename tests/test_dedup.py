"""Tests for deduplication logic."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
from src.models import ProcessedItem, Flags
from src import dedup


def test_filter_new_empty_cache(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """filter_new should accept all items when cache is empty."""
    monkeypatch.setattr(dedup, "CACHE_FILE", tmp_cache_dir / "dedup_keys.json")

    flags = Flags(source_role="公式")
    item = ProcessedItem(
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
    )

    items = [item]
    kept, dropped = dedup.filter_new(items)

    assert len(kept) == 1
    assert dropped == 0
    assert kept[0].dedup_key == "key1"


def test_filter_new_with_duplicates(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """filter_new should skip items with keys already in cache."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    initial_data = {
        "existing_key": datetime.now(timezone.utc).isoformat(),
    }
    cache_file.write_text(json.dumps(initial_data), encoding="utf-8")
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    flags = Flags(source_role="メディア")
    item1 = ProcessedItem(
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
        dedup_key="existing_key",
    )
    item2 = ProcessedItem(
        source_id="src2",
        raw_fingerprint="fp2",
        timestamp=datetime.now(timezone.utc),
        url="https://example.com/2",
        author="user2",
        genre="anime",
        subcategory_id="cat2",
        category_name="Category",
        importance="B",
        summary="Summary",
        flags=flags,
        dedup_key="new_key",
    )

    items = [item1, item2]
    kept, dropped = dedup.filter_new(items)

    assert len(kept) == 1
    assert dropped == 1
    assert kept[0].dedup_key == "new_key"


def test_load_recent_keys_respects_window(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """load_recent_keys should only keep keys within WINDOW_DAYS."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=10)).isoformat()
    recent_date = (now - timedelta(days=3)).isoformat()

    data = {
        "old_key": old_date,
        "recent_key": recent_date,
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    loaded = dedup.load_recent_keys()

    assert "recent_key" in loaded
    assert "old_key" not in loaded


def test_save_and_load_keys(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """save_keys and load_recent_keys should roundtrip data."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    test_keys = {
        "key1": datetime.now(timezone.utc).isoformat(),
        "key2": datetime.now(timezone.utc).isoformat(),
    }

    dedup.save_keys(test_keys)
    loaded = dedup.load_recent_keys()

    assert len(loaded) == 2
    assert "key1" in loaded
    assert "key2" in loaded


def test_load_recent_keys_handles_corrupted_cache(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """load_recent_keys should return empty dict on corrupted JSON."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    cache_file.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    loaded = dedup.load_recent_keys()

    assert loaded == {}


def test_load_recent_keys_nonexistent_file(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """load_recent_keys should return empty dict if file doesn't exist."""
    cache_file = tmp_cache_dir / "nonexistent.json"
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    loaded = dedup.load_recent_keys()

    assert loaded == {}


def test_processed_file_date_nested_directory(tmp_path: Path):
    """_processed_file_date should extract date from parent directory name."""
    nested_path = tmp_path / "2026-07-15" / "items.jsonl"
    result = dedup._processed_file_date(nested_path)
    assert result is not None
    assert result.year == 2026
    assert result.month == 7
    assert result.day == 15


def test_processed_file_date_flat_filename(tmp_path: Path):
    """_processed_file_date should extract date from flat filename."""
    flat_path = tmp_path / "2026-06-20.jsonl"
    result = dedup._processed_file_date(flat_path)
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 20


def test_processed_file_date_invalid_format(tmp_path: Path):
    """_processed_file_date should return None for invalid date format."""
    invalid_path = tmp_path / "invalid" / "notadate.jsonl"
    result = dedup._processed_file_date(invalid_path)
    assert result is None


def test_recent_raw_fingerprints_no_processed_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should return empty set if processed dir doesn't exist."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)
    result = dedup.recent_raw_fingerprints()
    assert result == set()


def test_recent_raw_fingerprints_from_nested_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_cache_dir: Path):
    """recent_raw_fingerprints should collect fingerprints from nested processed JSONL files."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)

    processed_dir = tmp_path / "processed"
    today_dir = processed_dir / "2026-07-11"
    today_dir.mkdir(parents=True)

    flags = Flags(source_role="公式")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_nested_1",
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
    )
    item2 = ProcessedItem(
        source_id="src2",
        raw_fingerprint="fp_nested_2",
        timestamp=datetime.now(timezone.utc),
        url="https://example.com/2",
        author="user2",
        genre="anime",
        subcategory_id="cat2",
        category_name="Category",
        importance="B",
        summary="Summary",
        flags=flags,
        dedup_key="key2",
    )

    items_file = today_dir / "items.jsonl"
    with items_file.open("w", encoding="utf-8") as f:
        f.write(item1.model_dump_json() + "\n")
        f.write(item2.model_dump_json() + "\n")

    result = dedup.recent_raw_fingerprints(days=30)
    assert "fp_nested_1" in result
    assert "fp_nested_2" in result
    assert len(result) == 2


def test_recent_raw_fingerprints_respects_days_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should only include items within days window."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)

    processed_dir = tmp_path / "processed"
    old_dir = processed_dir / "2026-06-10"
    recent_dir = processed_dir / "2026-07-11"
    old_dir.mkdir(parents=True)
    recent_dir.mkdir(parents=True)

    flags = Flags(source_role="公式")
    old_item = ProcessedItem(
        source_id="src_old",
        raw_fingerprint="fp_old",
        timestamp=datetime.now(timezone.utc),
        url="https://example.com/old",
        author="user_old",
        genre="games",
        subcategory_id="cat1",
        category_name="Category",
        importance="A",
        summary="Summary",
        flags=flags,
        dedup_key="key_old",
    )
    recent_item = ProcessedItem(
        source_id="src_recent",
        raw_fingerprint="fp_recent",
        timestamp=datetime.now(timezone.utc),
        url="https://example.com/recent",
        author="user_recent",
        genre="anime",
        subcategory_id="cat2",
        category_name="Category",
        importance="B",
        summary="Summary",
        flags=flags,
        dedup_key="key_recent",
    )

    with (old_dir / "items.jsonl").open("w", encoding="utf-8") as f:
        f.write(old_item.model_dump_json() + "\n")
    with (recent_dir / "items.jsonl").open("w", encoding="utf-8") as f:
        f.write(recent_item.model_dump_json() + "\n")

    result = dedup.recent_raw_fingerprints(days=7)
    assert "fp_recent" in result
    assert "fp_old" not in result
