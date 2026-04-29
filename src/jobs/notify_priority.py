"""Quick-classify recent raw items and notify high-importance ones to Discord.

This job runs more frequently than process_digest. It classifies only
the most recent batch and sends S/A items to the priority webhook.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from .. import dedup, logger
from ..outputs import discord
from ..processors import classify
from ..storage import read_raw

log = logger.get(__name__)
LOOKBACK_MINUTES = 45


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    raw_items = [it for it in read_raw(date_str) if it.timestamp >= cutoff]
    log.info(f"Notify check: {len(raw_items)} recent items")
    if not raw_items:
        return

    processed = classify.process(raw_items)
    fresh, _ = dedup.filter_new(processed)
    sa = [it for it in fresh if it.importance in ("S", "A")]
    log.info(f"S/A items to notify: {len(sa)}")

    sent = discord.notify_priority(sa)
    log.info(f"Sent {sent} notifications")


if __name__ == "__main__":
    main()
