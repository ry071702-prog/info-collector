"""状態ファイルの atomic 書き込み。

dedup_keys / discord_sent / circuit_breakers 等は、書き込み中に落ちると壊れた JSON が残る。
読み手はどれも「壊れていたら {} から開始」にフォールバックするため、**状態を丸ごと失って
静かに誤動作する** (通知済みの記事を再通知する / 開いていたブレーカーが閉じる)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.storage import write_json_atomic


def test_write_json_atomic_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    write_json_atomic(path, {"k": "2026-07-13T00:00:00+00:00"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "2026-07-13T00:00:00+00:00"}


def test_crash_midwrite_keeps_previous_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """書き込み中に落ちても、既存の状態が壊れない (これが atomic の本体)。"""
    path = tmp_path / "state.json"
    write_json_atomic(path, {"old": "keep"})

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        write_json_atomic(path, {"new": "lost"})

    # 旧状態は無傷で読める (途中まで書かれた JSON で上書きされていない)
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": "keep"}
    # 一時ファイルも残さない
    assert list(tmp_path.iterdir()) == [path]


def test_no_partial_file_left_behind(tmp_path: Path):
    """シリアライズ不能なデータでも、既存ファイルを壊さず一時ファイルも残さない。"""
    path = tmp_path / "state.json"
    write_json_atomic(path, {"old": "keep"})

    with pytest.raises(TypeError):
        write_json_atomic(path, {"bad": object()})  # JSON にできない

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": "keep"}
    assert list(tmp_path.iterdir()) == [path]
