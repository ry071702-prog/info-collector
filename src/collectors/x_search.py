"""X (Twitter) search collector via twscrape.

watchlist 行例:
  XS001,X検索: 釈迦×新作ゲーム,釈迦 新作ゲーム,,XSearch,games,メディア,"D,A",high,TRUE,daily,ja,...
  - handle に検索クエリを書く (例: 釈迦 新作ゲーム / "k4sen" AND "同接")
  - X_ACCOUNTS 未設定時は graceful skip
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

from .. import circuit_breaker, logger
from ..config import env_json, settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)
BREAKER = "x_search"


async def _ensure_pool():
    """Initialize twscrape API pool with accounts from env."""
    from twscrape import API

    api = API()
    accounts = env_json("X_ACCOUNTS", default=[])
    if not accounts:
        raise RuntimeError("X_ACCOUNTS not configured")
    existing = {a.username async for a in api.pool.accounts_info()}
    for acc in accounts:
        if acc["username"] not in existing:
            await api.pool.add_account(
                acc["username"],
                acc["password"],
                acc["email"],
                acc["email_password"],
            )
    await api.pool.login_all()
    return api


async def _collect_query(api, source: WatchSource, since: datetime) -> list[RawItem]:
    from twscrape import gather

    cfg = settings()["collectors"].get("x_search", {})
    limit = int(cfg.get("results_per_query", 30))
    tweets = await gather(api.search(source.handle, limit=limit))
    items: list[RawItem] = []
    for t in tweets:
        ts = t.date.replace(tzinfo=timezone.utc)
        if ts < since:
            continue
        text = t.rawContent
        if t.media and t.media.photos:
            text += "\n[image]"
        if t.media and t.media.videos:
            text += "\n[video]"
        items.append(
            RawItem(
                source_id=source.id,
                platform="X",
                author=getattr(t.user, "username", "") or "(unknown)",
                account_type=source.source_type,
                text=text,
                url=f"https://x.com/{getattr(t.user, 'username', 'i')}/status/{t.id}",
                timestamp=ts,
                extra={
                    "search_query": source.handle,
                    "found_via": "x_search",
                    "tweet_id": str(t.id),
                    "retweet_count": getattr(t, "retweetCount", 0),
                    "like_count": getattr(t, "likeCount", 0),
                    "reply_count": getattr(t, "replyCount", 0),
                },
            )
        )
    return items


async def _collect_async(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    api = await _ensure_pool()
    out: list[RawItem] = []
    for s in sources:
        try:
            out.extend(await _collect_query(api, s, since))
        except Exception as e:  # noqa: BLE001
            log.error(f"X search failed for {s.id} '{s.handle}': {e}")
    return out


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    """Synchronous wrapper used by job entrypoints."""
    x_search_sources = [s for s in sources if s.platform == "XSearch"]
    if not x_search_sources:
        return []
    accounts = env_json("X_ACCOUNTS", default=[])
    if not accounts:
        log.info(
            f"X_ACCOUNTS not configured; skipping X search ({len(x_search_sources)} sources待ち)"
        )
        return []
    if circuit_breaker.is_open(BREAKER):
        log.warning(f"{BREAKER} circuit open; skipping")
        return []
    try:
        return asyncio.run(_collect_async(x_search_sources, since))
    except Exception as e:  # noqa: BLE001
        log.error(f"X search collection crashed: {e}")
        circuit_breaker.trip(BREAKER, reason=str(e), auto_reset_hours=2)
        return []
