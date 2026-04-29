"""Discord webhook notifier."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from .. import logger
from ..config import cache_dir, env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)
DEDUP_FILE = cache_dir() / "discord_sent.json"
DEDUP_WINDOW_HOURS = 24


def _load_sent() -> dict[str, str]:
    if not DEDUP_FILE.exists():
        return {}
    try:
        return json.loads(DEDUP_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_sent(d: dict[str, str]) -> None:
    cutoff = (datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)).isoformat()
    d = {k: v for k, v in d.items() if v >= cutoff}
    DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEDUP_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _format(item: ProcessedItem) -> str:
    badge = "🔥" if item.importance == "S" else "⭐"
    genre_emoji = "🎮" if item.genre == "games" else "📺"
    spoiler_tag = " [ネタバレ]" if item.flags.spoiler != "なし" else ""
    return (
        f"{badge}{genre_emoji} **{item.category_name}**{spoiler_tag}\n"
        f"{item.summary}\n"
        f"by {item.author} | <{item.url}>"
    )


def notify_priority(items: list[ProcessedItem]) -> int:
    """Send S/A items to priority webhook. Returns count sent."""
    webhook = env("DISCORD_WEBHOOK_PRIORITY")
    if not webhook:
        log.warning("DISCORD_WEBHOOK_PRIORITY not set; skipping")
        return 0

    sent = _load_sent()
    now_iso = datetime.utcnow().isoformat()
    cutoff = (datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)).isoformat()
    fresh = [it for it in items if it.dedup_key not in sent or sent.get(it.dedup_key, "") < cutoff]
    fresh = [it for it in fresh if it.importance in ("S", "A")]

    count = 0
    for it in fresh:
        content = _format(it)
        if is_dry_run():
            log.info(f"[DRY_RUN] would notify: {content[:80]}")
        else:
            try:
                httpx.post(webhook, json={"content": content}, timeout=15.0).raise_for_status()
            except Exception as e:  # noqa: BLE001
                log.error(f"Discord notify failed: {e}")
                continue
        sent[it.dedup_key] = now_iso
        count += 1
    _save_sent(sent)
    return count


def post_message(webhook_env_key: str, content: str) -> None:
    """Generic helper for ops/alerts channels."""
    webhook = env(webhook_env_key)
    if not webhook:
        log.warning(f"{webhook_env_key} not set; skipping post")
        return
    if is_dry_run():
        log.info(f"[DRY_RUN] would post to {webhook_env_key}: {content[:120]}")
        return
    try:
        httpx.post(webhook, json={"content": content[:1900]}, timeout=15.0).raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.error(f"Discord post to {webhook_env_key} failed: {e}")
