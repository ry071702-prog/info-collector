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
    # 宛先は 2 方式に対応 (優先: webhook)。
    #  - SLACK_WEBHOOK_CATCHUP: Incoming Webhook (紐づく1チャンネルへ)
    #  - SLACK_BOT_TOKEN + SLACK_USER_ID: Bot Token で chat.postMessage (DM 可)
    #    日報自動生成 と同じ Bot を流用する想定。
    webhook = env("SLACK_WEBHOOK_CATCHUP")
    bot_token = env("SLACK_BOT_TOKEN")
    user_id = env("SLACK_USER_ID")
    if not webhook and not (bot_token and user_id):
        log.info("Slack 宛先未設定 (SLACK_WEBHOOK_CATCHUP または SLACK_BOT_TOKEN+SLACK_USER_ID); スキップ")
        return False

    blocks = build_blocks(items, slot_label=slot_label, date_label=date_label, audio_url=audio_url)
    text = f"☀ {slot_label} — 重要{len(items)}件"
    if is_dry_run():
        log.info(f"[DRY_RUN] Slack 投稿スキップ ({len(items)}件)")
        return False

    try:
        if webhook:
            httpx.post(webhook, json={"text": text, "blocks": blocks}, timeout=15.0).raise_for_status()
        else:
            resp = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": user_id, "text": text, "blocks": blocks},
                timeout=15.0,
            )
            data = resp.json()
            if not data.get("ok"):
                log.error(f"Slack chat.postMessage 失敗: {data.get('error')}")
                return False
    except Exception as e:  # noqa: BLE001
        log.error(f"Slack 投稿失敗: {e}")
        return False
    log.info(f"Slack 投稿: {slot_label} {len(items)}件 ({'webhook' if webhook else 'bot-token DM'})")
    return True
