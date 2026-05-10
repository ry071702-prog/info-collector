"""YouTube Data API v3 search collector. Discovers videos by keyword.

watchlist 行例:
  SR001,VTuber新作ゲーム,VTuber 新作ゲーム,,YouTubeSearch,games,メディア,"FF,A",high,TRUE,6h,ja,...
  - handle に検索クエリを書く
  - genre / source_type / subcategory_hints は通常通り
"""
from __future__ import annotations
from datetime import datetime, timezone

import httpx

from .. import logger
from ..config import env, settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)
API_BASE = "https://www.googleapis.com/youtube/v3"


def _collect_query(source: WatchSource, since: datetime, api_key: str) -> list[RawItem]:
    cfg = settings()["collectors"].get("youtube_search", {})
    max_results = cfg.get("max_results", 25)
    order = cfg.get("order", "date")  # date / relevance / viewCount

    region = "JP" if source.language == "ja" else "US"
    rel_lang = source.language if source.language in ("ja", "en") else "ja"

    params = {
        "part": "snippet",
        "q": source.handle,
        "type": "video",
        "maxResults": max_results,
        "order": order,
        "regionCode": region,
        "relevanceLanguage": rel_lang,
        "publishedAfter": since.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "key": api_key,
    }
    try:
        resp = httpx.get(f"{API_BASE}/search", params=params, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        log.warning(
            f"YouTubeSearch HTTP error '{source.handle}': {e.response.status_code} {e.response.text[:200]}"
        )
        return []
    except httpx.RequestError as e:
        log.warning(f"YouTubeSearch network error '{source.handle}': {e}")
        return []

    items: list[RawItem] = []
    for entry in data.get("items", []):
        snip = entry.get("snippet", {}) or {}
        vid_id = (entry.get("id") or {}).get("videoId")
        if not vid_id:
            continue
        try:
            published = datetime.fromisoformat(snip.get("publishedAt", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        text = f"{snip.get('title', '')}\n{snip.get('description', '')[:1500]}"
        items.append(
            RawItem(
                source_id=source.id,
                platform="YouTube",
                author=snip.get("channelTitle", "(unknown)"),
                account_type=source.source_type,
                text=text,
                url=f"https://www.youtube.com/watch?v={vid_id}",
                timestamp=published,
                extra={
                    "video_id": vid_id,
                    "search_query": source.handle,
                    "found_via": "search",
                    "channel_id": snip.get("channelId", ""),
                },
            )
        )
    return items


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    api_key = env("YOUTUBE_API_KEY")
    yt_search = [s for s in sources if s.platform == "YouTubeSearch"]
    if not yt_search:
        return []
    if not api_key:
        log.info(
            f"YOUTUBE_API_KEY not configured; skipping YouTubeSearch ({len(yt_search)} sources待ち)"
        )
        return []
    out: list[RawItem] = []
    for s in yt_search:
        try:
            out.extend(_collect_query(s, since, api_key))
        except Exception as e:  # noqa: BLE001
            log.error(f"YouTubeSearch failed for {s.id} '{s.handle}': {e}")
    return out
