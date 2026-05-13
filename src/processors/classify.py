"""Two-stage classification: filter+genre then full extraction."""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timezone

from .. import dedup, llm_client, logger, prompts, taxonomy
from ..config import settings
from ..models import Flags, FilterResult, ProcessedItem, RawItem

log = logger.get(__name__)

_PINNED_GENRES = {"games", "anime", "disney"}
_URL_ONLY_RE = re.compile(r"^(?:https?://\S+\s*)+$", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)
_WORD_RE = re.compile(r"[\w#]+", re.UNICODE)


def _video_trend_score(view_count: int | None, timestamp: datetime) -> int:
    """YouTube 動画の views-per-hour レートから 0-100。

    履歴を持たないので「公開からの経過時間」を分母にした
    平均 views/hour で擬似トレンドを表現する。
    急上昇 (mostPopular) で拾った動画ほど高くなる傾向。

      <100 view/hour       -> 0
      100-1k               -> 30
      1k-10k               -> 50
      10k-50k              -> 70
      50k-200k             -> 90
      200k+                -> 100
    """
    n = int(view_count or 0)
    if n < 1000:
        return 0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_hours = max(1.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600.0)
    rate = n / age_hours
    if rate < 100:
        return 0
    if rate < 1000:
        return 30
    if rate < 10000:
        return 50
    if rate < 50000:
        return 70
    if rate < 200000:
        return 90
    return 100


def _live_trend_score(viewer_count: int | None) -> int:
    """Twitch 同接ベースの live トレンドスコア 0-100。

    バケット式（成長率ではなく絶対値ベース）:
      <100        -> 0   （誰も見ていない / VOD 等）
      100-1k      -> 30  （小規模コミュニティ）
      1k-5k       -> 50  （まあまあ盛り上がり）
      5k-20k      -> 70  （人気配信）
      20k-100k    -> 90  （大型 / バズ）
      100k+       -> 100 （歴史的ピーク級）
    """
    n = int(viewer_count or 0)
    if n < 100:
        return 0
    if n < 1000:
        return 30
    if n < 5000:
        return 50
    if n < 20000:
        return 70
    if n < 100000:
        return 90
    return 100


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
    live: int = 0,
    video: int = 0,
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
        + live * cfg.get("weight_live", 0.10)
        + video * cfg.get("weight_video", 0.10)
    )
    if composite >= cfg.get("final_S_threshold", 80):
        return "S"
    if composite >= cfg.get("final_A_threshold", 60):
        return "A"
    if composite >= cfg.get("final_B_threshold", 35):
        return "B"
    return "C"


def _heuristic_prefilter(item: RawItem) -> FilterResult | None:
    """明らかに情報価値がない raw だけを LLM 前に除外する。"""
    text = (item.text or "").strip()
    if not text:
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="empty-text")
    if _URL_ONLY_RE.fullmatch(text):
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="url-only")
    if len(text) < 30:
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="too-short")

    hashtags = _HASHTAG_RE.findall(text.lower())
    if len(hashtags) >= 5 and len(set(hashtags)) == 1:
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="repeated-hashtag")

    words = _WORD_RE.findall(text.lower())
    if len(words) >= 5:
        word, count = Counter(words).most_common(1)[0]
        if len(word) >= 2 and count / len(words) >= 0.6:
            return FilterResult(spam=True, genre="neither", confidence=1.0, reason="repeated-word")

    non_space = [ch for ch in text if not ch.isspace()]
    if len(non_space) >= 30:
        _, count = Counter(non_space).most_common(1)[0]
        if count / len(non_space) >= 0.8:
            return FilterResult(spam=True, genre="neither", confidence=1.0, reason="repeated-char")

    return None


def filter_and_genre(item: RawItem) -> FilterResult | None:
    extra = item.extra or {}
    source_type = str(extra.get("source_type") or item.account_type or "")
    if source_type == "個人":
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="personal-source-skip")

    prefilter = _heuristic_prefilter(item)
    if prefilter:
        return prefilter

    source_genre = str(extra.get("source_genre") or "")
    if source_genre in _PINNED_GENRES:
        return FilterResult(
            spam=False,
            genre=source_genre,  # type: ignore[arg-type]
            confidence=1.0,
            reason="watchlist-pinned",
        )

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


def should_classify(item: RawItem) -> bool:
    """Cheap pre-filter to protect Gemini quota before any LLM call."""
    if item.fingerprint in _RECENT_RAW_FINGERPRINTS:
        return False

    source_type = str((item.extra or {}).get("source_type") or item.account_type or "")
    return source_type != "個人"


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
            max_tokens=2048,
        )
        flags = Flags(**data["flags"])
        importance = data["importance"]
        risk_level = data.get("risk_level", "low") if data.get("risk_level") in ("low", "middle", "high") else "low"
        streamer = max(0, min(100, int(data.get("streamer_influence_score") or 0)))
        virality = max(0, min(100, int(data.get("clip_virality_score") or 0)))
        trend = max(0, min(100, int(data.get("game_trend_from_streamers_score") or 0)))
        freshness = _freshness_score(item.timestamp)
        # live_trend_score: Twitch コレクターが extra.viewer_count を入れている前提（live のみ非0）
        live = _live_trend_score(item.extra.get("viewer_count") if item.extra else 0)
        # video_trend_score: YouTube 急上昇等で view_count が取得できる場合のみ非0
        video = _video_trend_score(
            item.extra.get("view_count") if item.extra else 0,
            item.timestamp,
        )
        final_pri = _final_priority(importance, freshness, streamer, virality, trend, live, video)
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
            live_trend_score=live,
            video_trend_score=video,
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
    skipped = 0
    for idx, item in enumerate(items):
        if not should_classify(item):
            skipped += 1
            continue
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
    if skipped:
        log.info(f"Skipped {skipped} items before LLM classification")
    return out


def _imp_rank(imp: str) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(imp, 0)


_RECENT_RAW_FINGERPRINTS = dedup.recent_raw_fingerprints(days=30)
