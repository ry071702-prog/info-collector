"""Weekly trend report job. Run on Mondays."""
from __future__ import annotations
from datetime import datetime, timedelta

from .. import logger
from ..outputs import discord, markdown
from ..processors import digest
from ..storage import read_processed_range

log = logger.get(__name__)


def main() -> None:
    end = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    log.info(f"Weekly report: {start.date()} → {end.date()}")

    items = read_processed_range(start, end)
    log.info(f"Items in range: {len(items)}")

    if not items:
        discord.post_message("DISCORD_WEBHOOK_ALERTS", "⚠️ Weekly report: no data in range")
        return

    try:
        content = digest.weekly_report(items, start, end)
        path = markdown.write_weekly(end, content)
        log.info(f"Weekly report written to {path}")
        discord.post_message("DISCORD_WEBHOOK_OPS", f"📈 週次レポート完成: {path.name}（{len(items)}件分析）")
    except Exception as e:  # noqa: BLE001
        log.error(f"Weekly report failed: {e}")
        discord.post_message("DISCORD_WEBHOOK_ALERTS", f"❌ Weekly report failed: {e}")


if __name__ == "__main__":
    main()
