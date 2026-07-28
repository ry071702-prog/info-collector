"""UTC 時刻の共通ヘルパー。

`datetime.utcnow()` は Python 3.12 で非推奨 (将来削除) になった。
tz-naive な値を返すため、tz-aware な値と比較すると TypeError で落ちる罠もある。
新規コードは必ず `utc_now()` を使う。

保存済みキャッシュには tz-naive (`...T12:00:00`) と tz-aware
(`...T12:00:00+00:00`) が混在しうるので、読み出しは `parse_utc()` を通して
どちらでも受けられるようにする (dedup.py が元々やっていた処理を共通化した)。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """現在時刻を tz-aware な UTC で返す (`datetime.utcnow()` の後継)。"""
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    """ISO 文字列を tz-aware な UTC として読む。

    tz 情報が無い古いキャッシュ値は UTC とみなす (過去に `utcnow().isoformat()`
    で書かれたものが該当)。
    """
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp
