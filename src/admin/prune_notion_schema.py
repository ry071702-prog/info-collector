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

from .. import logger
from ..config import env
from ..outputs.notion import _client, normalize_db_id

log = logger.get(__name__)

LEGACY_PROP = "Tags"
REPLACEMENT_PROP = "TagsText"


def prune(client, db_id: str, label: str) -> None:
    # retrieve は新 API バージョンだと properties を返さない (0 件) ことがあるため、
    # 検知に依存せず Tags を無条件で削除し、TagsText を冪等に確保する。
    schema = client.databases.retrieve(database_id=db_id)
    props = schema.get("properties", {})
    # 原因確定用: retrieve の応答形を診断ログに残す。
    log.info(
        f"[{label}] retrieve keys={sorted(schema.keys())} "
        f"properties={len(props)} has_data_sources={'data_sources' in schema}"
    )

    # Tags=None で削除 / TagsText を rich_text で確保 (どちらも名前ベースで冪等)。
    updates: dict[str, dict | None] = {LEGACY_PROP: None, REPLACEMENT_PROP: {"rich_text": {}}}
    try:
        client.databases.update(database_id=db_id, properties=updates)
        log.info(f"[{label}] update sent: drop '{LEGACY_PROP}', ensure '{REPLACEMENT_PROP}'")
    except Exception as e:  # noqa: BLE001
        # Tags が既に無いケース等。TagsText 確保だけは試みる。
        log.warning(f"[{label}] combined update failed ({e}); retrying TagsText only")
        client.databases.update(database_id=db_id, properties={REPLACEMENT_PROP: {"rich_text": {}}})
        log.info(f"[{label}] ensured '{REPLACEMENT_PROP}' only")

    after = client.databases.retrieve(database_id=db_id).get("properties", {})
    log.info(f"[{label}] after: properties={len(after)} tags_present={LEGACY_PROP in after}")


def main() -> int:
    client = _client()
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
