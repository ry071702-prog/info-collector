"""Daily digest and weekly report generation via Claude."""
from __future__ import annotations
import json
from datetime import datetime, timedelta

from .. import llm_client, logger, prompts
from ..config import settings
from ..models import ProcessedItem

log = logger.get(__name__)


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
