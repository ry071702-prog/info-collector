"""Quick-classify recent raw items and notify high-importance ones to Discord.

This job runs more frequently than process_digest. It classifies only
the most recent batch and sends S/A items to the priority webhook.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from .. import logger
from ..outputs import discord
from ..processors import classify
from ..storage import read_raw

log = logger.get(__name__)
LOOKBACK_MINUTES = 45


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    raw_items = [it for it in read_raw(date_str) if it.timestamp >= cutoff]
    log.info(f"Notify check: {len(raw_items)} recent items")
    if not raw_items:
        return

    processed = classify.process(raw_items)
    # ここで dedup.filter_new は呼ばない。あれは副作用で dedup_keys.json に全記事のキーを
    # 登録するため、後続の process_digest が同じ記事を「重複」として捨ててしまう
    # (通知自体の重複抑制は discord.notify_priority が discord_sent.json で 24h 単位に行う)。
    # importance S/A だけ拾い、risk_level=high は確認待ちなので priority 通知から除外
    sa = [it for it in processed if it.importance in ("S", "A") and it.risk_level != "high"]
    suppressed = sum(1 for it in processed if it.importance in ("S", "A") and it.risk_level == "high")
    log.info(f"S/A items to notify: {len(sa)} (suppressed {suppressed} high-risk)")

    sent = discord.notify_priority(sa)
    log.info(f"Sent {sent} notifications")


if __name__ == "__main__":
    main()
