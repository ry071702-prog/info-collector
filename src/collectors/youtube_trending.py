"""YouTube Data API v3 trending (mostPopular) collector.

watchlist 行例:
  TR001,JPゲーム急上昇,JP,https://example.invalid/?category=20,YouTubeTrending,games,メディア,"FF,D",high,TRUE,hourly,ja,...
  - handle = regionCode (JP / US)
  - url の "category=NN" でカテゴリ指定。20=Gaming, 1=Film&Animation, 24=Entertainment
  - url 省略時は全カテゴリ
"""
from __future__ import annotations
from datetime import datetime, timezone

import httpx

from .. import logger
from ..config import env, settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)
API_BASE = "https://www.googleapis.com/youtube/v3"


def _category_from_url(url: str) -> str | None:
    if not url or "category=" not in url:
        return None
    try:
        return url.split("category=")[1].split("&")[0].strip()
    except (IndexError, ValueError):
        return None


def _fetch(source: WatchSource, since: datetime, api_key: str) -> list[RawItem]:
    cfg = settings()["collectors"].get("youtube_trending", {})
    max_results = cfg.get("max_results", 30)
    region = source.handle.strip() or "JP"
    category_id = _category_from_url(source.url)

    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
        "key": api_key,
    }
    if category_id:
        params["videoCategoryId"] = category_id

    try:
        resp = httpx.get(f"{API_BASE}/videos", params=params, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        log.warning(
            f"YouTubeTrending HTTP error region={region} cat={category_id}: "
            f"{e.response.status_code} {e.response.text[:200]}"
        )
        return []
    except httpx.RequestError as e:
        log.warning(f"YouTubeTrending network error region={region}: {e}")
        return []

    items: list[RawItem] = []
    for entry in data.get("items", []):
        snip = entry.get("snippet", {}) or {}
        stats = entry.get("statistics", {}) or {}
        vid_id = entry.get("id")
        if not vid_id:
            continue
        try:
            published = datetime.fromisoformat(snip.get("publishedAt", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if published < since:
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
                    "found_via": "trending",
                    "region": region,
                    "category": category_id or "all",
                    "view_count": int(stats.get("viewCount", 0) or 0),
                    "like_count": int(stats.get("likeCount", 0) or 0),
                    "comment_count": int(stats.get("commentCount", 0) or 0),
                    "channel_id": snip.get("channelId", ""),
                },
            )
        )
    return items


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    api_key = env("YOUTUBE_API_KEY")
    trending = [s for s in sources if s.platform == "YouTubeTrending"]
    if not trending:
        return []
    if not api_key:
        log.info(
            f"YOUTUBE_API_KEY not configured; skipping YouTubeTrending ({len(trending)} sources待ち)"
        )
        return []
    out: list[RawItem] = []
    for s in trending:
        try:
            out.extend(_fetch(s, since, api_key))
        except Exception as e:  # noqa: BLE001
            log.error(f"YouTubeTrending failed for {s.id}: {e}")
    return out
