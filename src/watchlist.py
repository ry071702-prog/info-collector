"""Watchlist loader: reads local CSV and mirrors it to Google Sheets."""
from __future__ import annotations
import csv
from pathlib import Path

from . import logger
from .config import CONFIG_DIR, env, env_bool, env_json
from .models import WatchSource

log = logger.get(__name__)
LOCAL_CACHE = CONFIG_DIR / "watchlist.csv"


def load() -> list[WatchSource]:
    """Load local CSV as canonical source and best-effort sync to Sheets."""
    sources = _load_from_csv(LOCAL_CACHE)
    log.info(f"Loaded {len(sources)} sources from local CSV")

    # NOTE: Sheets 同期はデフォルト無効。_sync_csv_to_sheets は ws.clear() で
    # Sheets を毎回上書きするため、過去に Sheets 側のみに存在したソースを破壊した
    # 実績がある (2026-05-21)。CSV を唯一の canonical とし、明示的に
    # SYNC_SHEETS_FROM_CSV=true を設定した場合のみ同期する。
    if env_bool("SYNC_SHEETS_FROM_CSV", False):
        _sync_csv_to_sheets(sources)
    else:
        log.info("Sheets sync skipped (SYNC_SHEETS_FROM_CSV not enabled)")

    return [s for s in sources if s.enabled]


def _load_from_sheets() -> list[WatchSource]:
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
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(sheet_id).worksheet("watchlist")
    records = ws.get_all_records()
    return [_parse_row(r) for r in records]


def _sync_csv_to_sheets(sources: list[WatchSource]) -> None:
    """Overwrite the watchlist worksheet from local CSV rows."""
    try:
        creds_dict = env_json("GOOGLE_SHEETS_CREDENTIALS")
        sheet_id = env("GOOGLE_SHEETS_ID")
        if not creds_dict or not sheet_id:
            log.info("Sheets sync skipped: GOOGLE_SHEETS_CREDENTIALS or GOOGLE_SHEETS_ID is not set")
            return

        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_id).worksheet("watchlist")

        fieldnames = list(WatchSource.model_fields.keys())
        values = [fieldnames]
        for source in sources:
            row = _source_to_csv_row(source)
            values.append([row.get(field, "") for field in fieldnames])

        ws.clear()
        ws.update("A1", values)
        log.info(f"Synced {len(sources)} sources from local CSV to Google Sheets")
    except Exception as e:  # noqa: BLE001
        log.warning(f"Sheets sync failed ({e}); continuing with local CSV")


def _load_from_csv(path: Path) -> list[WatchSource]:
    if not path.exists():
        log.error(f"No watchlist found at {path}")
        return []
    rows: list[WatchSource] = []
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(_parse_row(r))
    return rows


def _parse_row(r: dict) -> WatchSource:
    hints = r.get("subcategory_hints", "")
    if isinstance(hints, str):
        hints = [h.strip() for h in hints.split(",") if h.strip()]
    enabled = r.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.upper() in ("TRUE", "1", "YES")
    return WatchSource(
        id=r["id"],
        name=r["name"],
        handle=r.get("handle", "") or "",
        url=r.get("url", "") or "",
        platform=r["platform"],
        genre=r["genre"],
        source_type=r["source_type"],
        subcategory_hints=hints,
        priority=r.get("priority", "medium") or "medium",
        enabled=enabled,
        check_frequency=r.get("check_frequency", "6h") or "6h",
        language=r.get("language", "ja") or "ja",
        notes=r.get("notes", "") or "",
    )


def _write_local_cache(sources: list[WatchSource]) -> None:
    fieldnames = list(WatchSource.model_fields.keys())
    with LOCAL_CACHE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in sources:
            writer.writerow(_source_to_csv_row(s))


def _source_to_csv_row(source: WatchSource) -> dict[str, str]:
    row = source.model_dump()
    row["subcategory_hints"] = ",".join(row["subcategory_hints"])
    row["enabled"] = "TRUE" if row["enabled"] else "FALSE"
    return {key: str(value) for key, value in row.items()}


def by_frequency(sources: list[WatchSource], freq: str) -> list[WatchSource]:
    """Filter sources matching the requested check_frequency tier."""
    if freq == "realtime":
        return [s for s in sources if s.check_frequency == "realtime"]
    if freq == "hourly":
        return [s for s in sources if s.check_frequency in ("realtime", "hourly")]
    if freq == "6h":
        return [s for s in sources if s.check_frequency in ("realtime", "hourly", "6h")]
    return sources  # daily: all
