"""One-shot: re-filter today's data/processed items to drop misclassified ones.

Background: 旧バージョンの classify は genre=games の watchlist 行を全て
games にピン留めしていたため、Yahoo IT / GIGAZINE 等のメディア源で
genre 違いの記事が games に流れ込んでいた。

このスクリプトは、指定日の data/processed/<date>/items.jsonl を読み、
- source_type="メディア" のアイテムだけを対象に
- Gemini filter を再実行し
- 新しい genre が現在の genre と異なる、または spam と判定されたら除外
- 残ったアイテムだけで items.jsonl を書き戻す

Run via: `python -m src.admin.refilter_processed [YYYY-MM-DD]`
Required env: GEMINI_API_KEY + GOOGLE_SHEETS_CREDENTIALS (watchlist lookup)
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import llm_client, logger, prompts, watchlist
from ..config import processed_dir, settings
from ..models import FilterResult, ProcessedItem

log = logger.get(__name__)


def _build_filter_user(item: ProcessedItem) -> str:
    return prompts.FILTER_USER.format(
        source=item.flags.source_role if item.flags else "メディア",
        author=item.author,
        account_type=item.flags.source_role if item.flags else "メディア",
        text=(item.summary + "\n" + item.raw_text)[:1500],
        url=item.url,
        timestamp=item.timestamp.isoformat(),
    )


def main(date_str: str | None = None) -> int:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log.info(f"refilter target date: {date_str}")

    items_path = processed_dir(date_str) / "items.jsonl"
    if not items_path.exists():
        log.warning(f"no processed file at {items_path}")
        return 0

    # watchlist から source_type マップを作る
    sources = watchlist.load()
    source_type_by_id = {s.id: s.source_type for s in sources}

    items: list[ProcessedItem] = []
    with items_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(ProcessedItem.model_validate_json(line))
                except Exception as e:  # noqa: BLE001
                    log.warning(f"skip bad json line: {e}")
    log.info(f"loaded {len(items)} items")

    model = settings()["models"]["filter"]
    kept: list[ProcessedItem] = []
    rechecked = 0
    dropped = 0
    FLUSH_EVERY = 50  # 50 件処理ごとに items.jsonl を書き出し（途中キャンセル耐性）

    # checkpoint で「処理済 kept + 未処理 remainder」を書き戻すため、
    # 元 items のインデックスを把握する必要がある。current_idx を outer scope で持つ。
    current_idx = [0]

    def _flush(reason: str) -> None:
        # 未処理分を items から拾って kept にぶら下げる（順序は元と同じになる）
        remainder = items[current_idx[0] + 1 :]
        snapshot = kept + remainder
        with items_path.open("w", encoding="utf-8") as fh:
            for x in snapshot:
                fh.write(x.model_dump_json() + "\n")
        log.info(
            f"FLUSH ({reason}): wrote kept={len(kept)} + remainder={len(remainder)} = {len(snapshot)}"
        )

    for idx, it in enumerate(items):
        current_idx[0] = idx
        source_type = source_type_by_id.get(it.source_id, "")
        if source_type != "メディア":
            kept.append(it)
        else:
            rechecked += 1
            try:
                data = llm_client.call_json(
                    model=model,
                    system=prompts.FILTER_SYSTEM,
                    user=_build_filter_user(it),
                    max_tokens=256,
                )
                fr = FilterResult(**data)
            except Exception as e:  # noqa: BLE001
                log.warning(f"filter call failed for {it.url}: {e}; keeping item")
                kept.append(it)
                if rechecked % FLUSH_EVERY == 0:
                    _flush(f"checkpoint @ rechecked={rechecked}")
                continue

            if fr.spam:
                log.info(f"DROP spam: [{it.source_id}] {it.summary[:60]}")
                dropped += 1
            elif fr.genre == "neither":
                log.info(f"DROP neither: [{it.source_id}] {it.summary[:60]}")
                dropped += 1
            elif fr.genre == it.genre:
                # 既存 genre と一致するなら維持
                kept.append(it)
            else:
                # genre 訂正で済む場合: ジャンルだけ書き換え
                log.info(f"FIX genre: [{it.source_id}] {it.genre} -> {fr.genre}: {it.summary[:60]}")
                kept.append(it.model_copy(update={"genre": fr.genre}))

            if rechecked % FLUSH_EVERY == 0:
                _flush(f"checkpoint @ rechecked={rechecked}")

    log.info(f"summary: total={len(items)} rechecked={rechecked} dropped={dropped} kept={len(kept)}")

    if not items:
        return 0

    # backup original
    backup = items_path.with_suffix(".jsonl.bak")
    if not backup.exists():
        backup.write_text(items_path.read_text(encoding="utf-8"), encoding="utf-8")
        log.info(f"backup written: {backup}")

    # write back
    with items_path.open("w", encoding="utf-8") as f:
        for it in kept:
            f.write(it.model_dump_json() + "\n")
    log.info(f"rewrote {items_path} with {len(kept)} items")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))
