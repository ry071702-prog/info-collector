"""Daily processing job: classify raw items, dedupe, write to all outputs, generate digest."""
from __future__ import annotations
from datetime import datetime, timedelta

from .. import dedup, logger
from ..outputs import discord, markdown, notion, sheets
from ..processors import classify, digest
from ..storage import read_raw, read_processed, write_processed

log = logger.get(__name__)


def main() -> None:
    # 当日の UTC 日付に揃える。cron も手動トリガーも同じ日付の raw を処理する。
    # 当日が空なら直前日にフォールバック（タイムゾーン境界での取りこぼし回避）。
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    raw_items = list(read_raw(today_str))
    if raw_items:
        date_str = today_str
    else:
        yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        raw_items = list(read_raw(yesterday_str))
        date_str = yesterday_str
    log.info(f"Processing date: {date_str}")
    log.info(f"Read {len(raw_items)} raw items")
    if not raw_items:
        log.warning("No raw items found; skipping")
        return

    # Classify with Claude
    processed = classify.process(raw_items)
    log.info(f"Classified {len(processed)} items")

    # Dedup against the recent window
    fresh, dropped = dedup.filter_new(processed)
    log.info(f"Dedup: {len(fresh)} fresh, {dropped} duplicates")

    # Persist processed
    if fresh:
        write_processed(date_str, fresh)

    # Outputs in parallel-ish (sequential but each isolated by try/except)
    try:
        sheets_count = sheets.append(fresh)
        log.info(f"Sheets: {sheets_count} rows appended")
    except Exception as e:  # noqa: BLE001
        log.error(f"Sheets append failed: {e}")

    try:
        ok, fail = notion.write(fresh)
        log.info(f"Notion: {ok} success, {fail} failed")
    except Exception as e:  # noqa: BLE001
        log.error(f"Notion write failed: {e}")

    # Generate Markdown digest
    all_today = read_processed(date_str)
    if all_today:
        try:
            content = digest.daily_digest(all_today, date_str)
            path = markdown.write_digest(date_str, content)
            log.info(f"Digest written to {path}")
        except Exception as e:  # noqa: BLE001
            log.error(f"Digest generation failed: {e}")

    # Heartbeat
    discord.post_message("DISCORD_WEBHOOK_OPS", f"✅ Daily digest OK ({date_str}): {len(fresh)}件処理")


if __name__ == "__main__":
    main()
