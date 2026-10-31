"""send_catchup (キャッチアップ便) のテスト。外部送信はすべてモック。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.jobs import send_catchup as sc
from src.models import Flags, ProcessedItem

NOW = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)  # JST 09:00 → morning


def _item(
    key: str,
    *,
    priority: str = "A",
    genre: str = "games",
    risk: str = "low",
    freshness: int = 50,
    ts: datetime | None = None,
) -> ProcessedItem:
    return ProcessedItem(
        source_id="s1",
        raw_fingerprint=f"https://example.com/{key}",
        timestamp=ts or NOW - timedelta(hours=1),
        url=f"https://example.com/{key}",
        author="author",
        genre=genre,  # type: ignore[arg-type]
        subcategory_id="x",
        category_name="cat",
        importance="A",
        summary=f"summary {key}",
        flags=Flags(source_role="公式"),
        dedup_key=key,
        risk_level=risk,  # type: ignore[arg-type]
        freshness_score=freshness,
        final_priority=priority,  # type: ignore[arg-type]
    )


@pytest.fixture
def sent_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "cache" / "catchup_sent.json"
    monkeypatch.setattr(sc, "SENT_FILE", p)
    return p


# --- _slot_from_hour ---------------------------------------------------------

@pytest.mark.parametrize(
    "hour,slot",
    [(0, "morning"), (9, "morning"), (10, "noon"), (14, "noon"), (15, "evening"), (23, "evening")],
)
def test_slot_from_hour(hour: int, slot: str) -> None:
    assert sc._slot_from_hour(hour) == slot


# --- _load_sent / _save_sent -------------------------------------------------

def test_load_sent_missing_file_returns_empty(sent_file: Path) -> None:
    assert sc._load_sent() == {}


def test_load_sent_broken_json_returns_empty(sent_file: Path) -> None:
    sent_file.parent.mkdir(parents=True)
    sent_file.write_text("{not json", encoding="utf-8")
    assert sc._load_sent() == {}


def test_save_sent_prunes_old_entries_and_roundtrips(sent_file: Path) -> None:
    now = datetime.now(timezone.utc)
    sc._save_sent({
        "fresh": now.isoformat(),
        "old": (now - timedelta(days=sc.SENT_RETAIN_DAYS + 1)).isoformat(),
    })
    loaded = sc._load_sent()
    assert set(loaded) == {"fresh"}


# --- _recent_candidates ------------------------------------------------------

def test_recent_candidates_reads_today_and_yesterday_and_filters_by_lookback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent = _item("recent", ts=NOW - timedelta(hours=2))
    naive_recent = _item("naive", ts=(NOW - timedelta(hours=3)).replace(tzinfo=None))
    too_old = _item("old", ts=NOW - timedelta(hours=sc.LOOKBACK_HOURS + 1))
    by_date = {"2026-10-26": [recent], "2026-10-25": [naive_recent, too_old]}
    calls: list[str] = []

    def fake_read(date_str: str) -> list[ProcessedItem]:
        calls.append(date_str)
        return by_date.get(date_str, [])

    monkeypatch.setattr(sc, "read_processed", fake_read)
    out = sc._recent_candidates(NOW)
    assert calls == ["2026-10-26", "2026-10-25"]
    assert [i.dedup_key for i in out] == ["recent", "naive"]


def test_recent_candidates_covers_daily_gap_at_noon_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1日1便 (JST 11:40 = UTC 02:40) では前日の処理分 (約25時間前) を拾えること
    now = datetime(2026, 10, 26, 2, 40, tzinfo=timezone.utc)
    yesterday_run = _item("yesterday", ts=datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc))
    monkeypatch.setattr(
        sc, "read_processed",
        lambda d: [yesterday_run] if d == "2026-10-25" else [],
    )
    assert [i.dedup_key for i in sc._recent_candidates(now)] == ["yesterday"]


# --- _select ------------------------------------------------------------------

def test_select_excludes_sent_high_risk_low_priority_and_duplicates() -> None:
    items = [
        _item("ok"),
        _item("ok"),  # 重複
        _item("sent"),
        _item("risky", risk="high"),
        _item("c", priority="C"),
    ]
    picked = sc._select(items, {"sent": "2026-10-26T00:00:00+00:00"})
    assert [i.dedup_key for i in picked] == ["ok"]


def test_select_orders_by_priority_then_freshness_then_recency() -> None:
    items = [
        _item("b", priority="B", freshness=100),
        _item("a_low", priority="A", freshness=10),
        _item("a_high_old", priority="A", freshness=90, ts=NOW - timedelta(hours=5)),
        _item("a_high_new", priority="A", freshness=90, ts=NOW - timedelta(hours=1)),
        _item("s", priority="S", freshness=0),
    ]
    picked = sc._select(items, {})
    assert [i.dedup_key for i in picked] == ["s", "a_high_new", "a_high_old", "a_low", "b"]


def test_select_respects_genre_cap_then_backfills() -> None:
    games = [_item(f"g{i}", genre="games", freshness=100 - i) for i in range(15)]
    anime = [_item(f"a{i}", genre="anime", priority="B") for i in range(2)]
    picked = sc._select(games + anime, {})
    keys = [i.dedup_key for i in picked]
    # 先に games 上限 8 件 + anime 2 件、その後 games で補充して計 17 件 (MAX_ITEMS 未満)
    assert keys[: sc.MAX_PER_GENRE] == [f"g{i}" for i in range(sc.MAX_PER_GENRE)]
    assert keys[sc.MAX_PER_GENRE : sc.MAX_PER_GENRE + 2] == ["a0", "a1"]
    assert len(picked) == 17
    assert len(set(keys)) == 17


def test_select_caps_at_max_items() -> None:
    items = [
        _item(f"{g}{i}", genre=g)
        for g in ("games", "anime", "disney", "both")
        for i in range(10)
    ]
    picked = sc._select(items, {})
    assert len(picked) == sc.MAX_ITEMS
    counts: dict[str, int] = {}
    for it in picked:
        counts[it.genre] = counts.get(it.genre, 0) + 1
    assert max(counts.values()) <= sc.MAX_PER_GENRE


# --- _hero / _audio -----------------------------------------------------------

@pytest.fixture
def site_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(sc, "DATA_DIR", data_dir)
    monkeypatch.setattr(sc.email_digest, "_site_url", lambda: "https://site.example")
    return tmp_path / "site" / "public"


def test_hero_and_audio_none_when_files_missing(site_root: Path) -> None:
    assert sc._hero("2026-10-26") == (None, None)
    assert sc._audio("2026-10-26") is None


def test_hero_prefers_png_and_audio_prefers_mp3(site_root: Path) -> None:
    img = site_root / "newspaper-img"
    img.mkdir(parents=True)
    (img / "2026-10-26.png").write_bytes(b"")
    (img / "2026-10-26.jpg").write_bytes(b"")
    audio = site_root / "audio"
    audio.mkdir(parents=True)
    (audio / "2026-10-26.wav").write_bytes(b"")
    assert sc._hero("2026-10-26") == (
        "https://site.example/newspaper-img/2026-10-26.png",
        "https://site.example/newspaper/2026-10-26/",
    )
    assert sc._audio("2026-10-26") == "https://site.example/audio/2026-10-26.wav"
    (audio / "2026-10-26.mp3").write_bytes(b"")
    assert sc._audio("2026-10-26") == "https://site.example/audio/2026-10-26.mp3"


# --- main ---------------------------------------------------------------------

class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return NOW if tz is None else NOW.astimezone(tz)


@pytest.fixture
def main_env(
    sent_file: Path, site_root: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    monkeypatch.setattr(sc, "datetime", _FixedDatetime)
    state: dict = {"items": [_item("k1", priority="S"), _item("k2")], "calls": {}}
    monkeypatch.setattr(sc, "read_processed", lambda d: state["items"] if d == "2026-10-26" else [])

    def recorder(name: str, result: bool):
        def _f(picked, **kwargs):
            state["calls"][name] = ([i.dedup_key for i in picked], kwargs)
            return result
        return _f

    state["recorder"] = recorder
    monkeypatch.setattr(sc.email_digest, "send_digest", recorder("email", True))
    monkeypatch.setattr(sc.slack_digest, "send_digest", recorder("slack", False))
    monkeypatch.setattr(sc.discord, "post_digest", recorder("discord", False))
    monkeypatch.setattr(sc.sys, "argv", ["send_catchup"])
    return state


def test_main_delivers_and_marks_sent(main_env: dict, sent_file: Path) -> None:
    sc.main()
    keys, kwargs = main_env["calls"]["email"]
    assert keys == ["k1", "k2"]
    assert kwargs["slot_label"] == "朝のニュース"  # JST 09:00 → morning
    assert kwargs["date_label"] == "10月26日"
    assert kwargs["hero_image_url"] is None and kwargs["audio_url"] is None
    assert main_env["calls"]["discord"][1]["site_url"] == "https://site.example"
    saved = json.loads(sent_file.read_text(encoding="utf-8"))
    assert set(saved) == {"k1", "k2", "__slot__:morning:2026-10-26"}


def test_main_uses_slot_from_argv(main_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.sys, "argv", ["send_catchup", "evening"])
    sc.main()
    assert main_env["calls"]["email"][1]["slot_label"] == "夕方のニュース"


def test_main_skips_when_slot_already_sent_today(main_env: dict, sent_file: Path) -> None:
    sent_file.parent.mkdir(parents=True, exist_ok=True)
    sent_file.write_text(
        json.dumps({"__slot__:morning:2026-10-26": NOW.isoformat()}), encoding="utf-8"
    )
    sc.main()
    assert main_env["calls"] == {}


def test_main_skips_when_nothing_to_send(main_env: dict, sent_file: Path) -> None:
    main_env["items"] = []
    sc.main()
    assert main_env["calls"] == {}
    assert not sent_file.exists()


def test_main_does_not_mark_sent_when_no_channel_delivered(
    main_env: dict, sent_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sc.email_digest, "send_digest", main_env["recorder"]("email", False))
    sc.main()
    assert set(main_env["calls"]) == {"email", "slack", "discord"}
    assert not sent_file.exists()
