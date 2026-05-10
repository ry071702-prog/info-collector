"""One-shot: ensure Notion DBs have β scoring properties.

Idempotent: skips properties that already exist on each DB.
Run via: `python -m src.admin.init_notion_schema`
Required env: NOTION_TOKEN + at least one of NOTION_DATABASE_ID_{GAMES,ANIME,DISNEY}
"""
from __future__ import annotations
import sys

from notion_client import Client

from .. import logger
from ..config import env

log = logger.get(__name__)

# β プロパティ（カラム名 → Notion property schema）
BETA_PROPS: dict[str, dict] = {
    "RiskLevel": {
        "select": {
            "options": [
                {"name": "low", "color": "green"},
                {"name": "middle", "color": "yellow"},
                {"name": "high", "color": "red"},
            ]
        }
    },
    "FinalPriority": {
        "select": {
            "options": [
                {"name": "S", "color": "red"},
                {"name": "A", "color": "orange"},
                {"name": "B", "color": "blue"},
                {"name": "C", "color": "gray"},
            ]
        }
    },
    "FreshnessScore": {"number": {"format": "number"}},
    "StreamerInfluence": {"number": {"format": "number"}},
    "ClipVirality": {"number": {"format": "number"}},
    "GameTrendFromStreamers": {"number": {"format": "number"}},
}


def ensure_props(client: Client, db_id: str, label: str) -> None:
    schema = client.databases.retrieve(database_id=db_id)
    existing = set(schema.get("properties", {}).keys())
    to_add = {k: v for k, v in BETA_PROPS.items() if k not in existing}
    if not to_add:
        log.info(f"[{label}] all β properties already present; nothing to do")
        return
    log.info(f"[{label}] adding properties: {list(to_add.keys())}")
    client.databases.update(database_id=db_id, properties=to_add)
    log.info(f"[{label}] updated")


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
            ensure_props(client, db_id, label)
        except Exception as e:  # noqa: BLE001
            log.error(f"[{label}] failed: {e}")
    if not any_done:
        log.warning("No NOTION_DATABASE_ID_* set; nothing to do")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
