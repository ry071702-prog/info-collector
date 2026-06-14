"""Tests for scoring helpers in processors.classify and digest."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from src.models import Flags, ProcessedItem
from src.processors import digest
from src.processors.classify import (
    _final_priority,
    _freshness_score,
    _live_trend_score,
    _video_trend_score,
)


# ---- live_trend_score ----
@pytest.mark.parametrize(
    "viewer_count,expected",
    [
        (None, 0),
        (0, 0),
        (50, 0),
        (100, 30),
        (999, 30),
        (1000, 50),
        (4999, 50),
        (5000, 70),
        (20000, 90),
        (100000, 100),
        (1_000_000, 100),
    ],
)
def test_live_trend_score_buckets(viewer_count, expected):
    assert _live_trend_score(viewer_count) == expected


# ---- video_trend_score ----
def test_video_trend_score_zero_for_low_views():
    ts = datetime.now(timezone.utc) - timedelta(hours=10)
    assert _video_trend_score(0, ts) == 0
    assert _video_trend_score(500, ts) == 0


def test_video_trend_score_growing_with_rate():
    # 9h で 100k views → ~11k/hour → 70 (境界値 10k/h を避けて安定させる)
    ts = datetime.now(timezone.utc) - timedelta(hours=9)
    assert _video_trend_score(100_000, ts) == 70


def test_video_trend_score_caps_at_100():
    # 1h で 500k views → 500k/hour → 100
    ts = datetime.now(timezone.utc) - timedelta(hours=1)
    assert _video_trend_score(500_000, ts) == 100


def test_video_trend_score_naive_timestamp_handled():
    # tzinfo=None でも落ちないこと
    ts = datetime.utcnow() - timedelta(hours=5)
    assert _video_trend_score(50_000, ts) >= 30


# ---- freshness_score ----
def test_freshness_recent_high():
    ts = datetime.now(timezone.utc) - timedelta(hours=2)
    assert _freshness_score(ts) == 100


def test_freshness_72h_mid():
    ts = datetime.now(timezone.utc) - timedelta(hours=60)
    assert _freshness_score(ts) == 70


def test_freshness_old_low():
    ts = datetime.now(timezone.utc) - timedelta(days=30)
    assert _freshness_score(ts) == 10


# ---- final_priority composition ----
def test_final_priority_S_threshold():
    # S importance + 24h freshness → composite > 80
    assert _final_priority("S", 100, 0, 0, 0) == "S"


def test_final_priority_C_only_when_all_low():
    # C importance + old timestamp + 0 scores
    assert _final_priority("C", 10, 0, 0, 0) == "C"


def test_final_priority_live_boost():
    # B importance alone is B, でも live=100 で boost すると A 以上に上がるはず
    base = _final_priority("B", 70, 0, 0, 0)
    boosted = _final_priority("B", 70, 0, 0, 0, live=100, video=0)
    rank = {"S": 4, "A": 3, "B": 2, "C": 1}
    assert rank[boosted] >= rank[base]


# ---- cross_source_trends ----
def _make_item(entity_tags: list[str], risk_level: str = "low") -> ProcessedItem:
    return ProcessedItem(
        source_id="x",
        raw_fingerprint="fp",
        timestamp=datetime.now(timezone.utc),
        url="https://example.invalid",
        author="a",
        genre="games",
        subcategory_id="A1",
        category_name="release",
        importance="A",
        summary="s",
        title_tags=[],
        entity_tags=entity_tags,
        flags=Flags(source_role="公式"),
        dedup_key="k",
        risk_level=risk_level,
    )


def test_cross_source_trends_threshold():
    items = [
        _make_item(["FF14"]),
        _make_item(["FF14"]),
        _make_item(["FF14"]),  # 3 件で min_count に到達
        _make_item(["他作品"]),  # 1 件のみで除外
    ]
    trends = digest.cross_source_trends(items, min_count=3, top_n=5)
    assert len(trends) == 1
    assert trends[0][0] == "FF14"
    assert trends[0][1] == 3


def test_cross_source_trends_skips_high_risk():
    items = [
        _make_item(["炎上案件"], risk_level="high"),
        _make_item(["炎上案件"], risk_level="high"),
        _make_item(["炎上案件"], risk_level="high"),
    ]
    assert digest.cross_source_trends(items, min_count=3) == []


def test_cross_source_trends_top_n_limit():
    items = []
    for tag in ("AA", "BB", "CC", "DD", "EE"):  # len>=2 を満たす (1文字タグは内部でスキップ)
        for _ in range(4):
            items.append(_make_item([tag]))
    trends = digest.cross_source_trends(items, min_count=3, top_n=3)
    assert len(trends) == 3
