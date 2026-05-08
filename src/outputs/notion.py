"""Notion DB writer. One DB per genre. Schema is defined in the DB itself."""
from __future__ import annotations
from datetime import datetime

from .. import logger
from ..config import env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)


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
    }


def write(items: list[ProcessedItem]) -> tuple[int, int]:
    """Returns (success, failed)."""
    if is_dry_run():
        log.info(f"[DRY_RUN] would write {len(items)} items to Notion")
        return 0, 0

    db_games = env("NOTION_DATABASE_ID_GAMES")
    db_anime = env("NOTION_DATABASE_ID_ANIME")
    db_disney = env("NOTION_DATABASE_ID_DISNEY")
    if not (db_games or db_anime or db_disney):
        log.warning("Notion DB IDs not set; skipping")
        return 0, 0

    try:
        client = _client()
    except Exception as e:  # noqa: BLE001
        log.error(f"Notion auth failed: {e}")
        return 0, len(items)

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
        try:
            client.pages.create(parent={"database_id": db_id}, properties=_properties(it))
            success += 1
        except Exception as e:  # noqa: BLE001
            log.warning(f"Notion write failed for {it.dedup_key}: {e}")
            failed += 1
    return success, failed
