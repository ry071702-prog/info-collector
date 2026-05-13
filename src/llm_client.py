"""Google Gemini API wrapper with retry, JSON parsing, throttle."""
from __future__ import annotations
import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Any

import google.generativeai as genai
from google.api_core import exceptions as gx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from . import logger
from .config import cache_dir, env

log = logger.get(__name__)


class QuotaExhausted(RuntimeError):
    """Gemini の日次クォータが枯渇したことを示す。リトライ対象外。"""


# モデルごとに 429 を食らったキー index を記録し、生きているキーへ fail-over する。
_API_KEYS: list[str] | None = None
_ACTIVE_KEY_IDX = 0
_CONFIGURED_KEY_IDX: int | None = None
_DEAD_KEYS: dict[str, set[int]] = {}

# 一過性エラー（リトライ対象）。ResourceExhausted (=daily quota) は除外。
_TRANSIENT_EXC: tuple[type[Exception], ...] = (
    gx.InternalServerError,
    gx.ServiceUnavailable,
    gx.DeadlineExceeded,
    gx.TooManyRequests,
)


def quota_exhausted(model: str) -> bool:
    """そのプロセスで該当モデルがクォータ枯渇判定されているか。"""
    keys = _api_keys()
    return bool(keys) and len(_DEAD_KEYS.get(model, set())) >= len(keys)


def _guard_quota(model: str) -> None:
    if quota_exhausted(model):
        raise QuotaExhausted(f"Gemini daily quota exhausted for {model}")

# Per-model RPM limits.
# 2.5 系 (paid tier) は実質ほぼ無制限だが、過剰呼び出し防止のため抑えめに設定。
RPM_LIMITS = {
    "gemini-2.5-flash": 1000,
    "gemini-2.5-flash-lite": 4000,
    "gemini-2.5-pro": 150,
    # legacy (互換用、新規発行 key では使えない)
    "gemini-2.0-flash": 15,
    "gemini-2.0-flash-lite": 30,
    "gemini-1.5-flash": 15,
    "gemini-1.5-flash-8b": 15,
    "gemini-1.5-pro": 2,
}
RPD_LIMITS = {
    "gemini-2.5-flash": 1000000,
    "gemini-2.5-flash-lite": 1000000,
    "gemini-2.5-pro": 10000,
    "gemini-2.0-flash": 1500,
    "gemini-2.0-flash-lite": 1500,
    "gemini-1.5-flash": 1500,
    "gemini-1.5-flash-8b": 1500,
    "gemini-1.5-pro": 50,
}

_REQUEST_HISTORY: dict[tuple[str, int], deque] = {}


def _api_keys() -> list[str]:
    global _API_KEYS
    if _API_KEYS is None:
        primary = env("GEMINI_API_KEY", required=True)
        _API_KEYS = [
            key
            for key in (
                primary,
                env("GEMINI_API_KEY_2", ""),
                env("GEMINI_API_KEY_3", ""),
            )
            if key
        ]
    return _API_KEYS


def _next_api_key(model: str) -> tuple[int, str]:
    global _ACTIVE_KEY_IDX
    keys = _api_keys()
    dead = _DEAD_KEYS.setdefault(model, set())
    if len(dead) >= len(keys):
        raise QuotaExhausted(f"Gemini daily quota exhausted for {model} on all API keys")

    for offset in range(len(keys)):
        idx = (_ACTIVE_KEY_IDX + offset) % len(keys)
        if idx not in dead:
            _ACTIVE_KEY_IDX = idx
            return idx, keys[idx]
    raise QuotaExhausted(f"Gemini daily quota exhausted for {model} on all API keys")


def _configure_key(key_idx: int, api_key: str) -> None:
    global _CONFIGURED_KEY_IDX
    if _CONFIGURED_KEY_IDX != key_idx:
        genai.configure(api_key=api_key)
        _CONFIGURED_KEY_IDX = key_idx


def _mark_key_exhausted(model: str, key_idx: int, exc: Exception) -> None:
    global _ACTIVE_KEY_IDX
    _DEAD_KEYS.setdefault(model, set()).add(key_idx)
    keys = _api_keys()
    log.error(
        f"Gemini daily quota exhausted for {model} on key #{key_idx + 1}; "
        f"{len(keys) - len(_DEAD_KEYS[model])} key(s) remain"
    )
    if len(_DEAD_KEYS[model]) >= len(keys):
        raise QuotaExhausted(str(exc)) from exc
    _ACTIVE_KEY_IDX = (key_idx + 1) % len(keys)


def _throttle(model: str, key_idx: int) -> None:
    """Sleep if we're about to exceed RPM."""
    rpm = RPM_LIMITS.get(model, 10)
    history = _REQUEST_HISTORY.setdefault((model, key_idx), deque(maxlen=rpm))
    now = time.time()
    if len(history) >= rpm:
        oldest = history[0]
        wait = 60.0 - (now - oldest)
        if wait > 0:
            log.info(f"RPM throttle: sleeping {wait:.1f}s for {model}")
            time.sleep(wait + 0.5)
    history.append(time.time())


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
    retry=retry_if_exception_type(_TRANSIENT_EXC),
    reraise=True,
)
def call_json(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Single Gemini call returning parsed JSON."""
    _guard_quota(model)
    while True:
        key_idx, api_key = _next_api_key(model)
        _configure_key(key_idx, api_key)
        _throttle(model, key_idx)
        m = genai.GenerativeModel(model, system_instruction=system)
        try:
            resp = m.generate_content(
                user,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                },
            )
            break
        except gx.ResourceExhausted as e:
            _mark_key_exhausted(model, key_idx, e)
    text = (resp.text or "").strip()
    _track_usage(model, key_idx)
    return _parse_json(text)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
    retry=retry_if_exception_type(_TRANSIENT_EXC),
    reraise=True,
)
def call_text(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Single Gemini call returning plain text."""
    _guard_quota(model)
    while True:
        key_idx, api_key = _next_api_key(model)
        _configure_key(key_idx, api_key)
        _throttle(model, key_idx)
        m = genai.GenerativeModel(model, system_instruction=system)
        try:
            resp = m.generate_content(
                user,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            break
        except gx.ResourceExhausted as e:
            _mark_key_exhausted(model, key_idx, e)
    _track_usage(model, key_idx)
    return resp.text or ""


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction."""
    text = text.strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


# ---- Usage tracking (request count vs free quota) ----
def _track_usage(model: str, key_idx: int) -> None:
    path = cache_dir() / "api_usage.jsonl"
    record = {
        "model": model,
        "key_index": key_idx + 1,
        "timestamp": datetime.utcnow().isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def daily_request_count() -> dict[str, int]:
    """Today's request count per model."""
    path = cache_dir() / "api_usage.jsonl"
    if not path.exists():
        return {}
    today = datetime.utcnow().strftime("%Y-%m-%d")
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("timestamp", "").startswith(today):
                counts[r["model"]] = counts.get(r["model"], 0) + 1
    return counts


def quota_status() -> dict[str, dict]:
    """Today's usage vs free quota."""
    counts = daily_request_count()
    out = {}
    for model, used in counts.items():
        limit = RPD_LIMITS.get(model, 0)
        out[model] = {
            "used": used,
            "limit": limit,
            "pct": (used / limit * 100) if limit else 0,
        }
    return out
