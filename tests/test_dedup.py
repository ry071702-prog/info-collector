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
