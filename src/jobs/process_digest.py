"""Daily processing job: classify raw items in chunks, write to outputs incrementally.

設計:
- raw を chunk (settings.batch_sizes.classify_batch) ごとに分類 → 即座に各 output へ書き込む
- 既に処理済みの fingerprint はスキップ（再開時に重複処理しない）
- 連続して 0 件しか分類できない chunk が続いたら Gemini quota 切れと判断して early stop
- 部分的な処理結果でも data/processed と Notion / Sheets には反映される
"""
from __future__ import annotations
from datetime import datetime, timedelta

from .. import dedup, logger
from ..config import settings
from ..outputs import discord, markdown, notion, sheets
from ..processors import classify, digest
from ..storage import read_raw, read_processed, write_processed

log = logger.get(__name__)

# 連続してこの数だけ「0件分類」chunk が続いたら quota 切れとみなして停止
QUOTA_EXHAUSTED_EMPTY_CHUNKS = 2


def main() -> None:
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

    # 既に処理済みの raw fingerprint をセット化してスキップ（再開時の重複処理回避）
    already_processed = read_processed(date_str)
    already_fps = {p.raw_fingerprint for p in already_processed}
    pending = [it for it in raw_items if it.fingerprint not in already_fps]
    log.info(f"Already processed: {len(already_fps)}, pending: {len(pending)}")

    chunk_size = settings()["batch_sizes"].get("classify_batch", 20)
    totals = {"classified": 0, "notion_ok": 0, "notion_fail": 0, "sheets": 0, "duplicates": 0}
    consecutive_empty = 0
    stopped_early = False

    for i in range(0, len(pending), chunk_size):
        chunk = pending[i : i + chunk_size]
        chunk_idx = i // chunk_size + 1
        total_chunks = (len(pending) - 1) // chunk_size + 1 if pending else 0
        log.info(f"Chunk {chunk_idx}/{total_chunks}: classifying {len(chunk)} items")

        processed = classify.process(chunk)

        if not processed:
            consecutive_empty += 1
            log.warning(f"Chunk {chunk_idx}: 0 items classified (consecutive empty: {consecutive_empty})")
            if consecutive_empty >= QUOTA_EXHAUSTED_EMPTY_CHUNKS:
                log.warning(
                    f"Stopping early: {consecutive_empty} consecutive empty chunks "
                    f"(likely Gemini quota exhausted)"
                )
                stopped_early = True
                break
            continue

        consecutive_empty = 0
        fresh, dropped = dedup.filter_new(processed)
        totals["duplicates"] += dropped
        if not fresh:
            log.info(f"Chunk {chunk_idx}: all {len(processed)} were duplicates")
            continue

        write_processed(date_str, fresh)
        totals["classified"] += len(fresh)
        log.info(f"Chunk {chunk_idx}: {len(fresh)} fresh classified ({dropped} duplicates)")

        # Incremental writes: each chunk goes to outputs immediately
        try:
            n = sheets.append(fresh)
            totals["sheets"] += n
        except Exception as e:  # noqa: BLE001
            log.error(f"Chunk {chunk_idx}: Sheets append failed: {e}")
        try:
            ok, fail = notion.write(fresh)
            totals["notion_ok"] += ok
            totals["notion_fail"] += fail
        except Exception as e:  # noqa: BLE001
            log.error(f"Chunk {chunk_idx}: Notion write failed: {e}")

    log.info(
        f"Pipeline summary: classified={totals['classified']} "
        f"duplicates={totals['duplicates']} "
        f"notion_ok={totals['notion_ok']} notion_fail={totals['notion_fail']} "
        f"sheets={totals['sheets']} "
        f"early_stopped={stopped_early}"
    )

    # Markdown digest: その日の全 processed を集約。LLM 呼び出しあり（quota 切れ時はスキップ扱い）
    all_today = read_processed(date_str)
    if all_today and not stopped_early:
        try:
            content = digest.daily_digest(all_today, date_str)
            path = markdown.write_digest(date_str, content)
            log.info(f"Digest written to {path}")
        except Exception as e:  # noqa: BLE001
            log.error(f"Digest generation failed: {e}")
    elif stopped_early:
        log.info("Skipping digest generation due to early stop (quota likely exhausted)")

    # Heartbeat
    status_emoji = "⚠️" if stopped_early else "✅"
    discord.post_message(
        "DISCORD_WEBHOOK_OPS",
        f"{status_emoji} Daily digest ({date_str}): "
        f"{totals['classified']}件処理 / "
        f"Notion {totals['notion_ok']} / Sheets {totals['sheets']}"
        + (" (quota切れで途中停止)" if stopped_early else ""),
    )


if __name__ == "__main__":
    main()
