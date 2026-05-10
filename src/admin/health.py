"""Pipeline health monitor.

Run via: `python -m src.admin.health`
- watchlist の各 source について、過去 N 日の processed 件数を集計
- 0 件のソース（取れていない/分類されていない）と高ノイズ源を一覧
- Gemini API quota 状況
- data/raw / processed の容量とファイル数
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .. import llm_client, logger, watchlist
from ..config import DATA_DIR
from ..storage import read_processed_range

log = logger.get(__name__)

WINDOW_DAYS = 7


def _dir_stats(path: Path) -> tuple[int, int]:
    """(file_count, total_bytes) を返す。"""
    if not path.exists():
        return 0, 0
    files = 0
    size = 0
    for f in path.rglob("*"):
        if f.is_file():
            files += 1
            size += f.stat().st_size
    return files, size


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> None:
    end = datetime.utcnow()
    start = end - timedelta(days=WINDOW_DAYS)

    sources = watchlist.load()
    enabled = [s for s in sources if s.enabled]

    items = read_processed_range(start, end)
    by_source_id = Counter(it.source_id for it in items)
    by_genre = Counter(it.genre for it in items)
    by_importance = Counter(it.importance for it in items)
    by_risk = Counter(getattr(it, "risk_level", "low") for it in items)

    silent = [s for s in enabled if by_source_id.get(s.id, 0) == 0]

    print(f"=== Pipeline Health ({start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}) ===")
    print(f"watchlist: {len(sources)} total, {len(enabled)} enabled, {len(sources) - len(enabled)} disabled")
    print(f"processed last {WINDOW_DAYS} days: {len(items)}")
    print(f"  by genre: {dict(by_genre)}")
    print(f"  by importance: {dict(by_importance)}")
    print(f"  by risk_level: {dict(by_risk)}")

    print(f"\n=== Silent sources ({len(silent)}/{len(enabled)} enabled, 0 items in {WINDOW_DAYS}d) ===")
    by_platform = defaultdict(list)
    for s in silent:
        by_platform[s.platform].append(s.id + " " + s.name)
    for plat, names in sorted(by_platform.items()):
        print(f"  [{plat}] {len(names)}件")
        for n in names[:10]:
            print(f"    - {n}")
        if len(names) > 10:
            print(f"    ... and {len(names) - 10} more")

    print(f"\n=== Top 10 productive sources ===")
    for sid, n in by_source_id.most_common(10):
        src = next((s for s in enabled if s.id == sid), None)
        name = src.name if src else "(unknown)"
        print(f"  {sid:6} {n:4} items  {name}")

    print(f"\n=== Storage ===")
    for sub in ("raw", "cache", "logs", "processed"):
        files, size = _dir_stats(DATA_DIR / sub)
        print(f"  data/{sub}: {files} files, {_human_size(size)}")

    print(f"\n=== Gemini API Quota (today UTC) ===")
    quota = llm_client.quota_status()
    if not quota:
        print("  (no usage today)")
    for model, info in quota.items():
        print(f"  {model}: {info['used']}/{info['limit']} ({info['pct']:.0f}%)")


if __name__ == "__main__":
    main()
