"""Pydantic data models for the pipeline."""
from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Genre = Literal["games", "anime", "both", "neither"]
Importance = Literal["S", "A", "B", "C"]
SourceRole = Literal["公式", "メディア", "個人", "リーカー", "大会", "VTuber"]


class WatchSource(BaseModel):
    id: str
    name: str
    handle: str = ""
    url: str = ""
    platform: Literal["X", "YouTube", "Twitch", "RSS", "Web"]
    genre: Genre
    source_type: SourceRole
    subcategory_hints: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    enabled: bool = True
    check_frequency: Literal["realtime", "hourly", "6h", "daily"] = "6h"
    language: Literal["ja", "en", "multi"] = "ja"
    notes: str = ""


class RawItem(BaseModel):
    """データ収集レイヤーから出る統一フォーマット."""
    source_id: str  # WatchSource.id
    platform: str
    author: str
    account_type: SourceRole
    text: str
    url: str
    timestamp: datetime
    extra: dict = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """同一性チェック用（URL or author+timestamp）."""
        return self.url or f"{self.author}|{self.timestamp.isoformat()}"


class Flags(BaseModel):
    source_role: SourceRole
    speed: Literal["速報", "通常", "アーカイブ"] = "通常"
    spoiler: Literal["なし", "軽微", "重大"] = "なし"
    language: Literal["ja", "en", "multi"] = "ja"
    content_type: Literal["text", "image", "video", "live"] = "text"
    source_reliability: Literal["公式確定", "公式予告中", "信頼リーカー", "噂", "二次"] = "公式確定"
    cross_genre: Literal["ゲーム単独", "アニメ単独", "両方"] = "ゲーム単独"


class FilterResult(BaseModel):
    """Step 1+2 output."""
    spam: bool
    genre: Genre
    confidence: float
    reason: str = ""


RiskLevel = Literal["low", "middle", "high"]


class ProcessedItem(BaseModel):
    """Step 3 output (full classification)."""
    source_id: str
    raw_fingerprint: str
    timestamp: datetime
    url: str
    author: str
    genre: Genre
    subcategory_id: str
    category_name: str
    importance: Importance
    summary: str
    title_tags: list[str] = Field(default_factory=list)
    entity_tags: list[str] = Field(default_factory=list)
    flags: Flags
    dedup_key: str
    raw_text: str = ""
    # β: risk_level + 配信者文脈スコア
    risk_level: RiskLevel = "low"
    streamer_influence_score: int = 0           # 0-100, 配信者界隈での話題量
    clip_virality_score: int = 0                # 0-100, 切り抜き拡散スコア
    game_trend_from_streamers_score: int = 0    # 0-100, 配信者起点のゲームトレンド
    freshness_score: int = 0                    # 0-100, タイムスタンプから自動計算
    final_priority: Importance = "C"            # importance + scores の合成結果
