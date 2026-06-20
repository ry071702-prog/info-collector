"""組織インテリジェンスの「前回からの差分」検知。

収集アイテムの fingerprint を baseline スナップショット(data/cache/org_baseline.json)
と突き合わせ、新規(=前回に無かった)アイテムだけを返す。
DRY_RUN では baseline を更新しない(再実行で同じ差分が再現できる)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import logger
from ..config import cache_dir, is_dry_run
from ..models import RawItem

log = logger.get(__name__)

_BASELINE_FILE = "org_baseline.json"
_MAX_KEEP = 2000


def _path():
    return cache_dir() / _BASELINE_FILE


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"seen": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"seen": {}}


def detect_changes(items: list[RawItem]) -> list[RawItem]:
    """baseline に無い fingerprint のアイテムだけ返す(=前回からの新規/変化)。"""
    seen = _load().get("seen", {})
    fresh = [it for it in items if it.fingerprint not in seen]
    log.info(f"change_detect: {len(fresh)} new / {len(items)} collected")
    return fresh


def commit_baseline(items: list[RawItem]) -> None:
    """収集済み fingerprint を baseline に記録(DRY_RUN では何もしない)。"""
    if is_dry_run():
        log.info("DRY_RUN: baseline not updated")
        return
    base = _load()
    seen = base.get("seen", {})
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        seen[it.fingerprint] = now
    if len(seen) > _MAX_KEEP:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-_MAX_KEEP:])
    base["seen"] = seen
    _path().write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    log.info(f"baseline updated: {len(seen)} fingerprints")
