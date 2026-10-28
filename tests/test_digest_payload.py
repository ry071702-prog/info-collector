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
