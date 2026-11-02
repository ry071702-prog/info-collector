"""2.5-flash の思考を切っているかのテスト

2.5-flash は思考が既定でオンで、思考トークンも max_output_tokens に数えられる
daily_digest (4096) は思考に約3,900 を使い切り、5月半ば以降のダイジェストが
数百文字で途中切れになっていた (2026-10-28 実測)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import llm_client


class _FakeModels:
    def __init__(self) -> None:
        self.configs: list = []

    def generate_content(self, *, model, contents, config):
        self.configs.append(config)
        return SimpleNamespace(text='{"ok": true}')


@pytest.fixture
def fake_models(monkeypatch):
    models = _FakeModels()
    monkeypatch.setattr(llm_client, "_api_keys", lambda: ["k"])
    monkeypatch.setattr(llm_client, "_client", lambda _key: SimpleNamespace(models=models))
    monkeypatch.setattr(llm_client, "_track_usage", lambda *_a: None)
    monkeypatch.setattr(llm_client, "_DEAD_KEYS", {})
    return models


@pytest.mark.parametrize("call", [llm_client.call_text, llm_client.call_json])
def test_flash_thinking_is_off(fake_models, call):
    call(model="gemini-2.5-flash", system="s", user="u")
    thinking = fake_models.configs[-1].thinking_config
    assert thinking is not None and thinking.thinking_budget == 0


@pytest.mark.parametrize("model", ["gemini-2.5-flash-lite", "gemini-2.5-pro"])
def test_other_models_keep_default_thinking(fake_models, model):
    """lite は既定でオフ  pro は 0 を受け付けない"""
    llm_client.call_text(model=model, system="s", user="u")
    assert fake_models.configs[-1].thinking_config is None
