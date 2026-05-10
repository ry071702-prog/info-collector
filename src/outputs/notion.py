"""Notion DB writer. One DB per genre. Schema is defined in the DB itself."""
from __future__ import annotations
import re
from datetime import datetime

from .. import logger
from ..config import env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)

_HEX32 = re.compile(r"([0-9a-fA-F]{32})")


def normalize_db_id(raw: str | None) -> str | None:
    """secret に URL がまるごと入っているケースを救済して UUID 形式に整形。"""
    if not raw:
        return raw
    s = raw.strip()
    m = _HEX32.search(s.replace("-", ""))
    if m:
        h = m.group(1)
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    return s


def _client():
    from notion_client import Client

    token = env("NOTION_TOKEN", required=True)
    return Client(auth=token)


def _properties(item: ProcessedItem) -> dict:
    """Map ProcessedItem to Notion properties.

    Required DB properties (create with these names/types):
    - Title (title): summary
    - Importance (select): S/A/B/C
    - Category (select): subcategory_id
    - Genre (select): games/anime/disney/both
    - URL (url)
    - Author (rich_text)
    - Timestamp (date)
    - Tags (multi_select): title_tags + entity_tags
    - Spoiler (select): なし/軽微/重大
    - Source (select): source_role
    - DedupKey (rich_text)

    Optional β properties (auto-skipped if column missing on the DB):
    - RiskLevel (select): low/middle/high
    - FinalPriority (select): S/A/B/C  (importance + scores 合成)
    - FreshnessScore (number): 0-100
    - StreamerInfluence (number): 0-100
    - ClipVirality (number): 0-100
    - GameTrendFromStreamers (number): 0-100
    """
    tags = list({*item.title_tags, *item.entity_tags})[:50]
    return {
        "Title": {"title": [{"text": {"content": item.summary[:200]}}]},
        "Importance": {"select": {"name": item.importance}},
        "Category": {"select": {"name": item.subcategory_id}},
        "Genre": {"select": {"name": item.genre}},
        "URL": {"url": item.url or None},
        "Author": {"rich_text": [{"text": {"content": item.author}}]},
        "Timestamp": {"date": {"start": item.timestamp.isoformat()}},
        "Tags": {"multi_select": [{"name": t[:100]} for t in tags if t]},
        "Spoiler": {"select": {"name": item.flags.spoiler}},
        "Source": {"select": {"name": item.flags.source_role}},
        "DedupKey": {"rich_text": [{"text": {"content": item.dedup_key[:200]}}]},
        "RiskLevel": {"select": {"name": item.risk_level}},
        "FinalPriority": {"select": {"name": item.final_priority}},
        "FreshnessScore": {"number": item.freshness_score},
        "StreamerInfluence": {"number": item.streamer_influence_score},
        "ClipVirality": {"number": item.clip_virality_score},
        "GameTrendFromStreamers": {"number": item.game_trend_from_streamers_score},
    }


def _filter_existing(props: dict, allowed: set[str]) -> dict:
    """Drop properties not present in DB schema so create() does not fail."""
    return {k: v for k, v in props.items() if k in allowed}


def _db_property_names(client, db_id: str) -> set[str]:
    try:
        schema = client.databases.retrieve(database_id=db_id)
        return set(schema.get("properties", {}).keys())
    except Exception as e:  # noqa: BLE001
        log.warning(f"Could not retrieve Notion DB schema for {db_id}: {e}")
        return set()


def write(items: list[ProcessedItem]) -> tuple[int, int]:
    """Returns (success, failed)."""
    if is_dry_run():
        log.info(f"[DRY_RUN] would write {len(items)} items to Notion")
        return 0, 0

    db_games = normalize_db_id(env("NOTION_DATABASE_ID_GAMES"))
    db_anime = normalize_db_id(env("NOTION_DATABASE_ID_ANIME"))
    db_disney = normalize_db_id(env("NOTION_DATABASE_ID_DISNEY"))
    if not (db_games or db_anime or db_disney):
        log.warning("Notion DB IDs not set; skipping")
        return 0, 0

    try:
        client = _client()
    except Exception as e:  # noqa: BLE001
        log.error(f"Notion auth failed: {e}")
        return 0, len(items)

    # Cache schema per DB so we only fetch once per run
    schema_cache: dict[str, set[str]] = {}
    for db_id in (db_games, db_anime):
        if db_id and db_id not in schema_cache:
            schema_cache[db_id] = _db_property_names(client, db_id)

    success, failed = 0, 0
    for it in items:
        if it.genre == "disney":
            db_id = db_disney
        elif it.genre == "anime":
            db_id = db_anime
        else:
            db_id = db_games
        if not db_id:
            continue
        allowed = schema_cache.get(db_id, set())
        props = _properties(it)
        if allowed:
            props = _filter_existing(props, allowed)
        try:
            client.pages.create(parent={"database_id": db_id}, properties=props)
            success += 1
        except Exception as e:  # noqa: BLE001
            log.warning(f"Notion write failed for {it.dedup_key}: {e}")
            failed += 1
    return success, failed
