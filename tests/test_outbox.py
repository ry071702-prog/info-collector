"""外部出力の再送キュー (永久欠損の防止)。

process_digest は processed を先に書くため、Notion / Sheets が一時障害で失敗すると、
再実行しても raw_fingerprint でスキップされ **その記事は二度と外部に載らない**。
しかもジョブは成功扱いなので気づけない。失敗分を outbox に積み、次回 run で再送する。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import outbox
from src.models import Flags, ProcessedItem


def _item(key: str, genre: str = "games") -> ProcessedItem:
    return ProcessedItem(
        source_id="src1",
        raw_fingerprint=key,
        timestamp=datetime.now(timezone.utc),
        url=f"https://example.com/{key}",
        author="author",
        genre=genre,
        subcategory_id="cat1",
        category_name="Category",
        importance="A",
        summary="Summary",
        flags=Flags(source_role="公式"),
        dedup_key=key,
    )


def test_add_load_roundtrip(tmp_cache_dir: Path):
    outbox.add("notion", [_item("a"), _item("b")])
    assert [it.dedup_key for it in outbox.load("notion")] == ["a", "b"]


def test_replace_with_empty_clears_queue(tmp_cache_dir: Path):
    """再送が全部成功したらキューは空になる。"""
    outbox.add("notion", [_item("a")])
    outbox.replace("notion", [])
    assert outbox.load("notion") == []


def test_only_failures_remain_after_partial_resend(tmp_cache_dir: Path):
    outbox.add("sheets", [_item("a"), _item("b"), _item("c")])
    still_failing = [_item("b")]  # a と c は再送成功したとする
    outbox.replace("sheets", still_failing)
    assert [it.dedup_key for it in outbox.load("sheets")] == ["b"]


def test_same_item_is_not_queued_twice(tmp_cache_dir: Path):
    """同じ記事が毎 run 積み増されてキューが膨らまない。"""
    outbox.add("notion", [_item("a")])
    outbox.add("notion", [_item("a")])
    assert len(outbox.load("notion")) == 1


def test_targets_are_independent(tmp_cache_dir: Path):
    """Notion だけ落ちた時に Sheets の再送キューを汚さない。"""
    outbox.add("notion", [_item("a")])
    assert outbox.load("sheets") == []


def test_queue_is_capped_and_logs_the_drop(tmp_cache_dir: Path, caplog: pytest.LogCaptureFixture):
    """上限超過は黙って捨てない (捨てたことが分からないと outbox を信用できない)。"""
    outbox.replace("notion", [_item(f"k{i}") for i in range(outbox.MAX_ITEMS + 10)])
    assert len(outbox.load("notion")) == outbox.MAX_ITEMS
