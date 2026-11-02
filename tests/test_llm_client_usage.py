"""api_usage.jsonl にトークン数が残ること (料金を実測で出すための記録)。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import llm_client


@pytest.fixture
def usage_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(llm_client, "cache_dir", lambda: tmp_path)
    return tmp_path / "api_usage.jsonl"


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_track_usage_records_token_counts(usage_path: Path) -> None:
    resp = SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=1200, candidates_token_count=340, thoughts_token_count=None,
    ))
    llm_client._track_usage("gemini-2.5-flash", 0, resp)
    (rec,) = _records(usage_path)
    assert rec["model"] == "gemini-2.5-flash"
    assert rec["key_index"] == 1
    assert rec["prompt_tokens"] == 1200
    assert rec["output_tokens"] == 340
    assert rec["thinking_tokens"] == 0  # None は 0 として残す


def test_track_usage_without_metadata_keeps_old_format(usage_path: Path) -> None:
    llm_client._track_usage("gemini-2.5-flash-lite", 1)
    llm_client._track_usage("gemini-2.5-flash-lite", 1, SimpleNamespace())
    recs = _records(usage_path)
    assert [set(r) for r in recs] == [{"model", "key_index", "timestamp"}] * 2


def test_daily_request_count_still_counts_new_records(usage_path: Path) -> None:
    resp = SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=1, candidates_token_count=1, thoughts_token_count=1,
    ))
    llm_client._track_usage("gemini-2.5-flash", 0, resp)
    llm_client._track_usage("gemini-2.5-flash", 0)
    assert llm_client.daily_request_count() == {"gemini-2.5-flash": 2}
