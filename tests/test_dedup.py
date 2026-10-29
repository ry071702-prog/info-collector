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


def test_processed_file_date_nested_dir():
    """_processed_file_date should extract date from parent directory name."""
    path = Path("processed") / "2026-10-15" / "items.jsonl"
    date = dedup._processed_file_date(path)
    assert date is not None
    assert date.year == 2026
    assert date.month == 10
    assert date.day == 15


def test_processed_file_date_flat_filename():
    """_processed_file_date should extract date from filename stem."""
    path = Path("processed") / "2026-10-20.jsonl"
    date = dedup._processed_file_date(path)
    assert date is not None
    assert date.year == 2026
    assert date.month == 10
    assert date.day == 20


def test_processed_file_date_invalid_format():
    """_processed_file_date should return None for unparseable dates."""
    path = Path("processed") / "invalid" / "data.jsonl"
    date = dedup._processed_file_date(path)
    assert date is None


def test_recent_raw_fingerprints_no_processed_dir(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should return empty set when processed dir doesn't exist."""
    monkeypatch.setattr(dedup, "DATA_DIR", tmp_cache_dir)

    fingerprints = dedup.recent_raw_fingerprints()

    assert fingerprints == set()


def test_recent_raw_fingerprints_reads_recent_files(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should load fingerprints from recent processed files."""
    data_dir = tmp_cache_dir / "data"
    # 固定日付だと 30 日経過後に窓から外れて落ちるため、当日 (UTC) のディレクトリを使う
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    processed_dir = data_dir / "processed" / today
    processed_dir.mkdir(parents=True, exist_ok=True)

    flags = Flags(source_role="公式")
    item1 = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_recent_1",
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
        raw_fingerprint="fp_recent_2",
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

    items_file = processed_dir / "items.jsonl"
    items_file.write_text(item1.model_dump_json() + "\n" + item2.model_dump_json() + "\n", encoding="utf-8")

    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    fingerprints = dedup.recent_raw_fingerprints(days=30)

    assert "fp_recent_1" in fingerprints
    assert "fp_recent_2" in fingerprints


def test_recent_raw_fingerprints_ignores_old_files(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """recent_raw_fingerprints should ignore files older than specified days."""
    data_dir = tmp_cache_dir / "data"

    old_date = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")
    old_dir = data_dir / "processed" / old_date
    old_dir.mkdir(parents=True, exist_ok=True)

    flags = Flags(source_role="公式")
    old_item = ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp_old",
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

    old_file = old_dir / "items.jsonl"
    old_file.write_text(old_item.model_dump_json() + "\n", encoding="utf-8")

    # 窓内のファイルも置き、「何も読めていないから fp_old が無い」ケースと区別する
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recent_dir = data_dir / "processed" / today
    recent_dir.mkdir(parents=True, exist_ok=True)
    recent_item = old_item.model_copy(update={"raw_fingerprint": "fp_recent", "dedup_key": "key2"})
    (recent_dir / "items.jsonl").write_text(recent_item.model_dump_json() + "\n", encoding="utf-8")

    monkeypatch.setattr(dedup, "DATA_DIR", data_dir)

    fingerprints = dedup.recent_raw_fingerprints(days=30)

    assert "fp_recent" in fingerprints
    assert "fp_old" not in fingerprints
