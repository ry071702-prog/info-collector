"""JSONL-based storage for raw and processed items."""
from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .config import processed_dir, raw_dir
from .models import ProcessedItem, RawItem


def write_json_atomic(path: Path, data: Any) -> None:
    """状態ファイルを atomic に書く (同一ディレクトリの一時ファイル → os.replace)。

    直接 write_text すると、書き込み中に落ちた場合に途中まで書かれた壊れた JSON が残る。
    状態ファイルの読み手はどれも「壊れていたら {} から開始」にフォールバックするため、
    dedup キーや circuit breaker の状態を丸ごと失って静かに誤動作する
    (通知済みの記事を再通知する、開いていたブレーカーが閉じる 等)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # 同一 FS 内の rename は atomic
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_raw(date_str: str, source_id: str, items: list[RawItem]) -> Path:
    path = raw_dir(date_str) / f"{source_id}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            f.write(it.model_dump_json() + "\n")
    return path


def read_raw(date_str: str) -> Iterator[RawItem]:
    base = raw_dir(date_str)
    for fp in sorted(base.glob("*.jsonl")):
        with fp.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield RawItem.model_validate_json(line)


def write_processed(date_str: str, items: list[ProcessedItem]) -> Path:
    path = processed_dir(date_str) / "items.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            f.write(it.model_dump_json() + "\n")
    return path


def read_processed(date_str: str) -> list[ProcessedItem]:
    path = processed_dir(date_str) / "items.jsonl"
    if not path.exists():
        return []
    out: list[ProcessedItem] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(ProcessedItem.model_validate_json(line))
    return out


def read_processed_range(start: datetime, end: datetime) -> list[ProcessedItem]:
    out: list[ProcessedItem] = []
    cur = start
    while cur.date() <= end.date():
        out.extend(read_processed(cur.strftime("%Y-%m-%d")))
        cur += timedelta(days=1)
    return out
