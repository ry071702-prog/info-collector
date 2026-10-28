"""daily_digest に送る入力の中身のテスト

全項目を indent つきで送ると 403件で約20万トークンになっていた
指示文が使う項目だけに絞ると約8.4万トークン (2026-10-28 count_tokens で実測)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.models import Flags, ProcessedItem
from src.processors import digest


def _item() -> ProcessedItem:
    return ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 10, 28, 9, 30, 15, tzinfo=timezone.utc),
        url="https://example.com/1",
        author="公式X",
        genre="games",
        subcategory_id="cat1",
        category_name="新作・リリース情報",
        importance="S",
        summary="新作発表",
        title_tags=["作品A"],
        entity_tags=["会社B"],
        flags=Flags(source_role="公式", speed="速報", spoiler="軽微"),
        dedup_key="key1",
        risk_level="high",
        streamer_influence_score=80,
        streamer_name="配信者C",
    )


def test_digest_payload_keeps_fields_the_prompt_uses():
    row = json.loads(digest._digest_items_json([_item()]))[0]
    assert row == {
        "url": "https://example.com/1",
        "author": "公式X",
        "timestamp": "2026-10-28T09:30+00:00",
        "genre": "games",
        "category_name": "新作・リリース情報",
        "importance": "S",
        "risk_level": "high",
        "summary": "新作発表",
        "title_tags": ["作品A"],
        "entity_tags": ["会社B"],
        "speed": "速報",
        "source_role": "公式",
        "spoiler": "軽微",
    }


def test_digest_payload_is_compact_and_smaller():
    items = [_item() for _ in range(20)]
    new = digest._digest_items_json(items)
    assert "\n" not in new and ", " not in new
    assert len(new) < len(digest._items_to_json(items)) / 2


def test_daily_digest_sends_trimmed_payload(monkeypatch):
    sent = {}
    monkeypatch.setattr(digest.llm_client, "call_text", lambda **kw: sent.update(kw) or "ok")
    digest.daily_digest([_item()], "2026-10-28 AM")
    assert "streamer_influence_score" not in sent["user"]
    assert '"importance":"S"' in sent["user"]


def _mk(n: int, importance: str = "A", genre: str = "games", speed: str = "通常", risk: str = "low", tags=None) -> ProcessedItem:
    return ProcessedItem(
        source_id="src",
        raw_fingerprint=f"fp{n}",
        timestamp=datetime(2026, 10, 28, 0, n % 60, tzinfo=timezone.utc),
        url=f"https://example.com/{n}",
        author="media",
        genre=genre,
        subcategory_id="cat",
        category_name="新作・リリース情報",
        importance=importance,
        summary=f"item {n}",
        title_tags=tags or [],
        flags=Flags(source_role="メディア", speed=speed),
        dedup_key=f"key{n}",
        risk_level=risk,
    )


def test_pick_lists_s_before_a_and_caps_top():
    """S が A に埋もれない  上限15件  高リスクは上段に入れない (2026-10-28 指示文だけで絞ると S 32件を1件も選ばなかった)"""
    items = [_mk(i, "A", speed="速報") for i in range(20)]
    items += [_mk(100 + i, "S") for i in range(3)]
    items += [_mk(200, "S", risk="high")]
    picked = digest._digest_pick(items)
    top_urls = [it.url for it in picked["top"]]
    assert len(top_urls) == digest.DIGEST_TOP_MAX == 15
    assert set(top_urls[:3]) == {f"https://example.com/{100 + i}" for i in range(3)}
    assert "https://example.com/200" not in top_urls
    assert [it.url for it in picked["risk"]] == ["https://example.com/200"]


def test_pick_caps_b_per_genre_and_drops_c():
    items = [_mk(i, "B", "games") for i in range(8)]
    items += [_mk(100 + i, "B", "anime") for i in range(8)]
    items += [_mk(200, "C", "games")]
    picked = digest._digest_pick(items)
    assert len(picked["games"]) == len(picked["anime"]) == digest.DIGEST_GENRE_MAX == 5
    assert all(it.importance == "B" for it in picked["games"] + picked["anime"])


def test_pick_folds_duplicate_dedup_keys():
    a, b = _mk(1, "S"), _mk(2, "S")
    b.dedup_key = a.dedup_key
    assert len(digest._digest_pick([a, b])["top"]) == 1


def test_stats_count_every_item_not_only_picked():
    items = [_mk(i, "A", speed="速報", tags=["作品X"]) for i in range(20)]
    items += [_mk(100 + i, "B", tags=["作品Y"]) for i in range(3)]
    stats = digest._digest_stats(items, digest._digest_pick(items))
    assert stats["総件数"] == 23
    assert stats["速報件数"] == 20 and stats["通常件数"] == 3
    assert stats["重要件数(S/A)"] == 20
    assert stats["S/Aで載せなかった件数"] == 5
    assert stats["発信元別"] == {"メディア": 23}
    assert stats["注目タグTOP5"][0] == ["作品X", 20]


def test_daily_digest_sends_only_picked_items_and_stats(monkeypatch):
    sent = {}
    monkeypatch.setattr(digest.llm_client, "call_text", lambda **kw: sent.update(kw) or "ok")
    items = [_mk(i, "A") for i in range(20)]
    digest.daily_digest(items, "2026-10-28 AM")
    assert "https://example.com/19" in sent["user"]
    assert "https://example.com/0\"" not in sent["user"]  # 新しい順に選んで上限から外れた古い分
    assert '"総件数":20' in sent["user"]
