"""キャッチアップ便を Slack Incoming Webhook に Block Kit で投稿する。

SLACK_WEBHOOK_CATCHUP が未設定なら何もしない (任意チャネル)。
"""
from __future__ import annotations

import httpx

from .. import logger
from ..config import env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)

_GENRE_EMOJI = {"games": "🎮", "anime": "📺", "disney": "🏰", "both": "🎮", "neither": "📰"}
_BADGE = {"S": "🔴重要S", "A": "🟠重要A", "B": "🟢B", "C": "⚪C"}


def _site_url() -> str:
    from .email_digest import _site_url as site

    return site()


def build_blocks(
    items: list[ProcessedItem],
    *,
    slot_label: str,
    date_label: str,
    audio_url: str | None = None,
) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"☀ {slot_label}", "emoji": True}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"{date_label} ・ 重要 {len(items)} 件"}],
        },
        {"type": "divider"},
    ]
    for it in items:
        emoji = _GENRE_EMOJI.get(it.genre, "📰")
        badge = _BADGE.get(it.final_priority, "⚪")
        title = it.category_name or "(無題)"
        summary = (it.summary or "")[:280]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *<{it.url}|{title}>*  {badge}\n{summary}",
                },
            }
        )
    actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "📰 サイトで全部見る", "emoji": True},
            "url": f"{_site_url()}/feed/",
        }
    ]
    if audio_url:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "▶ 1分で聴く", "emoji": True},
                "url": audio_url,
            }
        )
    blocks.append({"type": "divider"})
    blocks.append({"type": "actions", "elements": actions})
    return blocks


def send_digest(
    items: list[ProcessedItem],
    *,
    slot_label: str,
    date_label: str,
    audio_url: str | None = None,
) -> bool:
    webhook = env("SLACK_WEBHOOK_CATCHUP")
    if not webhook:
        log.info("SLACK_WEBHOOK_CATCHUP 未設定; Slack 投稿スキップ")
        return False
    blocks = build_blocks(items, slot_label=slot_label, date_label=date_label, audio_url=audio_url)
    payload = {"text": f"☀ {slot_label} — 重要{len(items)}件", "blocks": blocks}
    if is_dry_run():
        log.info(f"[DRY_RUN] Slack 投稿スキップ ({len(items)}件)")
        return False
    try:
        httpx.post(webhook, json=payload, timeout=15.0).raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.error(f"Slack 投稿失敗: {e}")
        return False
    log.info(f"Slack 投稿: {slot_label} {len(items)}件")
    return True
