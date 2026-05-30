"""Tests for deduplication logic."""
from __future__ import annotations
from datetime import datetime, timedelta
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
        timestamp=datetime.utcnow(),
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
        "existing_key": datetime.utcnow().isoformat(),
    }
    cache_file.write_text(json.dumps(initial_data), encoding="utf-8")
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    flags = Flags(source_role="メディア")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime.utcnow(),
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
        timestamp=datetime.utcnow(),
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
    now = datetime.utcnow()
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
        "key1": datetime.utcnow().isoformat(),
        "key2": datetime.utcnow().isoformat(),
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


def test_recent_raw_fingerprints_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should return empty set when no processed files exist."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    result = dedup.recent_raw_fingerprints()

    assert result == set()


def test_recent_raw_fingerprints_reads_nested_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should read nested format processed/YYYY-MM-DD/items.jsonl."""
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed" / "2026-05-20"
    processed_dir.mkdir(parents=True)
    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    flags = Flags(source_role="公式")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_recent_001",
        timestamp=datetime(2026, 5, 20, 10, 0, 0),
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

    items_file = processed_dir / "items.jsonl"
    items_file.write_text(item.model_dump_json() + "\n", encoding="utf-8")

    result = dedup.recent_raw_fingerprints(days=30)

    assert "fp_recent_001" in result


def test_recent_raw_fingerprints_respects_days_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should exclude files older than days parameter."""
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True)
    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    # Old file (10 days ago)
    old_dir = processed_dir / "2026-05-10"
    old_dir.mkdir(parents=True)
    flags = Flags(source_role="公式")
    old_item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_old_001",
        timestamp=datetime(2026, 5, 10, 10, 0, 0),
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
    (old_dir / "items.jsonl").write_text(old_item.model_dump_json() + "\n", encoding="utf-8")

    # Recent file (3 days ago)
    recent_dir = processed_dir / "2026-05-27"
    recent_dir.mkdir(parents=True)
    recent_item = ProcessedItem(
        source_id="src2",
        raw_fingerprint="fp_recent_001",
        timestamp=datetime(2026, 5, 27, 10, 0, 0),
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
    (recent_dir / "items.jsonl").write_text(recent_item.model_dump_json() + "\n", encoding="utf-8")

    result = dedup.recent_raw_fingerprints(days=7)

    assert "fp_recent_001" in result
    assert "fp_old_001" not in result


def test_recent_raw_fingerprints_legacy_flat_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should read legacy flat format processed/YYYY-MM-DD.jsonl."""
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    processed_dir.mkdir(parents=True)
    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    flags = Flags(source_role="公式")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_legacy_001",
        timestamp=datetime(2026, 5, 25, 10, 0, 0),
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

    legacy_file = processed_dir / "2026-05-25.jsonl"
    legacy_file.write_text(item.model_dump_json() + "\n", encoding="utf-8")

    result = dedup.recent_raw_fingerprints(days=30)

    assert "fp_legacy_001" in result


def test_processed_file_date_nested_format():
    """_processed_file_date should extract date from nested directory name."""
    path = Path("/data/processed/2026-05-20/items.jsonl")
    result = dedup._processed_file_date(path)
    assert result == date(2026, 5, 20)


def test_processed_file_date_flat_format():
    """_processed_file_date should extract date from flat file name."""
    path = Path("/data/processed/2026-05-20.jsonl")
    result = dedup._processed_file_date(path)
    assert result == date(2026, 5, 20)


def test_processed_file_date_invalid_name():
    """_processed_file_date should return None for unparseable names."""
    path = Path("/data/processed/invalid/items.jsonl")
    result = dedup._processed_file_date(path)
    assert result is None


def test_filter_new_updates_timestamps(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """filter_new should update timestamps for new items in cache."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    flags = Flags(source_role="公式")
    item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime.utcnow(),
        url="https://example.com/1",
        author="user1",
        genre="games",
        subcategory_id="cat1",
        category_name="Category",
        importance="A",
        summary="Summary",
        flags=flags,
        dedup_key="new_key",
    )

    kept, dropped = dedup.filter_new([item])

    # Verify that the key was added to cache with a timestamp
    cached = dedup.load_recent_keys()
    assert "new_key" in cached
    assert len(kept) == 1
    assert dropped == 0
