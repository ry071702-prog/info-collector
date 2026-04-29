"""Two-stage classification: filter+genre then full extraction."""
from __future__ import annotations
import json
from datetime import datetime

from .. import llm_client, logger, prompts, taxonomy
from ..config import settings
from ..models import Flags, FilterResult, ProcessedItem, RawItem

log = logger.get(__name__)


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
    except Exception as e:  # noqa: BLE001
        log.warning(f"filter_and_genre failed for {item.fingerprint}: {e}")
        return None


def classify_full(item: RawItem, genre: str) -> ProcessedItem | None:
    model = settings()["models"]["classify"]
    if genre == "anime":
        system = prompts.CLASSIFY_ANIME_SYSTEM
        tax = taxonomy.ANIME_TAXONOMY
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
        return ProcessedItem(
            source_id=item.source_id,
            raw_fingerprint=item.fingerprint,
            timestamp=item.timestamp,
            url=item.url,
            author=item.author,
            genre=genre if genre != "both" else "both",
            subcategory_id=data["subcategory_id"],
            category_name=data["category_name"],
            importance=data["importance"],
            summary=data["summary"],
            title_tags=data.get("title_tags", []),
            entity_tags=data.get("entity_tags", []),
            flags=flags,
            dedup_key=data["dedup_key"],
            raw_text=item.text[:500],
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"classify_full failed for {item.fingerprint}: {e}")
        return None


def process(items: list[RawItem]) -> list[ProcessedItem]:
    """Pipeline: filter -> classify."""
    out: list[ProcessedItem] = []
    for item in items:
        fr = filter_and_genre(item)
        if not fr or fr.spam or fr.genre == "neither":
            continue
        # both ⇒ classify under games taxonomy primarily; cross_genre flag captures both
        target = "anime" if fr.genre == "anime" else "games"
        proc = classify_full(item, target)
        if proc:
            # if "both", run anime classification too and pick the higher importance one
            if fr.genre == "both":
                alt = classify_full(item, "anime")
                if alt and _imp_rank(alt.importance) > _imp_rank(proc.importance):
                    proc = alt
            out.append(proc)
    return out


def _imp_rank(imp: str) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(imp, 0)
