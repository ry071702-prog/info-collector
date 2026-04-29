"""Append processed items to Google Sheets (one row per item)."""
from __future__ import annotations
from datetime import datetime

from .. import logger
from ..config import env, env_json, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)

COLUMNS = [
    "timestamp", "genre", "importance", "subcategory_id", "category_name",
    "summary", "author", "url", "title_tags", "entity_tags",
    "source_role", "speed", "spoiler", "source_reliability", "dedup_key",
]


def _open_book():
    import gspread
    from google.oauth2.service_account import Credentials

    creds_dict = env_json("GOOGLE_SHEETS_CREDENTIALS", required=True)
    sheet_id = env("GOOGLE_SHEETS_ID", required=True)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds).open_by_key(sheet_id)


def _ensure_sheet(book, name: str):
    try:
        ws = book.worksheet(name)
    except Exception:  # noqa: BLE001
        ws = book.add_worksheet(name, rows=1, cols=len(COLUMNS))
        ws.append_row(COLUMNS)
    return ws


def _row(it: ProcessedItem) -> list:
    return [
        it.timestamp.isoformat(),
        it.genre,
        it.importance,
        it.subcategory_id,
        it.category_name,
        it.summary,
        it.author,
        it.url,
        ",".join(it.title_tags),
        ",".join(it.entity_tags),
        it.flags.source_role,
        it.flags.speed,
        it.flags.spoiler,
        it.flags.source_reliability,
        it.dedup_key,
    ]


def append(items: list[ProcessedItem]) -> int:
    if is_dry_run():
        log.info(f"[DRY_RUN] would append {len(items)} rows to Sheets")
        return 0
    if not items:
        return 0
    try:
        book = _open_book()
    except Exception as e:  # noqa: BLE001
        log.error(f"Sheets open failed: {e}")
        return 0

    games = [_row(it) for it in items if it.genre in ("games", "both")]
    anime = [_row(it) for it in items if it.genre == "anime"]
    count = 0
    if games:
        ws = _ensure_sheet(book, "ゲーム&esports")
        ws.append_rows(games, value_input_option="USER_ENTERED")
        count += len(games)
    if anime:
        ws = _ensure_sheet(book, "アニメ&漫画")
        ws.append_rows(anime, value_input_option="USER_ENTERED")
        count += len(anime)
    return count
