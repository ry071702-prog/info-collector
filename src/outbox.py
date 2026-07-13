"""外部出力 (Notion / Sheets) の再送キュー。

process_digest は processed を先に書き、そのあとで外部出力を実行する。外部出力が一時障害で
失敗しても processed には残るため、次回 run では raw_fingerprint により記事ごとスキップされ、
**失敗した出力先だけを再送する手段が無い** = その記事は二度と Notion / Sheets に載らない
(ジョブは成功扱いのままなので気づけない)。

失敗した item をここに積み、次回 run の冒頭で再送する。成功したものはキューから消える。
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config, logger
from .models import ProcessedItem

log = logger.get(__name__)

# 溜まり続けないよう上限を設ける。超えたぶんは古い順に捨て、捨てたことを必ず log に残す
# (黙って捨てると「再送したはず」の記事が消え、outbox を信用できなくなる)。
MAX_ITEMS = 500


def _path(target: str) -> Path:
    # config.cache_dir() をモジュール経由で呼ぶ (from-import で束縛するとテストの
    # monkeypatch が効かず、テストが本物の data/cache を汚す)
    return config.cache_dir() / f"outbox_{target}.jsonl"


def load(target: str) -> list[ProcessedItem]:
    path = _path(target)
    if not path.exists():
        return []
    items: list[ProcessedItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            items.append(ProcessedItem.model_validate_json(line))
        except ValueError:
            log.warning(f"outbox[{target}]: 壊れた行をスキップ")
    return items


def replace(target: str, items: list[ProcessedItem]) -> None:
    """キューの中身を items で置き換える (再送後の残り = まだ失敗しているもの)。"""
    path = _path(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not items:
        path.unlink(missing_ok=True)
        return

    # dedup_key で重複排除 (同じ記事を何度も積まない)。後勝ちで最新の内容を残す。
    unique: dict[str, ProcessedItem] = {it.dedup_key: it for it in items}
    kept = list(unique.values())

    if len(kept) > MAX_ITEMS:
        dropped = len(kept) - MAX_ITEMS
        kept = kept[-MAX_ITEMS:]
        log.warning(f"outbox[{target}]: 上限 {MAX_ITEMS} 超過のため古い {dropped} 件を破棄")

    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(it.model_dump_json() + "\n" for it in kept), encoding="utf-8")
    os.replace(tmp, path)  # atomic


def add(target: str, items: list[ProcessedItem]) -> None:
    """失敗した item をキューに追加する。"""
    if not items:
        return
    replace(target, load(target) + items)
    log.warning(f"outbox[{target}]: {len(items)} 件を再送キューに追加")
