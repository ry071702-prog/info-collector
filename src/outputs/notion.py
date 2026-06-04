"""Notion DB writer. One DB per genre. Schema is defined in the DB itself."""
from __future__ import annotations
import re
from datetime import datetime

from .. import logger
from ..config import env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)

_HEX32 = re.compile(r"([0-9a-fA-F]{32})")
_MISSING_PROPERTY_RE = re.compile(
    r'"?([A-Za-z][\w]*)"? is not a property that exists',
    re.IGNORECASE,
)
_CORE_SAFE_PROPS: set[str] = {
    "Title",
    "Importance",
    "Category",
    "Genre",
    "URL",
    "Author",
    "Timestamp",
    # 旧 "Tags" (multi_select) は schema を肥大化させたため廃止し rich_text の
    # "TagsText" に移行済み (_properties 参照)。fallback 書き込みでも TagsText を使う。
    "TagsText",
    "Spoiler",
    "Source",
    "DedupKey",
}

# Disney 専用: subcategory_id 先頭2文字 (DA-DO) → Notion 上の Category 表示名
DISNEY_GROUP_LABELS: dict[str, str] = {
    "DA": "公式発表・ニュース",
    "DB": "映画・劇場公開",
    "DC": "Disney+ 配信",
    "DD": "テレビ番組・ドラマ",
    "DE": "テーマパーク・リゾート",
    "DF": "グッズ・コラボ・物販",
    "DG": "キャラクター・IP展開",
    "DH": "D23・ファンイベント",
    "DI": "音楽・サウンドトラック",
    "DJ": "ゲーム・アプリ・体験",
    "DK": "キャスト・スタッフ",
    "DL": "業界・ビジネス",
    "DM": "ファン文化・考察",
    "DN": "リーク・先行情報",
    "DO": "トレーラー・予告映像",
}


def _disney_category_label(subcategory_id: str) -> str | None:
    """DA1 のような技術 ID から 15 グループの日本語ラベルを返す。不明なら None。"""
    return DISNEY_GROUP_LABELS.get(subcategory_id[:2].upper()) if subcategory_id else None


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


# このコードは DB 直下に `properties` が返る旧スキーマモデル前提。新しい
# Notion API バージョン (data source モデル) では databases.retrieve が
# properties を返さず schema 取得が 0 件になり、書き込みの property フィルタや
# Tags 削除が機能しなくなる。バージョンを固定して旧来の応答形に揃える。
NOTION_API_VERSION = "2022-06-28"


def _client():
    from notion_client import Client

    token = env("NOTION_TOKEN", required=True)
    return Client(auth=token, notion_version=NOTION_API_VERSION)


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
    # Tags は multi_select だと unique values が DB schema を肥大化させ
    # 489KB 上限に到達するため、rich_text に切り替え (新カラム名 TagsText)。
    # 旧 Tags multi_select は schema 上残るが新規書き込みでは触らない。
    tags = list({*item.title_tags, *item.entity_tags})[:20]
    tags_text = ", ".join(t for t in tags if t)[:1900]
    return {
        "Title": {"title": [{"text": {"content": item.summary[:200]}}]},
        "Importance": {"select": {"name": item.importance}},
        "Category": {"select": {"name": item.subcategory_id}},
        "Genre": {"select": {"name": item.genre}},
        "URL": {"url": item.url or None},
        "Author": {"rich_text": [{"text": {"content": item.author}}]},
        "Timestamp": {"date": {"start": item.timestamp.isoformat()}},
        "TagsText": {"rich_text": [{"text": {"content": tags_text}}]} if tags_text else {"rich_text": []},
        "Spoiler": {"select": {"name": item.flags.spoiler}},
        "Source": {"select": {"name": item.flags.source_role}},
        "DedupKey": {"rich_text": [{"text": {"content": item.dedup_key[:200]}}]},
        "RiskLevel": {"select": {"name": item.risk_level}},
        "FinalPriority": {"select": {"name": item.final_priority}},
        "FreshnessScore": {"number": item.freshness_score},
        "StreamerInfluence": {"number": item.streamer_influence_score},
        "ClipVirality": {"number": item.clip_virality_score},
        "GameTrendFromStreamers": {"number": item.game_trend_from_streamers_score},
        "LiveTrendScore": {"number": item.live_trend_score},
        "VideoTrendScore": {"number": item.video_trend_score},
        "StreamerName": {"rich_text": [{"text": {"content": item.streamer_name[:200]}}]} if item.streamer_name else {"rich_text": []},
        "StreamerGroup": {"select": {"name": item.streamer_group}} if item.streamer_group else {"select": None},
        "IsClip": {"checkbox": item.is_clip},
        "RelatedGameTitle": {"rich_text": [{"text": {"content": item.related_game_title[:200]}}]} if item.related_game_title else {"rich_text": []},
        "RelatedAnimeTitle": {"rich_text": [{"text": {"content": item.related_anime_title[:200]}}]} if item.related_anime_title else {"rich_text": []},
    }


def _filter_existing(props: dict, allowed: set[str]) -> dict:
    """Drop properties not present in DB schema so create() does not fail."""
    return {k: v for k, v in props.items() if k in allowed}


def _db_property_names(client, db_id: str) -> set[str]:
    try:
        schema = client.databases.retrieve(database_id=db_id)
        properties = set(schema.get("properties", {}).keys())
        log.info(f"Notion DB schema retrieved: {len(properties)} properties")
        return properties
    except Exception as e:  # noqa: BLE001
        log.warning(f"Notion DB schema retrieve FAILED for {db_id}; using fallback property set")
        log.warning(f"Could not retrieve Notion DB schema for {db_id}: {e}")
        return set()


def _is_api_response_error(error: Exception) -> bool:
    try:
        from notion_client.errors import APIResponseError

        return isinstance(error, APIResponseError)
    except Exception:  # noqa: BLE001
        return error.__class__.__name__ == "APIResponseError"


def _missing_property_names(error: Exception) -> set[str]:
    if not _is_api_response_error(error):
        return set()
    message = str(error)
    if "is not a property that exists" not in message:
        return set()
    return set(_MISSING_PROPERTY_RE.findall(message))


def _create_page_with_retry(client, db_id: str, props: dict, dedup_key: str) -> tuple[bool, set[str]]:
    dropped: set[str] = set()
    try:
        client.pages.create(parent={"database_id": db_id}, properties=props)
        return True, dropped
    except Exception as e:  # noqa: BLE001
        missing = _missing_property_names(e)
        if not missing:
            log.warning(f"Notion write failed for {dedup_key}: {e}")
            return False, dropped

        retry_props = dict(props)
        for key in missing:
            if key in retry_props:
                retry_props.pop(key, None)
                dropped.add(key)
        if not dropped:
            log.warning(f"Notion write failed for {dedup_key}: {e}")
            return False, dropped

        log.warning(
            f"Notion write failed for {dedup_key}; dropping missing properties "
            f"{sorted(dropped)} and retrying once: {e}"
        )
        try:
            client.pages.create(parent={"database_id": db_id}, properties=retry_props)
            return True, dropped
        except Exception as retry_error:  # noqa: BLE001
            log.error(
                f"Notion write retry failed for {dedup_key}: {retry_error}; "
                f"original_props={props}"
            )
            return False, dropped


def archive_by_urls(urls: list[str]) -> int:
    """Notion DBs を URL で検索し、ヒットしたページを archived=true にする。"""
    if is_dry_run():
        log.info(f"[DRY_RUN] would archive {len(urls)} Notion pages")
        return 0
    if not urls:
        return 0

    db_ids = [
        normalize_db_id(env("NOTION_DATABASE_ID_GAMES")),
        normalize_db_id(env("NOTION_DATABASE_ID_ANIME")),
        normalize_db_id(env("NOTION_DATABASE_ID_DISNEY")),
    ]
    db_ids = [d for d in db_ids if d]
    if not db_ids:
        log.warning("Notion DB IDs not set; skipping archive")
        return 0

    try:
        client = _client()
    except Exception as e:  # noqa: BLE001
        log.error(f"Notion auth failed: {e}")
        return 0

    archived = 0
    for url in urls:
        for db_id in db_ids:
            try:
                resp = client.databases.query(
                    database_id=db_id,
                    filter={"property": "URL", "url": {"equals": url}},
                    page_size=10,
                )
            except Exception as e:  # noqa: BLE001
                log.error(f"Notion query failed (db={db_id}, url={url}): {e}")
                continue
            for page in resp.get("results", []):
                page_id = page.get("id")
                if not page_id:
                    continue
                try:
                    client.pages.update(page_id=page_id, archived=True)
                    archived += 1
                except Exception as e:  # noqa: BLE001
                    log.error(f"Notion archive failed (page={page_id}): {e}")
    return archived


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
    for db_id in (db_games, db_anime, db_disney):
        if db_id and db_id not in schema_cache:
            schema_cache[db_id] = _db_property_names(client, db_id) or _CORE_SAFE_PROPS.copy()

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
        allowed = schema_cache.get(db_id) or _CORE_SAFE_PROPS.copy()
        props = _properties(it)
        # Disney DB は Category 列を 15 グループ日本語ラベルに置換し、
        # 元の DA1 等は SubcategoryRaw に退避（DB スキーマ側に列があれば書き込まれる）
        if it.genre == "disney":
            label = _disney_category_label(it.subcategory_id)
            if label:
                props["Category"] = {"select": {"name": label}}
            props["SubcategoryRaw"] = {
                "rich_text": [{"text": {"content": it.subcategory_id}}]
            }
        props = _filter_existing(props, allowed)
        ok, dropped = _create_page_with_retry(client, db_id, props, it.dedup_key)
        for key in dropped:
            schema_cache[db_id].discard(key)
        if ok:
            schema_cache[db_id].update(props.keys() - dropped)
            success += 1
        else:
            failed += 1
    return success, failed
