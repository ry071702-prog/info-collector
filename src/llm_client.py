"""Google Gemini API wrapper with retry, JSON parsing, throttle."""
from __future__ import annotations
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception,
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

# 日次クォータ枯渇を示す 429 の quota id。分次 (PerMinute) のレート制限と区別する。
_DAILY_QUOTA_MARKERS = ("perday", "per day", "per_day")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
        _CONFIGURED_KEY_IDX = key_idx


# genai.Client はキーごとに1つだけ生成して使い回す。
# 呼び出し毎に生成すると新SDK (google-genai) では、前の Client が GC される際に
# 内部 httpx クライアントが閉じられ、以降のリクエストが
# "Cannot send a request, as the client has been closed" で全件失敗する
# (2026-07-03 の旧SDK→新SDK移行で発生し、分類が全滅→processed 停止→通知が止まった)。
_CLIENTS: dict[str, genai.Client] = {}


def _client(api_key: str) -> genai.Client:
    client = _CLIENTS.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key)
        _CLIENTS[api_key] = client
    return client


def _is_rate_limited(exc: BaseException) -> bool:
    """429 (レート制限 or 日次クォータ枯渇)。

    APIError の .code が HTTP ステータス (int)。.status は 'RESOURCE_EXHAUSTED' 等の
    文字列なので数値比較してはいけない。
    """
    return isinstance(exc, genai_errors.APIError) and exc.code == 429


def _is_daily_quota_exhausted(exc: BaseException) -> bool:
    """429 のうち日次クォータ枯渇のもの。キーを切り替えても即座には回復しない。

    分次レート制限 (RPM 超過) は待てば回復するので、ここでは弾く。判別できない 429 は
    「一時的」側に倒す (キーを永久停止して全滅させるより、待って再試行する方が安全)。
    """
    if not _is_rate_limited(exc):
        return False
    details = str(getattr(exc, "details", "") or exc).lower()
    return any(marker in details for marker in _DAILY_QUOTA_MARKERS)


def _is_server_error(exc: BaseException) -> bool:
    return isinstance(exc, genai_errors.APIError) and (exc.code or 0) >= 500


def _should_retry(exc: BaseException) -> bool:
    """5xx と、日次枯渇でない 429 だけリトライする。QuotaExhausted は対象外。"""
    return _is_server_error(exc) or (_is_rate_limited(exc) and not _is_daily_quota_exhausted(exc))


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
    retry=retry_if_exception(_should_retry),
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
        try:
            resp = _client(api_key).models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
            break
        except genai_errors.APIError as e:
            if _is_daily_quota_exhausted(e):
                _mark_key_exhausted(model, key_idx, e)
                continue
            # 5xx と一時的な 429 は tenacity (_should_retry) が指数バックオフで再試行する
            raise
    text = (resp.text or "").strip()
    _track_usage(model, key_idx)
    return _parse_json(text)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
    retry=retry_if_exception(_should_retry),
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
        try:
            resp = _client(api_key).models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            break
        except genai_errors.APIError as e:
            if _is_daily_quota_exhausted(e):
                _mark_key_exhausted(model, key_idx, e)
                continue
            # 5xx と一時的な 429 は tenacity (_should_retry) が指数バックオフで再試行する
            raise
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
        "timestamp": _utc_now().isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def daily_request_count() -> dict[str, int]:
    """Today's request count per model."""
    path = cache_dir() / "api_usage.jsonl"
    if not path.exists():
        return {}
    today = _utc_now().strftime("%Y-%m-%d")
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
