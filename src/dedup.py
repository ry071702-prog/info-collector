"""Deduplication logic: dedup_key cache + cross-day awareness."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path

from . import logger
from .config import cache_dir
from .models import ProcessedItem

log = logger.get(__name__)
CACHE_FILE = cache_dir() / "dedup_keys.json"
WINDOW_DAYS = 7


def load_recent_keys() -> dict[str, str]:
    """{dedup_key: ISO timestamp} of recent items."""
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("dedup cache corrupted; starting fresh")
        return {}
    cutoff = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    return {k: v for k, v in data.items() if datetime.fromisoformat(v) >= cutoff}


def save_keys(keys: dict[str, str]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_new(items: list[ProcessedItem]) -> tuple[list[ProcessedItem], int]:
    """Drop items whose dedup_key is already known. Returns (kept, dropped_count)."""
    keys = load_recent_keys()
    kept: list[ProcessedItem] = []
    now_iso = datetime.utcnow().isoformat()
    for it in items:
        if it.dedup_key in keys:
            continue
        kept.append(it)
        keys[it.dedup_key] = now_iso
    save_keys(keys)
    return kept, len(items) - len(kept)
