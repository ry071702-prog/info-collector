"""One-shot: 旧 `Tags` multi_select を Notion DB から削除してスキーマ肥大を解消。

背景: Tags(multi_select)は書き込みのたびに unique なタグを option として溜め込み、
Notion DB schema の上限 (~489KB) に到達。`pages.create` が
"database schema has exceeded the maximum size" で失敗するようになった。
本体コードは既に rich_text の `TagsText` へ移行済み (src/outputs/notion.py) なので、
DB 側に残った旧 `Tags` プロパティを削除すればスキーマ容量が解放される。

挙動 (各 DB に対して、冪等):
1. `TagsText` (rich_text) が無ければ追加する (移行先の確保)。
2. 旧 `Tags` プロパティが在れば削除する (`properties={"Tags": None}`)。

⚠ `Tags` 削除は既存ページの Tags 列の値も失う破壊的操作。タグ情報は今後
`TagsText` に蓄積される。

Run via: `python -m src.admin.prune_notion_schema`
Required env: NOTION_TOKEN + at least one of NOTION_DATABASE_ID_{GAMES,ANIME,DISNEY}
"""
from __future__ import annotations
import sys

from notion_client import Client

from .. import logger
from ..config import env
from ..outputs.notion import normalize_db_id

log = logger.get(__name__)

LEGACY_PROP = "Tags"
REPLACEMENT_PROP = "TagsText"


def prune(client: Client, db_id: str, label: str) -> None:
    schema = client.databases.retrieve(database_id=db_id)
    existing = set(schema.get("properties", {}).keys())
    log.info(f"[{label}] current schema has {len(existing)} properties")

    updates: dict[str, dict | None] = {}
    if REPLACEMENT_PROP not in existing:
        updates[REPLACEMENT_PROP] = {"rich_text": {}}
        log.info(f"[{label}] will add '{REPLACEMENT_PROP}' (rich_text)")
    if LEGACY_PROP in existing:
        updates[LEGACY_PROP] = None  # None で Notion 上のプロパティを削除
        log.info(f"[{label}] will remove legacy '{LEGACY_PROP}' (multi_select)")

    if not updates:
        log.info(f"[{label}] nothing to do (no legacy '{LEGACY_PROP}', '{REPLACEMENT_PROP}' present)")
        return

    client.databases.update(database_id=db_id, properties=updates)
    log.info(f"[{label}] updated: {sorted(k for k in updates)}")


def main() -> int:
    token = env("NOTION_TOKEN", required=True)
    client = Client(auth=token)
    targets = [
        ("GAMES", env("NOTION_DATABASE_ID_GAMES")),
        ("ANIME", env("NOTION_DATABASE_ID_ANIME")),
        ("DISNEY", env("NOTION_DATABASE_ID_DISNEY")),
    ]
    any_done = False
    for label, db_id in targets:
        if not db_id:
            log.info(f"[{label}] DB ID not configured; skipping")
            continue
        any_done = True
        try:
            prune(client, normalize_db_id(db_id), label)
        except Exception as e:  # noqa: BLE001
            log.error(f"[{label}] failed: {e}")
    if not any_done:
        log.warning("No NOTION_DATABASE_ID_* set; nothing to do")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
