"""Generic RSS collector for media sites that aren't on YouTube."""
from __future__ import annotations
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx

from .. import logger
from ..models import RawItem, WatchSource

log = logger.get(__name__)

# default UA だと一部サイトで 403/404 を喰らうためブラウザ風 UA を明示
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _collect_feed(source: WatchSource, since: datetime) -> list[RawItem]:
    try:
        resp = httpx.get(
            source.url,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        log.warning(f"RSS error for {source.name}: {e}")
        return []
    feed = feedparser.parse(resp.text)
    items: list[RawItem] = []
    for entry in feed.entries[:30]:
        published_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if not published_struct:
            continue
        published = datetime.fromtimestamp(mktime(published_struct), tz=timezone.utc)
        if published < since:
            continue
        text = f"{entry.title}\n{getattr(entry, 'summary', '')}"
        items.append(
            RawItem(
                source_id=source.id,
                platform="RSS",
                author=source.name,
                account_type=source.source_type,
                text=text,
                url=entry.link,
                timestamp=published,
            )
        )
    return items


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    rss_sources = [s for s in sources if s.platform == "RSS"]
    out: list[RawItem] = []
    for s in rss_sources:
        try:
            out.extend(_collect_feed(s, since))
        except Exception as e:  # noqa: BLE001
            log.error(f"RSS collection failed for {s.name}: {e}")
    return out
