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
_configured = False


class QuotaExhausted(RuntimeError):
    """Gemini の日次クォータが枯渇したことを示す。リトライ対象外。"""


# 一度 429 を食らったモデルはそのプロセス内では再呼び出ししない。
_QUOTA_EXHAUSTED: set[str] = set()

# 一過性エラー（リトライ対象）。ResourceExhausted (=daily quota) は除外。
_TRANSIENT_EXC: tuple[type[Exception], ...] = (
    gx.InternalServerError,
    gx.ServiceUnavailable,
    gx.DeadlineExceeded,
    gx.TooManyRequests,
)


def quota_exhausted(model: str) -> bool:
    """そのプロセスで該当モデルがクォータ枯渇判定されているか。"""
    return model in _QUOTA_EXHAUSTED


def _guard_quota(model: str) -> None:
    if model in _QUOTA_EXHAUSTED:
        raise QuotaExhausted(f"Gemini daily quota exhausted for {model}")

# Per-model RPM limits (free tier as of 2025).
# Adjust if Google updates limits or you upgrade to paid tier.
RPM_LIMITS = {
    "gemini-2.0-flash": 15,
    "gemini-2.0-flash-lite": 30,
    "gemini-1.5-flash": 15,
    "gemini-1.5-flash-8b": 15,
    "gemini-1.5-pro": 2,
}
RPD_LIMITS = {
    "gemini-2.0-flash": 1500,
    "gemini-2.0-flash-lite": 1500,
    "gemini-1.5-flash": 1500,
    "gemini-1.5-flash-8b": 1500,
    "gemini-1.5-pro": 50,
}

_REQUEST_HISTORY: dict[str, deque] = {}


def _ensure_configured() -> None:
    global _configured
    if not _configured:
        genai.configure(api_key=env("GEMINI_API_KEY", required=True))
        _configured = True


def _throttle(model: str) -> None:
    """Sleep if we're about to exceed RPM."""
    rpm = RPM_LIMITS.get(model, 10)
    history = _REQUEST_HISTORY.setdefault(model, deque(maxlen=rpm))
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
    _ensure_configured()
    _throttle(model)
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
    except gx.ResourceExhausted as e:
        _QUOTA_EXHAUSTED.add(model)
        log.error(f"Gemini daily quota exhausted for {model}; subsequent calls will short-circuit")
        raise QuotaExhausted(str(e)) from e
    text = (resp.text or "").strip()
    _track_usage(model)
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
    _ensure_configured()
    _throttle(model)
    m = genai.GenerativeModel(model, system_instruction=system)
    try:
        resp = m.generate_content(
            user,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
        )
    except gx.ResourceExhausted as e:
        _QUOTA_EXHAUSTED.add(model)
        log.error(f"Gemini daily quota exhausted for {model}; subsequent calls will short-circuit")
        raise QuotaExhausted(str(e)) from e
    _track_usage(model)
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
def _track_usage(model: str) -> None:
    path = cache_dir() / "api_usage.jsonl"
    record = {"model": model, "timestamp": datetime.utcnow().isoformat()}
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
