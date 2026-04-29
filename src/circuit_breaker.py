"""Simple file-based circuit breakers."""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from . import logger
from .config import cache_dir

log = logger.get(__name__)
STATE_FILE = cache_dir() / "circuit_breakers.json"


def _load() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_open(name: str) -> bool:
    """Return True if breaker is open AND has not auto-reset yet."""
    # Manual reset via env
    reset = os.environ.get("BREAKER_RESET", "")
    if name in [r.strip() for r in reset.split(",")]:
        clear(name)
        log.info(f"Breaker {name} manually reset")
        return False

    state = _load().get(name)
    if not state or state.get("state") != "open":
        return False
    auto_reset_at = state.get("auto_reset_at")
    if auto_reset_at and datetime.utcnow().isoformat() >= auto_reset_at:
        clear(name)
        return False
    return True


def trip(name: str, reason: str, auto_reset_hours: int | None = None) -> None:
    state = _load()
    auto_reset_at = None
    if auto_reset_hours:
        auto_reset_at = (datetime.utcnow() + timedelta(hours=auto_reset_hours)).isoformat()
    state[name] = {
        "state": "open",
        "tripped_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "auto_reset_at": auto_reset_at,
    }
    _save(state)
    log.error(f"Circuit breaker tripped: {name} | {reason}")


def clear(name: str) -> None:
    state = _load()
    if name in state:
        del state[name]
    _save(state)
