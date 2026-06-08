"""One-shot: 指定 source_id の過去アイテムを全ストアから削除する。

用途: Disney フィードを汚染していた非作品ソース (ESPN/ABC/Hulu/Nat Geo/FX/
Freeform 等) の既存データを一掃する。

挙動 (指定 source_id 群に対して):
1. data/processed/*/items.jsonl と data/processed/*.jsonl を走査し、
   該当 source_id のアイテムの URL を収集し、ファイルからそのアイテムを除去
   (items.jsonl を書き戻す)。site は processed から再生成されるので消える。
2. 収集した URL を Notion (archive=true) と Google Sheets から削除。

source_id は引数で渡す。省略時は既定のノイズ群。
Run: `python -m src.admin.purge_by_source [SRC ...]`
Required env: NOTION_TOKEN + NOTION_DATABASE_ID_* / GOOGLE_SHEETS_CREDENTIALS
              + GOOGLE_SHEETS_ID (URL 削除に使用)
"""
from __future__ import annotations
import glob
import json
import sys
from pathlib import Path

from .. import logger
from ..config import ROOT
from ..outputs import notion as notion_out
from ..outputs import sheets as sheets_out

log = logger.get(__name__)

DEFAULT_SOURCES = ["DSY046", "DSY047", "DSY038", "DSY039", "DSY040", "DSY049"]


def _processed_paths() -> list[Path]:
    base = ROOT / "data" / "processed"
    paths = list(base.glob("*/items.jsonl")) + list(base.glob("*.jsonl"))
    return sorted(set(paths))


def purge_processed(source_ids: set[str]) -> list[str]:
    """該当アイテムを processed から除去し、その URL を返す。"""
    urls: list[str] = []
    removed = 0
    for p in _processed_paths():
        kept: list[str] = []
        changed = False
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if o.get("source_id") in source_ids:
                changed = True
                removed += 1
                if o.get("url"):
                    urls.append(o["url"])
                continue
            kept.append(line)
        if changed:
            p.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
            log.info(f"{p}: removed matching items, {len(kept)} remain")
    # dedup URLs preserving order
    seen: set[str] = set()
    uniq = [u for u in urls if not (u in seen or seen.add(u))]
    log.info(f"processed から {removed} 件除去 / unique URL {len(uniq)} 件")
    return uniq


def collect_urls_from_raw(source_ids: set[str]) -> list[str]:
    """raw (60日保持) から該当ソースの URL を回収。processed 削除後でも使える。"""
    base = ROOT / "data" / "raw"
    urls: list[str] = []
    for sid in source_ids:
        for p in base.glob(f"*/{sid}.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("url"):
                    urls.append(o["url"])
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def main(argv: list[str]) -> int:
    source_ids = set(argv or DEFAULT_SOURCES)
    log.info(f"purge 対象 source_id: {sorted(source_ids)}")

    # processed から除去しつつ URL 収集 + raw からも回収 (processed 削除済みでも消せる)
    urls = purge_processed(source_ids)
    raw_urls = collect_urls_from_raw(source_ids)
    merged = list(dict.fromkeys(urls + raw_urls))
    log.info(f"削除対象 URL: processed={len(urls)} raw={len(raw_urls)} merged={len(merged)}")
    urls = merged
    if not urls:
        log.info("削除対象 URL なし")
        return 0

    try:
        archived = notion_out.archive_by_urls(urls)
        log.info(f"Notion: {archived} ページを archived 化")
    except Exception as e:  # noqa: BLE001
        log.error(f"Notion archive 失敗: {e}")

    try:
        deleted = sheets_out.delete_by_urls(urls)
        log.info(f"Sheets: {deleted} 行を削除")
    except Exception as e:  # noqa: BLE001
        log.error(f"Sheets delete 失敗: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
