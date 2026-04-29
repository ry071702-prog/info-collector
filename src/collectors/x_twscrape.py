"""X (Twitter) collector via twscrape."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

from .. import circuit_breaker, logger
from ..config import env_json, settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)
BREAKER = "x_twscrape"


async def _ensure_pool():
    """Initialize twscrape API pool with accounts from env."""
    from twscrape import API

    api = API()
    accounts = env_json("X_ACCOUNTS", default=[])
    if not accounts:
        raise RuntimeError("X_ACCOUNTS not configured")
    # Idempotent: only add accounts not already in pool
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


async def _collect_user(api, source: WatchSource, since: datetime) -> list[RawItem]:
    from twscrape import gather

    handle = source.handle.lstrip("@")
    user = await api.user_by_login(handle)
    if not user:
        log.warning(f"X user not found: {handle}")
        return []
    limit = settings()["collectors"]["x"]["tweets_per_user_max"]
    tweets = await gather(api.user_tweets(user.id, limit=limit))
    items: list[RawItem] = []
    for t in tweets:
        if t.date.replace(tzinfo=timezone.utc) < since:
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
                author=handle,
                account_type=source.source_type,
                text=text,
                url=t.url,
                timestamp=t.date.replace(tzinfo=timezone.utc),
            )
        )
    return items


async def _collect_async(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    if circuit_breaker.is_open(BREAKER):
        log.warning("X breaker open; skipping")
        return []
    api = await _ensure_pool()
    out: list[RawItem] = []
    failures = 0
    for s in sources:
        try:
            out.extend(await _collect_user(api, s, since))
        except Exception as e:  # noqa: BLE001
            failures += 1
            log.error(f"X collection failed for {s.handle}: {e}")
    if failures and failures == len(sources):
        circuit_breaker.trip(BREAKER, f"All {failures} sources failed")
    return out


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    """Synchronous wrapper used by job entrypoints."""
    x_sources = [s for s in sources if s.platform == "X"]
    if not x_sources:
        return []
    return asyncio.run(_collect_async(x_sources, since))
