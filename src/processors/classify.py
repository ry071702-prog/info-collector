"""Two-stage classification: filter+genre then full extraction."""
from __future__ import annotations
import json
from datetime import datetime, timezone

from .. import llm_client, logger, prompts, taxonomy
from ..config import settings
from ..models import Flags, FilterResult, ProcessedItem, RawItem

log = logger.get(__name__)


def _freshness_score(timestamp: datetime) -> int:
    """Compute freshness score 0-100 from item timestamp."""
    cfg = settings().get("scoring", {})
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - timestamp).total_seconds() / 3600.0)
    if age_hours <= 24:
        return int(cfg.get("freshness_24h", 100))
    if age_hours <= 72:
        return int(cfg.get("freshness_72h", 70))
    if age_hours <= 24 * 7:
        return int(cfg.get("freshness_1week", 40))
    return int(cfg.get("freshness_old", 10))


def _final_priority(
    importance: str,
    freshness: int,
    streamer: int,
    virality: int,
    trend: int,
) -> str:
    """Compose S/A/B/C from importance + scores using configured weights."""
    cfg = settings().get("scoring", {})
    importance_score = {"S": 100, "A": 75, "B": 50, "C": 25}.get(importance, 25)
    composite = (
        importance_score * cfg.get("weight_importance", 0.5)
        + freshness * cfg.get("weight_freshness", 0.2)
        + streamer * cfg.get("weight_streamer", 0.15)
        + virality * cfg.get("weight_virality", 0.10)
        + trend * cfg.get("weight_trend", 0.05)
    )
    if composite >= cfg.get("final_S_threshold", 80):
        return "S"
    if composite >= cfg.get("final_A_threshold", 60):
        return "A"
    if composite >= cfg.get("final_B_threshold", 35):
        return "B"
    return "C"


def filter_and_genre(item: RawItem) -> FilterResult | None:
    model = settings()["models"]["filter"]
    user = prompts.FILTER_USER.format(
        source=item.platform,
        author=item.author,
        account_type=item.account_type,
        text=item.text[:1500],
        url=item.url,
        timestamp=item.timestamp.isoformat(),
    )
    try:
        data = llm_client.call_json(
            model=model,
            system=prompts.FILTER_SYSTEM,
            user=user,
            max_tokens=256,
        )
        return FilterResult(**data)
    except llm_client.QuotaExhausted:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning(f"filter_and_genre failed for {item.fingerprint}: {e}")
        return None


def classify_full(item: RawItem, genre: str) -> ProcessedItem | None:
    model = settings()["models"]["classify"]
    if genre == "anime":
        system = prompts.CLASSIFY_ANIME_SYSTEM
        tax = taxonomy.ANIME_TAXONOMY
    elif genre == "disney":
        system = prompts.CLASSIFY_DISNEY_SYSTEM
        tax = taxonomy.DISNEY_TAXONOMY
    else:
        system = prompts.CLASSIFY_GAMES_SYSTEM
        tax = taxonomy.GAMES_TAXONOMY

    user = prompts.CLASSIFY_USER_TEMPLATE.format(
        taxonomy=tax,
        source=item.platform,
        author=item.author,
        account_type=item.account_type,
        text=item.text[:2000],
        url=item.url,
        timestamp=item.timestamp.isoformat(),
    )
    try:
        data = llm_client.call_json(
            model=model,
            system=system,
            user=user,
            max_tokens=800,
        )
        flags = Flags(**data["flags"])
        importance = data["importance"]
        risk_level = data.get("risk_level", "low") if data.get("risk_level") in ("low", "middle", "high") else "low"
        streamer = max(0, min(100, int(data.get("streamer_influence_score") or 0)))
        virality = max(0, min(100, int(data.get("clip_virality_score") or 0)))
        trend = max(0, min(100, int(data.get("game_trend_from_streamers_score") or 0)))
        freshness = _freshness_score(item.timestamp)
        final_pri = _final_priority(importance, freshness, streamer, virality, trend)
        return ProcessedItem(
            source_id=item.source_id,
            raw_fingerprint=item.fingerprint,
            timestamp=item.timestamp,
            url=item.url,
            author=item.author,
            genre=genre if genre != "both" else "both",
            subcategory_id=data["subcategory_id"],
            category_name=data["category_name"],
            importance=importance,
            summary=data["summary"],
            title_tags=data.get("title_tags", []),
            entity_tags=data.get("entity_tags", []),
            flags=flags,
            dedup_key=data["dedup_key"],
            raw_text=item.text[:500],
            risk_level=risk_level,
            streamer_influence_score=streamer,
            clip_virality_score=virality,
            game_trend_from_streamers_score=trend,
            freshness_score=freshness,
            final_priority=final_pri,
        )
    except llm_client.QuotaExhausted:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning(f"classify_full failed for {item.fingerprint}: {e}")
        return None


def process(items: list[RawItem]) -> list[ProcessedItem]:
    """Pipeline: filter -> classify. Gemini クォータ枯渇時は残りバッチを早期終了。"""
    out: list[ProcessedItem] = []
    for idx, item in enumerate(items):
        try:
            fr = filter_and_genre(item)
        except llm_client.QuotaExhausted as e:
            log.error(
                f"Aborting classify batch at {idx}/{len(items)} due to Gemini quota exhaustion: {e}"
            )
            break
        if not fr or fr.spam or fr.genre == "neither":
            continue
        # disney は単独 taxonomy で分類。both は games/anime のクロスのみ扱う
        if fr.genre == "disney":
            target = "disney"
        elif fr.genre == "anime":
            target = "anime"
        else:
            target = "games"
        try:
            proc = classify_full(item, target)
        except llm_client.QuotaExhausted as e:
            log.error(
                f"Aborting classify batch at {idx}/{len(items)} due to Gemini quota exhaustion: {e}"
            )
            break
        if proc:
            # if "both", run anime classification too and pick the higher importance one
            if fr.genre == "both":
                try:
                    alt = classify_full(item, "anime")
                except llm_client.QuotaExhausted:
                    alt = None
                if alt and _imp_rank(alt.importance) > _imp_rank(proc.importance):
                    proc = alt
            out.append(proc)
    return out


def _imp_rank(imp: str) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(imp, 0)
