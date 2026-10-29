"""Tests for src/admin/refilter_processed.py (Gemini / watchlist はすべてモック)."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.admin import refilter_processed as rp
from src.models import Flags, ProcessedItem


def _item(n: int, source_id: str, genre: str = "games") -> ProcessedItem:
    return ProcessedItem(
        source_id=source_id,
        raw_fingerprint=f"fp{n}",
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        url=f"https://example.com/{n}",
        author=f"author{n}",
        genre=genre,  # type: ignore[arg-type]
        subcategory_id="cat",
        category_name="Category",
        importance="B",
        summary=f"summary {n}",
        raw_text=f"raw {n}",
        flags=Flags(source_role="メディア"),
        dedup_key=f"key{n}",
    )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """processed_dir を tmp_path に、watchlist を固定値に差し替える。"""
    day_dir = tmp_path / "processed" / "2026-05-01"
    day_dir.mkdir(parents=True)
    monkeypatch.setattr(rp, "processed_dir", lambda date_str: day_dir)
    sources = [
        SimpleNamespace(id="media", source_type="メディア"),
        SimpleNamespace(id="official", source_type="公式"),
    ]
    monkeypatch.setattr(rp.watchlist, "load", lambda: sources)
    calls: list[dict] = []

    def install(responder):
        def fake_call_json(**kwargs):
            calls.append(kwargs)
            return responder(kwargs)

        monkeypatch.setattr(rp.llm_client, "call_json", fake_call_json)

    return SimpleNamespace(path=day_dir / "items.jsonl", calls=calls, install=install)


def _write(path: Path, items: list[ProcessedItem], extra_lines: list[str] | None = None) -> None:
    lines = [it.model_dump_json() for it in items] + (extra_lines or [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read(path: Path) -> list[ProcessedItem]:
    return [
        ProcessedItem.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_missing_file_returns_zero_without_llm(env):
    env.install(lambda kw: pytest.fail("LLM must not be called"))
    assert rp.main("2026-05-01") == 0
    assert not env.path.exists()


def test_drops_spam_and_neither_fixes_genre_and_keeps_non_media(env):
    items = [
        _item(1, "media", "games"),     # spam -> drop
        _item(2, "media", "games"),     # neither -> drop
        _item(3, "media", "games"),     # same genre -> keep
        _item(4, "media", "games"),     # anime -> genre fix
        _item(5, "official", "games"),  # non-media -> keep, no LLM
    ]
    _write(env.path, items, extra_lines=["{not json", ""])
    original = env.path.read_text(encoding="utf-8")

    verdicts = {
        "https://example.com/1": {"spam": True, "genre": "games", "confidence": 0.9},
        "https://example.com/2": {"spam": False, "genre": "neither", "confidence": 0.9},
        "https://example.com/3": {"spam": False, "genre": "games", "confidence": 0.9},
        "https://example.com/4": {"spam": False, "genre": "anime", "confidence": 0.9},
    }

    def responder(kw):
        for url, v in verdicts.items():
            if url in kw["user"]:
                return v
        raise AssertionError("unexpected item sent to LLM")

    env.install(responder)
    assert rp.main("2026-05-01") == 0

    # メディアの4件だけ LLM に送られる
    assert len(env.calls) == 4
    assert all(c["max_tokens"] == 256 for c in env.calls)

    result = _read(env.path)
    assert [it.raw_fingerprint for it in result] == ["fp3", "fp4", "fp5"]
    assert result[1].genre == "anime"
    assert result[2].genre == "games"

    # 元ファイルのバックアップが作られる (不正行も含め原文のまま)
    backup = env.path.with_suffix(".jsonl.bak")
    assert backup.read_text(encoding="utf-8") == original


def test_llm_failure_keeps_item(env):
    _write(env.path, [_item(1, "media")])

    def boom(kw):
        raise RuntimeError("quota")

    env.install(boom)
    assert rp.main("2026-05-01") == 0
    assert [it.raw_fingerprint for it in _read(env.path)] == ["fp1"]


def test_invalid_llm_payload_keeps_item(env):
    _write(env.path, [_item(1, "media")])
    env.install(lambda kw: {"genre": "games"})  # spam 欠落 -> FilterResult 失敗
    assert rp.main("2026-05-01") == 0
    assert [it.raw_fingerprint for it in _read(env.path)] == ["fp1"]


def test_existing_backup_is_not_overwritten(env):
    _write(env.path, [_item(1, "media")])
    backup = env.path.with_suffix(".jsonl.bak")
    backup.write_text("ORIGINAL BACKUP\n", encoding="utf-8")
    env.install(lambda kw: {"spam": True, "genre": "games", "confidence": 1.0})

    rp.main("2026-05-01")

    assert backup.read_text(encoding="utf-8") == "ORIGINAL BACKUP\n"
    assert _read(env.path) == []


def test_empty_file_is_left_untouched(env):
    env.path.write_text("\n", encoding="utf-8")
    env.install(lambda kw: pytest.fail("LLM must not be called"))
    assert rp.main("2026-05-01") == 0
    assert env.path.read_text(encoding="utf-8") == "\n"
    assert not env.path.with_suffix(".jsonl.bak").exists()


def _count_writes(monkeypatch: pytest.MonkeyPatch, target: Path) -> list[int]:
    """target を書き込みモードで開いた回数を記録する spy を仕込む"""
    writes: list[int] = []
    real_open = Path.open

    def spy_open(self, mode="r", *args, **kwargs):
        fh = real_open(self, mode, *args, **kwargs)
        if self == target and "w" in mode:
            writes.append(1)
        return fh

    monkeypatch.setattr(Path, "open", spy_open)
    return writes


def test_checkpoint_flush_writes_kept_plus_remainder(env, monkeypatch):
    """50 件ごとの checkpoint で kept + 未処理分が書き出される。"""
    items = [_item(i, "media") for i in range(52)]
    _write(env.path, items)
    original = env.path.read_text(encoding="utf-8")
    snapshots = _count_writes(monkeypatch, env.path)

    # 偶数番号は spam として落とす
    def responder(kw):
        n = int(kw["user"].split("https://example.com/")[1].split()[0])
        return {"spam": n % 2 == 0, "genre": "games", "confidence": 1.0}

    env.install(responder)
    rp.main("2026-05-01")

    # checkpoint (rechecked=50) で1回 + 最終書き戻しで1回
    assert len(snapshots) == 2
    result = _read(env.path)
    assert [it.raw_fingerprint for it in result] == [f"fp{i}" for i in range(52) if i % 2 == 1]
    # .bak は checkpoint で上書きされる前の元データであること
    assert env.path.with_suffix(".jsonl.bak").read_text(encoding="utf-8") == original


def test_checkpoint_flush_on_failure_path(env, monkeypatch):
    items = [_item(i, "media") for i in range(50)]
    _write(env.path, items)
    writes = _count_writes(monkeypatch, env.path)

    def boom(kw):
        raise RuntimeError("down")

    env.install(boom)
    rp.main("2026-05-01")
    # 失敗経路の checkpoint (rechecked=50) で1回 + 最終書き戻しで1回
    assert len(writes) == 2
    assert len(_read(env.path)) == 50


def test_backup_survives_interrupted_run(env):
    """checkpoint 後に落ちても .bak に元データが残る"""
    items = [_item(i, "media") for i in range(60)]
    _write(env.path, items)
    original = env.path.read_text(encoding="utf-8")

    def responder(kw):
        n = int(kw["user"].split("https://example.com/")[1].split()[0])
        if n == 55:
            raise KeyboardInterrupt  # 途中キャンセル相当 (Exception ではないので握られない)
        return {"spam": True, "genre": "games", "confidence": 1.0}

    env.install(responder)
    with pytest.raises(KeyboardInterrupt):
        rp.main("2026-05-01")
    # checkpoint で items.jsonl は途中結果 (kept 0 件 + 未処理 10 件) になっている
    assert len(_read(env.path)) == 10
    assert env.path.with_suffix(".jsonl.bak").read_text(encoding="utf-8") == original


def test_build_filter_user_includes_item_fields():
    it = _item(7, "media")
    text = rp._build_filter_user(it)
    assert "https://example.com/7" in text
    assert "author7" in text
    assert "summary 7" in text
