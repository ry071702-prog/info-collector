"""YouTube RSS collector. Free, no API key needed."""
from __future__ import annotations
from datetime import datetime, timezone

import feedparser
import httpx

from .. import logger
from ..config import settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)


def _rss_url(handle: str) -> str:
    """handle is either UC... channel ID or full URL."""
    if handle.startswith("http"):
        return handle
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={handle}"


def _collect_channel(source: WatchSource, since: datetime) -> list[RawItem]:
    url = _rss_url(source.handle)
    try:
        resp = httpx.get(url, timeout=20.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.warning(f"YouTube RSS HTTP error for {source.handle}: {e.response.status_code}")
        return []
    except httpx.RequestError as e:
        log.warning(f"YouTube RSS network error for {source.handle}: {e}")
        return []

    feed = feedparser.parse(resp.text)
    limit = settings()["collectors"]["youtube"]["rss_entries_max"]
    items: list[RawItem] = []
    for entry in feed.entries[:limit]:
        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published < since:
            continue
        text = f"{entry.title}\n{getattr(entry, 'summary', '')}"
        items.append(
            RawItem(
                source_id=source.id,
                platform="YouTube",
                author=source.name,
                account_type=source.source_type,
                text=text,
                url=entry.link,
                timestamp=published,
                extra={"video_id": getattr(entry, "yt_videoid", "")},
            )
        )
    return items


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    yt_sources = [s for s in sources if s.platform == "YouTube"]
    out: list[RawItem] = []
    for s in yt_sources:
        try:
            out.extend(_collect_channel(s, since))
        except Exception as e:  # noqa: BLE001
            log.error(f"YouTube collection failed for {s.name}: {e}")
    return out
