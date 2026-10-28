"""Daily digest and weekly report generation via Claude."""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

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
            "streamer_name": it.streamer_name,
            "streamer_group": it.streamer_group,
            "is_clip": it.is_clip,
            "related_game_title": it.related_game_title,
            "related_anime_title": it.related_anime_title,
            "summary": it.summary,
            "title_tags": it.title_tags,
            "entity_tags": it.entity_tags,
            "flags": it.flags.model_dump(),
        })
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _digest_items_json(items: list[ProcessedItem]) -> str:
    """daily_digest 用  DIGEST_USER_TEMPLATE が使う項目だけを詰めて送る。

    _items_to_json (全項目・indent=1) だと 403件で入力が約20万トークンになり、
    ダイジェスト1本で1日 約¥11 かかっていた (2026-10-28 実測)。
    スコア類・配信者メタは指示文で使っていないので落とす。
    """
    payload = []
    for it in items:
        payload.append({
            "url": it.url,
            "author": it.author,
            "timestamp": it.timestamp.isoformat(timespec="minutes"),
            "genre": it.genre,
            "category_name": it.category_name,
            "importance": it.importance,
            "risk_level": it.risk_level,
            "summary": it.summary,
            "title_tags": it.title_tags,
            "entity_tags": it.entity_tags,
            # 速報件数・発信元別・[ネタバレ] の判定に使う
            "speed": it.flags.speed,
            "source_role": it.flags.source_role,
            "spoiler": it.flags.spoiler,
        })
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ダイジェストに載せる件数の上限  出力上限 4096 トークンに収めるため (1行 約70トークン)
# S/A を全部並べると 2026-10-28 は 214件中 45〜49件で途切れ、後半のセクションとサマリーが出なかった
# 指示文で上限だけ伝えると、S が 32件あるのに A を15件選んだので、選ぶのはコードでやる
DIGEST_TOP_MAX = 15
DIGEST_GENRE_MAX = 5
DIGEST_RISK_MAX = 5
_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}


def _newest_first(it: ProcessedItem) -> float:
    ts = it.timestamp if it.timestamp.tzinfo else it.timestamp.replace(tzinfo=timezone.utc)
    return -ts.timestamp()


def _digest_pick(items: list[ProcessedItem]) -> dict[str, list[ProcessedItem]]:
    """セクションごとに載せる item を選ぶ  上段は S→A、同じ重要度なら速報→新しい順  高リスクは別枠"""
    seen: set[str] = set()
    pool: list[ProcessedItem] = []
    for it in items:
        if it.dedup_key in seen:
            continue
        seen.add(it.dedup_key)
        pool.append(it)
    pool.sort(key=lambda it: (_RANK.get(it.importance, 3), it.flags.speed != "速報", _newest_first(it)))
    safe = [it for it in pool if it.risk_level != "high"]
    return {
        "top": [it for it in safe if it.importance in ("S", "A")][:DIGEST_TOP_MAX],
        "games": [it for it in safe if it.importance == "B" and it.genre == "games"][:DIGEST_GENRE_MAX],
        "anime": [it for it in safe if it.importance == "B" and it.genre == "anime"][:DIGEST_GENRE_MAX],
        "risk": [it for it in pool if it.risk_level == "high"][:DIGEST_RISK_MAX],
    }


def _digest_stats(items: list[ProcessedItem], picked: dict[str, list[ProcessedItem]]) -> dict:
    """サマリー用の件数  載せなかった分も含めて全件で数える"""
    important = sum(1 for it in items if it.importance in ("S", "A") and it.risk_level != "high")
    tags: Counter[str] = Counter(t for it in items if it.risk_level != "high" for t in it.title_tags)
    return {
        "総件数": len(items),
        "速報件数": sum(1 for it in items if it.flags.speed == "速報"),
        "重要件数(S/A)": important,
        "通常件数": sum(1 for it in items if it.flags.speed == "通常"),
        "S/Aで載せなかった件数": important - len(picked["top"]),
        "発信元別": dict(Counter(it.flags.source_role for it in items).most_common()),
        "注目タグTOP5": [[t, n] for t, n in tags.most_common(5)],
    }


def daily_digest(items: list[ProcessedItem], date_str: str) -> str:
    model = settings()["models"]["digest"]
    picked = _digest_pick(items)
    user = prompts.DIGEST_USER_TEMPLATE.format(
        date=date_str,
        items_json=_digest_items_json([it for section in picked.values() for it in section]),
        stats_json=json.dumps(_digest_stats(items, picked), ensure_ascii=False, separators=(",", ":")),
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
