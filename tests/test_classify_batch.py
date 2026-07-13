"""バッチ LLM 呼び出し (コスト削減 2026-07-13) の回帰テスト。

守りたい性質:
  1. まとめて送ることで LLM 呼び出し回数が実際に減る (= 課金が減る)
  2. バッチが壊れても記事を取りこぼさない (単件フォールバック)
安さより「落とさない」が優先。2 が崩れたら削減は無意味なので必ず両方見る。
"""
from __future__ import annotations
from datetime import datetime, timezone

import pytest

from src.models import RawItem
from src.processors import classify


def _item(i: int) -> RawItem:
    return RawItem(
        source_id=f"SRC{i}",
        platform="YouTube",
        author=f"author{i}",
        account_type="メディア",  # 個人でない = LLM 行き。公式でないので pin もされない
        # _heuristic_prefilter の too-short 判定に引っかからない長さにする
        text=(
            f"【速報】人気タイトルの完全新作が正式発表されました。発売は2026年冬を予定しており、"
            f"対応プラットフォームは複数機種。ティザー映像も同時公開されています。記事番号 {i}"
        ),
        url=f"https://example.com/{i}",
        timestamp=datetime.now(timezone.utc),
        extra={"source_type": "メディア"},
    )


def _filter_row(i: int) -> dict:
    return {"id": i, "spam": False, "genre": "games", "confidence": 0.9, "reason": "r"}


def _classify_row(i: int) -> dict:
    return {
        "id": i,
        "subcategory_id": "C7",
        "category_name": "決勝・優勝・MVP",
        "importance": "B",
        "summary": f"要約{i}",
        "title_tags": ["t"],
        "entity_tags": ["e"],
        "flags": {
            "source_role": "メディア", "speed": "通常", "spoiler": "なし",
            "language": "ja", "content_type": "text",
            "source_reliability": "公式確定", "cross_genre": "ゲーム単独",
        },
        "dedup_key": f"key_{i}",
        "risk_level": "low",
        "streamer_influence_score": 0,
        "clip_virality_score": 0,
        "game_trend_from_streamers_score": 0,
    }


@pytest.fixture(autouse=True)
def _no_dedup_skip(monkeypatch):
    """dedup の既知 fingerprint による事前スキップを無効化する。"""
    monkeypatch.setattr(classify, "_RECENT_RAW_FINGERPRINTS", set())


@pytest.fixture
def spy(monkeypatch):
    """llm_client.call_json を差し替え、呼び出しを記録する。"""
    calls: list[dict] = []

    def make(handler):
        def fake_call_json(*, model, system, user, max_tokens=1024, temperature=0.0):
            calls.append({"user": user, "max_tokens": max_tokens})
            return handler(user, len(calls))
        monkeypatch.setattr(classify.llm_client, "call_json", fake_call_json)
        return calls

    return make


def _is_filter_call(user: str) -> bool:
    # classify のプロンプトだけが taxonomy (サブカテゴリ一覧) を含む
    return "【サブカテゴリ一覧" not in user


def test_batch_reduces_call_count(spy):
    """20件が filter 1回 + classify 1回 = 計2回で済む (単件なら40回)。"""
    items = [_item(i) for i in range(20)]

    def handler(user, _n):
        n = user.count("--- [")
        rows = _filter_row if _is_filter_call(user) else _classify_row
        return {"results": [rows(i) for i in range(n)]}

    calls = spy(handler)
    out = classify.process(items)

    assert len(out) == 20, "20件すべて分類されるべき"
    assert len(calls) == 2, f"filter1回+classify1回のはずが {len(calls)} 回呼ばれた"


def test_partial_batch_response_falls_back_per_item(spy):
    """バッチが一部の id しか返さなくても、欠けた分は単件で埋めて取りこぼさない。"""
    items = [_item(i) for i in range(5)]

    def handler(user, _n):
        n = user.count("--- [")
        rows = _filter_row if _is_filter_call(user) else _classify_row
        if n > 1:
            # バッチ呼び出し: わざと最後の1件を落とす
            return {"results": [rows(i) for i in range(n - 1)]}
        # 単件フォールバック: 単件プロンプトは id を持たないので素の dict を返す
        r = rows(0)
        r.pop("id")
        return r

    spy(handler)
    out = classify.process(items)

    assert len(out) == 5, "バッチが1件落としても単件フォールバックで5件揃うべき"


def test_batch_exception_falls_back_per_item(spy):
    """バッチが例外で丸ごと失敗しても、単件フォールバックで全件処理される。"""
    items = [_item(i) for i in range(3)]

    def handler(user, _n):
        n = user.count("--- [")
        if n > 1:
            raise ValueError("batch blew up")
        rows = _filter_row if _is_filter_call(user) else _classify_row
        r = rows(0)
        r.pop("id")
        return r

    spy(handler)
    out = classify.process(items)

    assert len(out) == 3, "バッチ全滅でも単件で3件処理されるべき"


def test_quota_exhausted_stops_immediately(spy):
    """クォータ枯渇は即座に打ち切る (単件フォールバックで叩き続けない)。"""
    items = [_item(i) for i in range(10)]

    def handler(user, _n):
        raise classify.llm_client.QuotaExhausted("out of quota")

    calls = spy(handler)
    out = classify.process(items)

    assert out == []
    assert len(calls) == 1, f"枯渇後も {len(calls)} 回叩いている"


def test_batch_llm_false_restores_per_item(spy, monkeypatch):
    """[cost] batch_llm = false で旧挙動 (1件1呼び出し) に戻せる。"""
    base = classify.settings()
    monkeypatch.setattr(
        classify, "settings", lambda: {**base, "cost": {"batch_llm": False}}
    )
    items = [_item(i) for i in range(3)]

    def handler(user, _n):
        rows = _filter_row if _is_filter_call(user) else _classify_row
        r = rows(0)
        r.pop("id")
        return r

    calls = spy(handler)
    out = classify.process(items)

    assert len(out) == 3
    assert len(calls) == 6, f"3件 x (filter+classify) = 6回のはずが {len(calls)} 回"
