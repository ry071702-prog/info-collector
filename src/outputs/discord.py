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


_GENRE_COLOR = {
    "games": 0x2997FF,
    "anime": 0xBF5AF2,
    "disney": 0xD6A11F,
    "both": 0x2997FF,
    "neither": 0x8E8E93,
}
_GENRE_LABEL = {"games": "ゲーム", "anime": "アニメ", "disney": "Disney", "both": "ゲーム/アニメ", "neither": "その他"}


def post_digest(
    items: list[ProcessedItem],
    *,
    slot_label: str,
    date_label: str,
    webhook_env_key: str = "DISCORD_WEBHOOK_CATCHUP",
    audio_url: str | None = None,
    site_url: str | None = None,
) -> bool:
    """キャッチアップ便を rich embed で投稿する。webhook 未設定なら False。"""
    webhook = env(webhook_env_key)
    if not webhook:
        log.info(f"{webhook_env_key} 未設定; Discord 投稿スキップ")
        return False

    embeds = []
    for it in items:
        badge = "🔴" if it.final_priority == "S" else "🟠" if it.final_priority == "A" else "🟢"
        embeds.append({
            "title": (it.category_name or "(無題)")[:240],
            "url": it.url,
            "description": (it.summary or "")[:300],
            "color": _GENRE_COLOR.get(it.genre, 0x8E8E93),
            "footer": {"text": f"{badge} {_GENRE_LABEL.get(it.genre, '')} ・ {it.author}"[:100]},
        })

    links = []
    if site_url:
        links.append(f"[📰 サイトで全部見る]({site_url}/feed/)")
    if audio_url:
        links.append(f"[▶ 1分で聴く]({audio_url})")
    header = f"# ☀ {slot_label}\n{date_label} ・ 重要 {len(items)} 件"
    if links:
        header += "\n" + " ・ ".join(links)

    if is_dry_run():
        log.info(f"[DRY_RUN] Discord digest 投稿スキップ ({len(items)}件)")
        return False
    try:
        httpx.post(webhook, json={"content": header, "embeds": embeds[:10]}, timeout=15.0).raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.error(f"Discord digest 投稿失敗: {e}")
        return False
    log.info(f"Discord digest 投稿: {slot_label} {len(items)}件")
    return True


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
