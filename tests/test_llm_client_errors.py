"""Tests for Gemini APIError handling (retry / quota fail-over).

2026-07-12 の障害の再発防止。google-genai の APIError は .code が HTTP ステータス (int)、
.status は 'RESOURCE_EXHAUSTED' 等の文字列。両者を取り違えて .status を数値と比較すると
TypeError になり、それが classify 側で握り潰されて全記事が捨てられていた。
"""
from __future__ import annotations

import pytest
from google.genai import errors as genai_errors

from src import llm_client


def _api_error(code: int, status: str, message: str = "boom", **extra) -> genai_errors.APIError:
    """SDK が実際に投げる形の APIError を組み立てる。"""
    err: dict = {"code": code, "status": status, "message": message}
    err.update(extra)
    return genai_errors.APIError(code, {"error": err})


def test_api_error_code_is_int_and_status_is_str():
    """SDK の前提。ここが崩れたらリトライ判定を作り直す必要がある。"""
    exc = _api_error(503, "UNAVAILABLE")
    assert exc.code == 503
    assert isinstance(exc.status, str)


@pytest.mark.parametrize("code,status", [(500, "INTERNAL"), (503, "UNAVAILABLE"), (504, "DEADLINE_EXCEEDED")])
def test_server_errors_are_retried(code: int, status: str):
    exc = _api_error(code, status)
    assert llm_client._is_server_error(exc)
    assert llm_client._should_retry(exc)


def test_transient_rate_limit_is_retried_not_key_killed():
    """RPM 超過の 429 は待てば回復する。キーを永久停止してはいけない。"""
    exc = _api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded for GenerateRequestsPerMinute")
    assert llm_client._is_rate_limited(exc)
    assert not llm_client._is_daily_quota_exhausted(exc)
    assert llm_client._should_retry(exc)


def test_daily_quota_is_not_retried_but_fails_over():
    """日次クォータ枯渇はリトライしても無駄。キー fail-over に回す。"""
    exc = _api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded for GenerateRequestsPerDayPerProject")
    assert llm_client._is_daily_quota_exhausted(exc)
    assert not llm_client._should_retry(exc)


def test_client_errors_are_not_retried():
    exc = _api_error(400, "INVALID_ARGUMENT")
    assert not llm_client._should_retry(exc)


def test_retry_predicates_never_raise_typeerror():
    """本丸。5xx/429 判定が例外を投げたら分類が全滅する (2026-07-12 の障害)。"""
    for code, status in [(429, "RESOURCE_EXHAUSTED"), (500, "INTERNAL"), (503, "UNAVAILABLE"), (400, "INVALID_ARGUMENT")]:
        exc = _api_error(code, status)
        llm_client._should_retry(exc)  # TypeError が出たらここで落ちる


def test_quota_exhausted_is_not_retried():
    """全キー枯渇時の QuotaExhausted は即座に諦める (リトライ対象外)。"""
    assert not llm_client._should_retry(llm_client.QuotaExhausted("dead"))


def test_call_json_retries_server_errors(monkeypatch: pytest.MonkeyPatch):
    """判定ロジックだけでなく、tenacity への配線が実際に効いているかを確認する。"""
    from tenacity import wait_none

    calls: list[int] = []

    class _FakeModels:
        def generate_content(self, **_kwargs):
            calls.append(1)
            raise _api_error(503, "UNAVAILABLE")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(llm_client, "_API_KEYS", ["k1"])
    monkeypatch.setattr(llm_client, "_DEAD_KEYS", {})
    monkeypatch.setattr(llm_client, "_client", lambda _key: _FakeClient())
    monkeypatch.setattr(llm_client, "_throttle", lambda *_a: None)
    monkeypatch.setattr(llm_client, "_configure_key", lambda *_a: None)
    monkeypatch.setattr(llm_client.call_json.retry, "wait", wait_none())

    with pytest.raises(genai_errors.APIError):
        llm_client.call_json(model="gemini-2.5-flash", system="s", user="u")

    assert len(calls) == 3, f"5xx が再試行されていない (呼び出し {len(calls)} 回)"


def test_call_json_fails_over_on_daily_quota(monkeypatch: pytest.MonkeyPatch):
    """日次枯渇は同じキーで粘らず、次のキーへ切り替えて成功する。"""
    used_keys: list[str] = []

    class _FakeModels:
        def __init__(self, key: str):
            self._key = key

        def generate_content(self, **_kwargs):
            used_keys.append(self._key)
            if self._key == "k1":
                raise _api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded ... PerDay ...")

            class _Resp:
                text = '{"ok": true}'

            return _Resp()

    monkeypatch.setattr(llm_client, "_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(llm_client, "_DEAD_KEYS", {})
    monkeypatch.setattr(llm_client, "_ACTIVE_KEY_IDX", 0)
    monkeypatch.setattr(llm_client, "_client", lambda key: type("C", (), {"models": _FakeModels(key)})())
    monkeypatch.setattr(llm_client, "_throttle", lambda *_a: None)
    monkeypatch.setattr(llm_client, "_configure_key", lambda *_a: None)
    monkeypatch.setattr(llm_client, "_track_usage", lambda *_a: None)

    assert llm_client.call_json(model="gemini-2.5-flash", system="s", user="u") == {"ok": True}
    assert used_keys == ["k1", "k2"], "枯渇したキーから次のキーへ fail-over していない"


def test_mark_key_exhausted_fails_over_then_raises(monkeypatch: pytest.MonkeyPatch):
    """キーが複数あれば次のキーへ、全滅したら QuotaExhausted。"""
    monkeypatch.setattr(llm_client, "_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(llm_client, "_DEAD_KEYS", {})
    exc = _api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded ... PerDay")

    llm_client._mark_key_exhausted("gemini-2.5-flash", 0, exc)  # 1本目が死んでも継続
    assert not llm_client.quota_exhausted("gemini-2.5-flash")

    with pytest.raises(llm_client.QuotaExhausted):
        llm_client._mark_key_exhausted("gemini-2.5-flash", 1, exc)  # 2本目も死ぬ = 全滅
