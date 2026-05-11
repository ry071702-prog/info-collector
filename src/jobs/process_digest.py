"""Daily processing job: classify raw items in chunks, write to outputs incrementally.

設計:
- raw を chunk (settings.batch_sizes.classify_batch) ごとに分類 → 即座に各 output へ書き込む
- 既に処理済みの fingerprint はスキップ（再開時に重複処理しない）
- 連続して 0 件しか分類できない chunk が続いたら Gemini quota 切れと判断して early stop
- 部分的な処理結果でも data/processed と Notion / Sheets には反映される
- run 単位で classified=0 が 2 連続したら静かな破綻として ALERTS webhook へ警告
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

from .. import dedup, logger
from ..config import cache_dir, settings
from ..models import RawItem
from ..outputs import discord, markdown, notion, sheets
from ..processors import classify, digest
from ..storage import read_raw, write_processed

log = logger.get(__name__)
JST = timezone(timedelta(hours=9))

# 連続してこの数だけ「0件分類」chunk が続いたら quota 切れとみなして停止
QUOTA_EXHAUSTED_EMPTY_CHUNKS = 2

# run 単位の "0件処理" 連続検知。これを超えたら ALERTS webhook へ通知
RUN_HISTORY_PATH = cache_dir() / "process_digest_runs.json"
ZERO_CLASSIFY_ALERT_THRESHOLD = 2


def _load_run_history() -> list[dict]:
    """直近の run 結果履歴 (新しい順)。記録は最大 10 件保持。"""
    if not RUN_HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(RUN_HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_run_record(classified: int, raw_window_count: int, stopped_early: bool) -> int:
    """今回の run 結果を記録し、連続 0 件 run 数を返す。"""
    history = _load_run_history()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classified": classified,
        "raw_window_count": raw_window_count,
        "stopped_early": stopped_early,
    }
    history.insert(0, record)
    history = history[:10]
    RUN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    consecutive_zero = 0
    for r in history:
        # raw が 0 件の run は「処理対象なし」で除外 (静かな破綻ではない)
        if r.get("raw_window_count", 0) == 0:
            continue
        if r.get("classified", 0) == 0:
            consecutive_zero += 1
        else:
            break
    return consecutive_zero


def _phase(now_utc: datetime) -> tuple[str, str]:
    """Return (JST date, AM/PM) for the digest filename."""
    now_jst = now_utc.astimezone(JST)
    phase = "AM" if 6 <= now_jst.hour < 18 else "PM"
    return now_jst.strftime("%Y-%m-%d"), phase


def _read_raw_window(start: datetime, end: datetime) -> list[RawItem]:
    """Read raw items whose item timestamp is inside [start, end]."""
    items = []
    cur = start.astimezone(timezone.utc).date()
    end_date = end.astimezone(timezone.utc).date()
    while cur <= end_date:
        for item in read_raw(cur.strftime("%Y-%m-%d")):
            ts = item.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            if start <= ts <= end:
                items.append(item)
        cur += timedelta(days=1)
    return items


def main() -> None:
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=12)
    digest_date, digest_phase = _phase(now_utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    raw_items = _read_raw_window(window_start, now_utc)
    log.info(f"Processing window: {window_start.isoformat()} - {now_utc.isoformat()}")
    log.info(f"Digest slug: {digest_date}-{digest_phase}")
    log.info(f"Read {len(raw_items)} raw items in 12h window")
    if not raw_items:
        log.warning("No raw items found; skipping")
        return

    # 既に処理済みの raw fingerprint をセット化してスキップ（再開時の重複処理回避）
    already_fps = dedup.recent_raw_fingerprints(days=30)
    seen: set[str] = set()
    pending = []
    for item in raw_items:
        if item.fingerprint in already_fps or item.fingerprint in seen:
            continue
        seen.add(item.fingerprint)
        pending.append(item)
    log.info(f"Already processed: {len(already_fps)}, pending: {len(pending)}")

    chunk_size = settings()["batch_sizes"].get("classify_batch", 20)
    totals = {"classified": 0, "notion_ok": 0, "notion_fail": 0, "sheets": 0, "duplicates": 0}
    consecutive_empty = 0
    stopped_early = False
    processed_for_digest = []

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
        processed_for_digest.extend(fresh)
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

    # Markdown digest: この12時間 window の processed を集約。LLM 呼び出しあり（quota 切れ時はスキップ扱い）
    if processed_for_digest and not stopped_early:
        try:
            content = digest.daily_digest(processed_for_digest, f"{digest_date} {digest_phase}")
            path = markdown.write_digest(digest_date, content, digest_phase)
            log.info(f"Digest written to {path}")
        except Exception as e:  # noqa: BLE001
            log.error(f"Digest generation failed: {e}")
    elif stopped_early:
        log.info("Skipping digest generation due to early stop (quota likely exhausted)")

    # Heartbeat
    status_emoji = "⚠️" if stopped_early else "✅"
    discord.post_message(
        "DISCORD_WEBHOOK_OPS",
        f"{status_emoji} 12h digest ({digest_date}-{digest_phase}): "
        f"{totals['classified']}件処理 / "
        f"Notion {totals['notion_ok']} / Sheets {totals['sheets']}"
        + (" (quota切れで途中停止)" if stopped_early else ""),
    )

    # run 履歴を記録し、連続 0 件 run が閾値以上なら ALERTS webhook へ警告
    consecutive_zero = _save_run_record(
        classified=totals["classified"],
        raw_window_count=len(raw_items),
        stopped_early=stopped_early,
    )
    if consecutive_zero >= ZERO_CLASSIFY_ALERT_THRESHOLD:
        discord.post_message(
            "DISCORD_WEBHOOK_ALERTS",
            f"🚨 process_digest が **{consecutive_zero} 回連続** で 0 件処理。"
            f"最新 run: {digest_date}-{digest_phase} / raw {len(raw_items)}件中 0件分類。"
            f"\nGemini quota / filter ロジック / watchlist の点検を推奨。",
        )


if __name__ == "__main__":
    main()
