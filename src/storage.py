"""JSONL-based storage for raw and processed items."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .config import processed_dir, raw_dir
from .models import ProcessedItem, RawItem


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
