"""Monthly maintenance: aggregate stats, find noisy sources, quota report, prune old data."""
from __future__ import annotations
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .. import llm_client, logger
from ..config import DATA_DIR, settings
from ..outputs import discord, markdown
from ..storage import read_processed_range

log = logger.get(__name__)


def _prune_dated_subdirs(parent: Path, retain_days: int) -> int:
    """parent 配下の YYYY-MM-DD ディレクトリで cutoff より古いものを削除。返り値は削除件数。"""
    if not parent.exists():
        return 0
    cutoff = datetime.utcnow().date() - timedelta(days=retain_days)
    removed = 0
    for entry in parent.iterdir():
        if not entry.is_dir():
            continue
        try:
            d = datetime.strptime(entry.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            shutil.rmtree(entry)
            removed += 1
    return removed


def _prune_logs(parent: Path, retain_days: int) -> int:
    """data/logs/ 配下のファイルを mtime ベースで cutoff より古いものを削除。"""
    if not parent.exists():
        return 0
    cutoff_ts = (datetime.utcnow() - timedelta(days=retain_days)).timestamp()
    removed = 0
    for entry in parent.rglob("*"):
        if entry.is_file() and entry.stat().st_mtime < cutoff_ts:
            entry.unlink()
            removed += 1
    return removed


def cleanup() -> dict[str, int]:
    """retention 設定に従って古いデータを削除。"""
    cfg = settings().get("retention", {})
    raw_days = int(cfg.get("raw_days", 60))
    logs_days = int(cfg.get("logs_days", 30))
    raw_pruned = _prune_dated_subdirs(DATA_DIR / "raw", raw_days)
    logs_pruned = _prune_logs(DATA_DIR / "logs", logs_days)
    log.info(f"cleanup: raw_pruned={raw_pruned} (>{raw_days}d), logs_pruned={logs_pruned} (>{logs_days}d)")
    return {"raw_pruned": raw_pruned, "logs_pruned": logs_pruned}


def _aggregate_stats(items):
    by_source = Counter()
    by_source_importance = defaultdict(Counter)
    by_source_genre = defaultdict(Counter)
    for it in items:
        by_source[it.author] += 1
        by_source_importance[it.author][it.importance] += 1
        by_source_genre[it.author][it.genre] += 1
    return {
        "total": len(items),
        "by_source_count": dict(by_source.most_common(50)),
        "noisy_candidates": [
            author for author, counts in by_source_importance.items()
            if sum(counts.values()) >= 10 and counts.get("C", 0) / sum(counts.values()) > 0.7
        ],
        "by_source_genre": {a: dict(c) for a, c in by_source_genre.items()},
    }


def main() -> None:
    end = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    items = read_processed_range(start, end)
    log.info(f"Monthly: {len(items)} items in last 30 days")

    stats = _aggregate_stats(items)
    quota = llm_client.quota_status()
    pruned = cleanup()

    # Optional Gemini analysis (skip if data is too thin)
    if stats["total"] >= 50:
        try:
            ai_summary = llm_client.call_text(
                model=settings()["models"]["maintenance"],
                system="あなたはデータパイプラインの保守担当です。",
                user=(
                    "以下の30日分の運用統計を分析して、ノイズソース候補・カバレッジ不足・"
                    "推奨アクションを日本語Markdownでまとめてください。\n\n"
                    f"{json.dumps(stats, ensure_ascii=False, indent=2)}"
                ),
                max_tokens=4000,
            )
        except Exception as e:  # noqa: BLE001
            ai_summary = f"AI分析失敗: {e}"
    else:
        ai_summary = "（データ不足のためAI分析スキップ）"

    month = end.strftime("%Y-%m")
    quota_lines = [
        f"- {model}: {info['used']}/{info['limit']}回 ({info['pct']:.0f}%)"
        for model, info in quota.items()
    ]
    content = f"""# 月次メンテナンスレポート: {month}

## 数字で見る今月
- 処理総件数: {stats['total']}
- ノイズソース候補: {len(stats['noisy_candidates'])}件

## 本日のGemini API使用量（無料枠ベース）
{chr(10).join(quota_lines) or '- データなし'}

## ノイズソース候補（C率 > 70%）
{chr(10).join(f'- {a}' for a in stats['noisy_candidates']) or '- なし'}

## クリーンアップ実績
- data/raw/ から削除: {pruned['raw_pruned']} 日分
- data/logs/ から削除: {pruned['logs_pruned']} ファイル

## AI分析

{ai_summary}
"""
    path = markdown.write_monthly(month, content)
    log.info(f"Monthly report: {path}")
    discord.post_message("DISCORD_WEBHOOK_OPS", f"🛠️ 月次メンテレポート: {path.name}")


if __name__ == "__main__":
    main()
