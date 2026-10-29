"""process_digest ジョブのテスト。

外部出力 (Notion / Sheets / Discord) と Gemini 分類はすべて monkeypatch で差し替え、
ファイル I/O は tmp_path 配下に閉じ込める。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import outbox
from src.jobs import process_digest as pd
from src.models import Flags, ProcessedItem, RawItem

NOW = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)  # JST 12:00 → AM


def _raw(url: str, ts: datetime = NOW - timedelta(hours=1)) -> RawItem:
    return RawItem(
        source_id="src1",
        platform="RSS",
        author="author",
        account_type="公式",
        text="text",
        url=url,
        timestamp=ts,
    )


def _processed(key: str, entity_tags: list[str] | None = None) -> ProcessedItem:
    return ProcessedItem(
        source_id="src1",
        raw_fingerprint=key,
        timestamp=NOW,
        url=key,
        author="author",
        genre="games",
        subcategory_id="cat1",
        category_name="Category",
        importance="A",
        summary=f"summary of {key}",
        entity_tags=entity_tags or [],
        flags=Flags(source_role="公式"),
        dedup_key=key,
    )


def _as_processed(chunk: list[RawItem]) -> list[ProcessedItem]:
    return [_processed(it.url) for it in chunk]


class Recorder:
    """外部出力の呼び出しを記録する差し替え群。"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.sheets: list[list[ProcessedItem]] = []
        self.notion: list[list[ProcessedItem]] = []
        self.written: list[tuple[str, list[ProcessedItem]]] = []
        self.digests: list[tuple[str, str, str]] = []


@pytest.fixture
def env(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """process_digest の外部依存をすべて差し替えた環境。"""
    rec = Recorder()
    raw_by_date: dict[str, list[RawItem]] = {}

    monkeypatch.setattr(pd, "RUN_HISTORY_PATH", tmp_cache_dir / "process_digest_runs.json")
    monkeypatch.setenv("PROCESS_AS_OF", NOW.isoformat())
    monkeypatch.setattr(pd, "settings", lambda: {"batch_sizes": {"classify_batch": 2}})
    monkeypatch.setattr(pd, "read_raw", lambda d: raw_by_date.get(d, []))
    monkeypatch.setattr(pd, "write_processed", lambda d, items: rec.written.append((d, list(items))))
    monkeypatch.setattr(pd.dedup, "recent_raw_fingerprints", lambda days: set())
    monkeypatch.setattr(pd.dedup, "filter_new", lambda items: (list(items), 0))
    monkeypatch.setattr(pd.classify, "process", _as_processed)

    def _sheets(items):
        rec.sheets.append(list(items))
        return len(items), []

    def _notion(items):
        rec.notion.append(list(items))
        return len(items), []

    monkeypatch.setattr(pd.sheets, "append", _sheets)
    monkeypatch.setattr(pd.notion, "write", _notion)
    monkeypatch.setattr(pd.digest, "daily_digest", lambda items, label: f"digest {label} {len(items)}")
    monkeypatch.setattr(pd.digest, "cross_source_trends", lambda items, min_count, top_n: [])

    def _write_digest(date, content, phase):
        rec.digests.append((date, content, phase))
        return Path(f"/tmp/{date}-{phase}.md")

    monkeypatch.setattr(pd.markdown, "write_digest", _write_digest)
    monkeypatch.setattr(pd.discord, "post_message", lambda hook, msg: rec.messages.append((hook, msg)))

    rec.raw_by_date = raw_by_date  # type: ignore[attr-defined]
    rec.cache_dir = tmp_cache_dir  # type: ignore[attr-defined]
    return rec


# --- helpers ---------------------------------------------------------------


def test_phase_am_pm_boundaries():
    # JST 06:00 は AM、JST 18:00 は PM、JST 05:59 は PM (前日扱いではなく当日日付)
    assert pd._phase(datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)) == ("2026-10-26", "AM")
    assert pd._phase(datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)) == ("2026-10-26", "PM")
    assert pd._phase(datetime(2026, 10, 25, 20, 59, tzinfo=timezone.utc)) == ("2026-10-26", "PM")


def test_read_raw_window_filters_by_timestamp_across_days(monkeypatch: pytest.MonkeyPatch):
    start = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 26, 4, 0, tzinfo=timezone.utc)
    by_date = {
        "2026-10-25": [
            _raw("in-25", datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)),
            _raw("before", datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)),
        ],
        "2026-10-26": [
            _raw("naive-in", datetime(2026, 10, 26, 1, 0)),  # tz なしは UTC とみなす
            _raw("jst-in", datetime(2026, 10, 26, 12, 0, tzinfo=timezone(timedelta(hours=9)))),
            _raw("after", datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc)),
        ],
    }
    called: list[str] = []

    def _read(d):
        called.append(d)
        return by_date.get(d, [])

    monkeypatch.setattr(pd, "read_raw", _read)
    got = [it.url for it in pd._read_raw_window(start, end)]
    assert got == ["in-25", "naive-in", "jst-in"]
    assert called == ["2026-10-25", "2026-10-26"]


def test_save_run_record_counts_consecutive_zero_runs_ignoring_empty_windows(env):
    assert pd._save_run_record(classified=0, raw_window_count=5, stopped_early=False) == 1
    # raw 0 件の run は「処理対象なし」なのでカウントを途切れさせない
    assert pd._save_run_record(classified=0, raw_window_count=0, stopped_early=False) == 1
    assert pd._save_run_record(classified=0, raw_window_count=3, stopped_early=False) == 2
    assert pd._save_run_record(classified=4, raw_window_count=3, stopped_early=False) == 0
    history = pd._load_run_history()
    assert [r["classified"] for r in history] == [4, 0, 0, 0]


def test_save_run_record_keeps_at_most_10(env):
    for _ in range(12):
        pd._save_run_record(classified=1, raw_window_count=1, stopped_early=False)
    assert len(pd._load_run_history()) == 10


def test_load_run_history_tolerates_broken_or_non_list(env):
    path: Path = pd.RUN_HISTORY_PATH
    path.write_text("{broken", encoding="utf-8")
    assert pd._load_run_history() == []
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert pd._load_run_history() == []


def test_flush_outbox_resends_and_keeps_failures(env, monkeypatch: pytest.MonkeyPatch):
    a, b = _processed("a"), _processed("b")
    outbox.add("notion", [a, b])
    outbox.add("sheets", [a])

    monkeypatch.setattr(pd.notion, "write", lambda items: (1, [b]))

    def _boom(items):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(pd.sheets, "append", _boom)
    totals = {"resent": 0}
    pd._flush_outbox(totals)

    assert totals["resent"] == 1
    assert [it.dedup_key for it in outbox.load("notion")] == ["b"]
    # 例外時はキューを残したまま次回へ持ち越す
    assert [it.dedup_key for it in outbox.load("sheets")] == ["a"]


# --- main ------------------------------------------------------------------


def test_main_no_raw_items_returns_without_side_effects(env):
    pd.main()
    assert env.messages == []
    assert env.written == []
    assert not pd.RUN_HISTORY_PATH.exists()


def test_main_happy_path_writes_outputs_digest_and_heartbeat(env):
    env.raw_by_date["2026-10-26"] = [_raw(f"u{i}") for i in range(3)] + [_raw("u0")]  # u0 は重複

    pd.main()

    # chunk_size=2 → 3件 (重複除去後) は 2 chunk
    assert [len(items) for _, items in env.written] == [2, 1]
    assert all(d == "2026-10-26" for d, _ in env.written)
    assert [len(c) for c in env.sheets] == [2, 1]
    assert [len(c) for c in env.notion] == [2, 1]
    assert env.digests == [("2026-10-26", "digest 2026-10-26 AM 3", "AM")]
    hooks = [h for h, _ in env.messages]
    assert hooks == ["DISCORD_WEBHOOK_OPS"]
    assert env.messages[0][1].startswith("✅ 12h digest (2026-10-26-AM): 3件処理")
    assert pd._load_run_history()[0]["classified"] == 3


def test_main_skips_already_processed_fingerprints(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("done"), _raw("new")]
    monkeypatch.setattr(pd.dedup, "recent_raw_fingerprints", lambda days: {"done"})

    pd.main()

    assert [it.url for _, items in env.written for it in items] == ["new"]


def test_main_output_failures_go_to_outbox(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("x"), _raw("y")]

    def _boom(items):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(pd.sheets, "append", _boom)
    monkeypatch.setattr(pd.notion, "write", lambda items: (1, [items[1]]))

    pd.main()

    assert sorted(it.dedup_key for it in outbox.load("sheets")) == ["x", "y"]
    assert [it.dedup_key for it in outbox.load("notion")] == ["y"]
    assert "Notion 1 / Sheets 0" in env.messages[-1][1]


def test_main_notion_exception_queues_whole_chunk(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("x")]

    def _boom(items):
        raise RuntimeError("notion down")

    monkeypatch.setattr(pd.notion, "write", _boom)
    pd.main()
    assert [it.dedup_key for it in outbox.load("notion")] == ["x"]


def test_main_all_duplicates_raises_classification_broken(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("x")]
    monkeypatch.setattr(pd.dedup, "filter_new", lambda items: ([], len(items)))

    # 分類はできているが dedup で全落ち → classified=0 なので SystemExit
    with pytest.raises(SystemExit, match="classified 0 items out of 1"):
        pd.main()
    assert env.written == []
    assert env.digests == []


def test_main_early_stop_on_consecutive_empty_chunks(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw(f"u{i}") for i in range(6)]
    calls: list[int] = []

    def _empty(chunk):
        calls.append(len(chunk))
        return []

    monkeypatch.setattr(pd.classify, "process", _empty)

    pd.main()  # early stop は既知の劣化なので SystemExit しない

    assert calls == [2, 2]  # 2 連続空で 3 chunk 目に進まない
    assert env.digests == []
    assert "⚠️" in env.messages[-1][1] and "quota切れで途中停止" in env.messages[-1][1]
    assert pd._load_run_history()[0]["stopped_early"] is True


def test_main_alerts_after_two_consecutive_zero_runs(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw(f"u{i}") for i in range(4)]
    monkeypatch.setattr(pd.classify, "process", lambda chunk: [])

    pd.main()
    assert not any(h == "DISCORD_WEBHOOK_ALERTS" for h, _ in env.messages)
    pd.main()
    alerts = [m for h, m in env.messages if h == "DISCORD_WEBHOOK_ALERTS"]
    assert len(alerts) == 1 and "2 回連続" in alerts[0]


def test_main_posts_cross_source_trends(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("t1")]
    sample = _processed("t1")
    monkeypatch.setattr(
        pd.digest, "cross_source_trends", lambda items, min_count, top_n: [("GameX", 3, [sample])]
    )

    pd.main()

    trend_msgs = [m for _, m in env.messages if "横断トレンド" in m]
    assert len(trend_msgs) == 1
    assert "**GameX** (3件) — summary of t1" in trend_msgs[0]


def test_main_digest_failure_does_not_abort(env, monkeypatch: pytest.MonkeyPatch):
    env.raw_by_date["2026-10-26"] = [_raw("x")]

    def _boom(items, label):
        raise RuntimeError("quota")

    monkeypatch.setattr(pd.digest, "daily_digest", _boom)
    pd.main()
    assert env.digests == []
    assert env.messages[-1][1].startswith("✅")


def test_main_invalid_process_as_of_falls_back_to_now(env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROCESS_AS_OF", "not-a-date")
    seen: list[str] = []
    monkeypatch.setattr(pd, "read_raw", lambda d: seen.append(d) or [])
    # main() の実行中に UTC の日付が変わっても落ちないよう、前後どちらの日付も許容する
    before = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pd.main()
    after = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert before in seen or after in seen


def test_main_naive_process_as_of_is_treated_as_utc(env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROCESS_AS_OF", "2026-10-26T03:00:00")
    env.raw_by_date["2026-10-26"] = [_raw("x")]
    pd.main()
    assert env.digests and env.digests[0][2] == "AM"
