"""Tests for JSONL-based storage module."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

import pytest

from src.models import RawItem, ProcessedItem, Flags
from src import storage


def test_write_raw_creates_file(tmp_data_dirs: dict[str, Path]) -> None:
    """write_raw should create a JSONL file with RawItem entries."""
    date_str = "2026-05-15"
    source_id = "test_source"
    items = [
        RawItem(
            source_id=source_id,
            platform="X",
            author="user1",
            account_type="個人",
            text="Test post 1",
            url="https://example.com/1",
            timestamp=datetime(2026, 5, 15, 10, 0, 0),
        ),
        RawItem(
            source_id=source_id,
            platform="X",
            author="user2",
            account_type="メディア",
            text="Test post 2",
            url="https://example.com/2",
            timestamp=datetime(2026, 5, 15, 11, 0, 0),
        ),
    ]

    path = storage.write_raw(date_str, source_id, items)

    assert path.exists()
    assert path.name == f"{source_id}.jsonl"
    assert path.parent == tmp_data_dirs["raw"] / date_str

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_read_raw_empty_directory(tmp_data_dirs: dict[str, Path]) -> None:
    """read_raw should return empty iterator when no files exist."""
    date_str = "2026-05-14"
    result = list(storage.read_raw(date_str))
    assert result == []


def test_read_raw_returns_items(tmp_data_dirs: dict[str, Path]) -> None:
    """read_raw should deserialize RawItem objects from JSONL files."""
    date_str = "2026-05-15"
    source_id = "test_source"
    original_items = [
        RawItem(
            source_id=source_id,
            platform="X",
            author="user1",
            account_type="個人",
            text="Test post",
            url="https://example.com/1",
            timestamp=datetime(2026, 5, 15, 10, 0, 0),
        ),
    ]

    storage.write_raw(date_str, source_id, original_items)
    read_items = list(storage.read_raw(date_str))

    assert len(read_items) == 1
    assert read_items[0].author == "user1"
    assert read_items[0].text == "Test post"


def test_write_processed_creates_file(tmp_data_dirs: dict[str, Path]) -> None:
    """write_processed should create a JSONL file with ProcessedItem entries."""
    date_str = "2026-05-15"
    flags = Flags(source_role="公式")
    items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 15, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="cat_game_01",
            category_name="ゲーム発表",
            importance="A",
            summary="Summary 1",
            flags=flags,
            dedup_key="dedup_1",
        ),
    ]

    path = storage.write_processed(date_str, items)

    assert path.exists()
    assert path.name == "items.jsonl"
    assert path.parent == tmp_data_dirs["processed"] / date_str


def test_read_processed_empty(tmp_data_dirs: dict[str, Path]) -> None:
    """read_processed should return empty list when file does not exist."""
    date_str = "2026-05-14"
    result = storage.read_processed(date_str)
    assert result == []


def test_read_processed_returns_items(tmp_data_dirs: dict[str, Path]) -> None:
    """read_processed should deserialize ProcessedItem objects from JSONL file."""
    date_str = "2026-05-15"
    flags = Flags(source_role="メディア")
    original_items = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 15, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="cat_game_01",
            category_name="ゲーム発表",
            importance="S",
            summary="Summary 1",
            flags=flags,
            dedup_key="dedup_1",
        ),
        ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 15, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="cat_anime_01",
            category_name="新作アニメ",
            importance="A",
            summary="Summary 2",
            flags=flags,
            dedup_key="dedup_2",
        ),
    ]

    storage.write_processed(date_str, original_items)
    read_items = storage.read_processed(date_str)

    assert len(read_items) == 2
    assert read_items[0].author == "author1"
    assert read_items[1].genre == "anime"


def test_read_processed_range(tmp_data_dirs: dict[str, Path]) -> None:
    """read_processed_range should read items across multiple date directories."""
    flags = Flags(source_role="公式")
    dates = ["2026-05-13", "2026-05-14", "2026-05-15"]

    for i, date_str in enumerate(dates):
        items = [
            ProcessedItem(
                source_id="src1",
                raw_fingerprint=f"fp{i}",
                timestamp=datetime.fromisoformat(f"{date_str}T10:00:00"),
                url=f"https://example.com/{i}",
                author=f"author{i}",
                genre="games",
                subcategory_id="cat",
                category_name="cat",
                importance="B",
                summary=f"Summary {i}",
                flags=flags,
                dedup_key=f"dedup_{i}",
            ),
        ]
        storage.write_processed(date_str, items)

    start = datetime(2026, 5, 13, 0, 0, 0)
    end = datetime(2026, 5, 15, 23, 59, 59)
    result = storage.read_processed_range(start, end)

    assert len(result) == 3
    assert result[0].author == "author0"
    assert result[2].author == "author2"


def test_write_processed_append_mode(tmp_data_dirs: dict[str, Path]) -> None:
    """write_processed should append to existing file."""
    date_str = "2026-05-15"
    flags = Flags(source_role="公式")

    items1 = [
        ProcessedItem(
            source_id="src1",
            raw_fingerprint="fp1",
            timestamp=datetime(2026, 5, 15, 10, 0, 0),
            url="https://example.com/1",
            author="author1",
            genre="games",
            subcategory_id="cat",
            category_name="cat",
            importance="A",
            summary="Summary 1",
            flags=flags,
            dedup_key="dedup_1",
        ),
    ]

    items2 = [
        ProcessedItem(
            source_id="src2",
            raw_fingerprint="fp2",
            timestamp=datetime(2026, 5, 15, 11, 0, 0),
            url="https://example.com/2",
            author="author2",
            genre="anime",
            subcategory_id="cat",
            category_name="cat",
            importance="B",
            summary="Summary 2",
            flags=flags,
            dedup_key="dedup_2",
        ),
    ]

    storage.write_processed(date_str, items1)
    storage.write_processed(date_str, items2)

    result = storage.read_processed(date_str)
    assert len(result) == 2
    assert result[0].author == "author1"
    assert result[1].author == "author2"
