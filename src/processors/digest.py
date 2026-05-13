"""Daily digest and weekly report generation via Claude."""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timedelta

from .. import llm_client, logger, prompts
from ..config import settings
from ..models import ProcessedItem

log = logger.get(__name__)


def cross_source_trends(items: list[ProcessedItem], min_count: int = 3, top_n: int = 10) -> list[tuple[str, int, list[ProcessedItem]]]:
    """同じ entity_tag が複数 item に出ているものを上位 N 件返す。

    Returns: [(entity, count, related_items), ...] count >= min_count 降順。
    risk_level=high の item は集計から除外。
    """
    counts: Counter[str] = Counter()
    by_entity: dict[str, list[ProcessedItem]] = {}
    for it in items:
        if it.risk_level == "high":
            continue
        for tag in it.entity_tags:
            tag_n = tag.strip()
            if not tag_n or len(tag_n) < 2:
                continue
            counts[tag_n] += 1
            by_entity.setdefault(tag_n, []).append(it)
    out = []
    for entity, n in counts.most_common(top_n * 3):
        if n < min_count:
            break
        out.append((entity, n, by_entity[entity][:5]))
        if len(out) >= top_n:
            break
    return out


def _items_to_json(items: list[ProcessedItem]) -> str:
    payload = []
    for it in items:
        payload.append({
            "url": it.url,
            "author": it.author,
            "timestamp": it.timestamp.isoformat(),
            "genre": it.genre,
            "subcategory_id": it.subcategory_id,
            "category_name": it.category_name,
            "importance": it.importance,
            "final_priority": it.final_priority,
            "risk_level": it.risk_level,
            "freshness_score": it.freshness_score,
            "streamer_influence_score": it.streamer_influence_score,
            "clip_virality_score": it.clip_virality_score,
            "game_trend_from_streamers_score": it.game_trend_from_streamers_score,
            "live_trend_score": it.live_trend_score,
            "video_trend_score": it.video_trend_score,
            "summary": it.summary,
            "title_tags": it.title_tags,
            "entity_tags": it.entity_tags,
            "flags": it.flags.model_dump(),
        })
    return json.dumps(payload, ensure_ascii=False, indent=1)


def daily_digest(items: list[ProcessedItem], date_str: str) -> str:
    model = settings()["models"]["digest"]
    user = prompts.DIGEST_USER_TEMPLATE.format(
        date=date_str,
        items_json=_items_to_json(items),
    )
    return llm_client.call_text(
        model=model,
        system=prompts.DIGEST_SYSTEM,
        user=user,
        max_tokens=4096,
        temperature=0.3,
    )


def weekly_report(items: list[ProcessedItem], week_start: datetime, week_end: datetime) -> str:
    model = settings()["models"]["weekly_report"]
    user = prompts.WEEKLY_USER_TEMPLATE.format(
        week_start=week_start.strftime("%Y-%m-%d"),
        week_end=week_end.strftime("%Y-%m-%d"),
        items_json=_items_to_json(items),
    )
    return llm_client.call_text(
        model=model,
        system=prompts.WEEKLY_SYSTEM,
        user=user,
        max_tokens=8000,
        temperature=0.4,
    )
