"""notify_priority が process_digest の記事を食べないことの回帰テスト。

notify_priority は S/A の Discord 通知だけが仕事。かつては dedup.filter_new を呼んでおり、
その副作用で全記事 (B/C 含む) のキーが dedup_keys.json に登録され、data/cache ごと commit /
push されていた。結果、後続の process_digest が同じ記事を「重複」と判定して捨て、Notion /
Sheets / サイトに何も残らなかった。通知自体の重複抑制は discord_sent.json 側の仕事。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import dedup
from src.jobs import notify_priority
from src.models import Flags, ProcessedItem, RawItem


def _raw(url: str) -> RawItem:
    return RawItem(
        source_id="src1",
        platform="rss",
        url=url,
        author="author",
        account_type="公式",
        text="text",
        timestamp=datetime.now(timezone.utc),
    )


def _processed(url: str, importance: str, key: str) -> ProcessedItem:
    return ProcessedItem(
        source_id="src1",
        raw_fingerprint=key,
        timestamp=datetime.now(timezone.utc),
        url=url,
        author="author",
        genre="games",
        subcategory_id="cat1",
        category_name="Category",
        importance=importance,
        summary="Summary",
        flags=Flags(source_role="公式"),
        dedup_key=key,
    )


def test_notify_priority_does_not_touch_dedup_cache(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    cache_file = tmp_cache_dir / "dedup_keys.json"
    monkeypatch.setattr(dedup, "CACHE_FILE", cache_file)

    items = [
        _processed("https://example.com/1", "S", "key-s"),
        _processed("https://example.com/2", "C", "key-c"),
    ]
    monkeypatch.setattr(notify_priority, "read_raw", lambda _d: [_raw("https://example.com/1")])
    monkeypatch.setattr(notify_priority.classify, "process", lambda _items: items)

    notified: list[list[ProcessedItem]] = []
    monkeypatch.setattr(
        notify_priority.discord, "notify_priority", lambda sa: (notified.append(sa), len(sa))[1]
    )

    notify_priority.main()

    # S だけ通知される
    assert [it.dedup_key for it in notified[0]] == ["key-s"]

    # そして dedup キャッシュは一切書かれない = process_digest が同じ記事を処理できる
    assert not cache_file.exists(), "notify_priority が dedup_keys.json を汚染している"
    assert dedup.load_recent_keys() == {}
