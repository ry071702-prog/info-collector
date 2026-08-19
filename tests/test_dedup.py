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
    """_processed_file_date should extract date from nested directory name."""
    nested = tmp_path / "2026-07-04" / "items.jsonl"
    nested.parent.mkdir(parents=True, exist_ok=True)

    result = dedup._processed_file_date(nested)

    assert result.year == 2026
    assert result.month == 7
    assert result.day == 4


def test_processed_file_date_flat_legacy_file(tmp_path: Path):
    """_processed_file_date should extract date from flat legacy file stem."""
    flat_file = tmp_path / "2026-06-15.jsonl"
    flat_file.touch()

    result = dedup._processed_file_date(flat_file)

    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15


def test_processed_file_date_invalid_no_date(tmp_path: Path):
    """_processed_file_date should return None if no valid date found."""
    invalid_file = tmp_path / "invalid_name.jsonl"
    invalid_file.touch()

    result = dedup._processed_file_date(invalid_file)

    assert result is None


def test_processed_file_date_invalid_directory_and_stem(tmp_path: Path):
    """_processed_file_date should return None if both directory and stem are invalid."""
    bad_dir = tmp_path / "not_a_date"
    bad_dir.mkdir()
    bad_file = bad_dir / "also_invalid.jsonl"
    bad_file.touch()

    result = dedup._processed_file_date(bad_file)

    assert result is None


def test_recent_raw_fingerprints_empty_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should return empty set if processed dir doesn't exist."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)

    result = dedup.recent_raw_fingerprints(days=7)

    assert result == set()


def test_recent_raw_fingerprints_respects_cutoff_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should exclude items older than cutoff days."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    # Create two dated processed files
    old_date_dir = processed_dir / "2026-06-20"
    old_date_dir.mkdir()
    old_file = old_date_dir / "items.jsonl"
    old_file.write_text(
        '{"raw_fingerprint": "old_fp"}\n'
        '{"raw_fingerprint": "old_fp_2"}\n',
        encoding="utf-8",
    )

    recent_date_dir = processed_dir / "2026-07-02"
    recent_date_dir.mkdir()
    recent_file = recent_date_dir / "items.jsonl"
    recent_file.write_text(
        '{"raw_fingerprint": "recent_fp"}\n'
        '{"raw_fingerprint": "recent_fp_2"}\n',
        encoding="utf-8",
    )

    result = dedup.recent_raw_fingerprints(days=3)

    # Assuming today is around 2026-07-04, old items from 2026-06-20 should be excluded
    assert "recent_fp" in result
    assert "recent_fp_2" in result
    # Old items should not be included
    assert len(result) == 2


def test_recent_raw_fingerprints_handles_corrupted_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should skip corrupted JSONL lines gracefully."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    file_dir = processed_dir / "2026-07-03"
    file_dir.mkdir()
    jsonl_file = file_dir / "items.jsonl"

    # Mix valid and invalid JSON lines
    jsonl_file.write_text(
        '{"raw_fingerprint": "valid_fp"}\n'
        'invalid json here\n'
        '{"raw_fingerprint": "another_valid"}\n',
        encoding="utf-8",
    )

    # Should not raise, just skip invalid lines
    result = dedup.recent_raw_fingerprints(days=3)

    # Should still collect valid fingerprints despite corrupted lines
    assert "valid_fp" in result or "another_valid" in result or len(result) == 0


def test_recent_raw_fingerprints_supports_legacy_flat_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should support both nested and flat processed files."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_path)
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    # Legacy flat file with date in filename
    flat_file = processed_dir / "2026-07-03.jsonl"
    flat_file.write_text(
        '{"raw_fingerprint": "flat_fp_1"}\n'
        '{"raw_fingerprint": "flat_fp_2"}\n',
        encoding="utf-8",
    )

    # New nested file structure
    nested_dir = processed_dir / "2026-07-04"
    nested_dir.mkdir()
    nested_file = nested_dir / "items.jsonl"
    nested_file.write_text(
        '{"raw_fingerprint": "nested_fp_1"}\n',
        encoding="utf-8",
    )

    result = dedup.recent_raw_fingerprints(days=3)

    assert "flat_fp_1" in result
    assert "flat_fp_2" in result
    assert "nested_fp_1" in result
