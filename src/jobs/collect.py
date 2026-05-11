"""Collection job: pulls raw items from sources matching a frequency tier.

Usage:
    python -m src.jobs.collect realtime
    python -m src.jobs.collect hourly
    python -m src.jobs.collect daily
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone

from .. import logger, watchlist
from ..collectors import (
    rss_generic,
    twitch_api,
    x_twscrape,
    youtube_rss,
    youtube_search,
    youtube_trending,
)
from ..storage import write_raw

log = logger.get(__name__)

# How far back to look on each tier (in hours)
LOOKBACK = {
    "realtime": 1,
    "hourly": 4,  # safety margin
    "6h": 8,
    "daily": 30,
}


def main(tier: str) -> None:
    if tier not in LOOKBACK:
        raise SystemExit(f"Unknown tier: {tier}. Use realtime/hourly/6h/daily")

    sources = watchlist.load()
    sources = watchlist.by_frequency(sources, tier)
    log.info(f"[{tier}] {len(sources)} sources to collect")

    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK[tier])
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    all_items = []
    for collector_name, collector in [
        ("youtube_rss", youtube_rss),
        ("youtube_search", youtube_search),
        ("youtube_trending", youtube_trending),
        ("twitch", twitch_api),
        ("rss", rss_generic),
        ("x", x_twscrape),
    ]:
        try:
            items = collector.collect(sources, since)
            log.info(f"[{tier}] {collector_name}: {len(items)} items")
            all_items.extend(items)
        except Exception as e:  # noqa: BLE001
            log.error(f"[{tier}] collector {collector_name} crashed: {e}")

    # Write per-source jsonl
    source_priority = {source.id: source.priority for source in sources}
    source_genre = {source.id: source.genre for source in sources}
    source_type = {source.id: source.source_type for source in sources}
    by_source: dict[str, list] = {}
    for it in all_items:
        it.extra.setdefault("source_priority", source_priority.get(it.source_id, "medium"))
        it.extra.setdefault("source_genre", source_genre.get(it.source_id, "neither"))
        it.extra.setdefault("source_type", source_type.get(it.source_id, it.account_type))
        by_source.setdefault(it.source_id, []).append(it)
    for sid, items in by_source.items():
        write_raw(date_str, sid, items)

    log.info(f"[{tier}] wrote {len(all_items)} items across {len(by_source)} sources")


if __name__ == "__main__":
    tier = sys.argv[1] if len(sys.argv) > 1 else "hourly"
    main(tier)
