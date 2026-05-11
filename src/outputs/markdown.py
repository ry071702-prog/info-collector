"""Write daily digest / weekly report as committed Markdown."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from ..config import digests_dir, DOCS_DIR


def write_digest(date_str: str, content: str, suffix: str | None = None) -> Path:
    stem = f"{date_str}-{suffix}" if suffix else date_str
    path = digests_dir() / f"{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_weekly(week_end: datetime, content: str) -> Path:
    path = DOCS_DIR / "weekly" / f"{week_end.strftime('%Y-%m-%d')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_monthly(month: str, content: str) -> Path:
    path = DOCS_DIR / "monthly" / f"{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
