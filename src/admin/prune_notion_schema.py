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

import httpx

from .. import logger
from ..config import env
from ..outputs.notion import NOTION_API_VERSION, _client, normalize_db_id

log = logger.get(__name__)

LEGACY_PROP = "Tags"
REPLACEMENT_PROP = "TagsText"


def _patch_db(db_id: str, properties: dict) -> tuple[int, str]:
    """databases.update を raw httpx で実行。

    notion-client 経由だと properties の値が None のキーが送信時に欠落し、
    プロパティ削除 (Tags=null) が効かない。json.dumps は None→null を保持するため
    httpx で直接 PATCH して確実に null を送る。
    """
    token = env("NOTION_TOKEN", required=True)
    resp = httpx.patch(
        f"https://api.notion.com/v1/databases/{db_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        },
        json={"properties": properties},  # None は null として送られる
        timeout=30.0,
    )
    return resp.status_code, resp.text[:300]


def prune(client, db_id: str, label: str) -> None:
    schema = client.databases.retrieve(database_id=db_id)
    props = schema.get("properties", {})
    log.info(
        f"[{label}] before: properties={len(props)} tags_present={LEGACY_PROP in props}"
    )

    # Tags=null で削除 + TagsText を rich_text で確保 (名前ベースで冪等)。
    status, body = _patch_db(db_id, {LEGACY_PROP: None, REPLACEMENT_PROP: {"rich_text": {}}})
    if status == 200:
        log.info(f"[{label}] PATCH 200: dropped '{LEGACY_PROP}', ensured '{REPLACEMENT_PROP}'")
    else:
        log.warning(f"[{label}] PATCH {status}: {body}")

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
