"""Daily digest and weekly report generation via Claude."""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from .. import llm_client, logger, prompts, watchlist
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


def _digest_items_json(items: list[ProcessedItem], folded: dict[str, list[ProcessedItem]] | None = None) -> str:
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
        group = (folded or {}).get(it.dedup_key, [])
        if group:
            # 代表は記事を優先して選ぶので、S の切り抜きを束ねた A の記事が A のまま出ないようにする
            payload[-1]["importance"] = min([it, *group], key=lambda m: _RANK.get(m.importance, 3)).importance
        also = _also_authors(it, folded or {})
        if also:
            payload[-1]["also"] = also
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _also_authors(it: ProcessedItem, folded: dict[str, list[ProcessedItem]]) -> list[str]:
    """同じ作品で束ねた別 URL の媒体名  指示文で「（ほか 媒体名）」と書かせる

    切り抜きは1作品に10件近く束なるので、行が伸びないよう先頭3つまで
    """
    return list(dict.fromkeys(o.author for o in folded.get(it.dedup_key, []) if o.author != it.author))[:DIGEST_ALSO_MAX]


# ダイジェストに載せる件数の上限  出力上限 4096 トークンに収めるため (1行 約70トークン)
# S/A を全部並べると 2026-10-28 は 214件中 45〜49件で途切れ、後半のセクションとサマリーが出なかった
# 指示文で上限だけ伝えると、S が 32件あるのに A を15件選んだので、選ぶのはコードでやる
DIGEST_TOP_MAX = 15
DIGEST_GENRE_MAX = 5
DIGEST_RISK_MAX = 5
# YouTube 検索・急上昇で拾った一般の投稿 (切り抜き・配信) の上限  公式チャンネルは platform=YouTube なので対象外
# 2026-10-28 は上段15件中13件がこの枠だった  LLM が付ける flags は切り抜きでも source_role=公式・
# content_type=text になっていて見分けられないので、収集元の platform で判定する
FEED_PLATFORMS = ("YouTubeSearch", "YouTubeTrending")
DIGEST_FEED_TOP_MAX = 3
DIGEST_FEED_GENRE_MAX = 2
DIGEST_ALSO_MAX = 3
_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}
# 作品名の欄に入った作品名でない値  これで束ねると別作品・別の出来事がまとまる (全日分の processed から拾った)
# 機種・ブランド名もここに入れる (xbox で束ねると議員の発言と CEO の表明が1行になった)
_NOT_TITLES = {
    "anime", "アニメ", "game", "ゲーム", "不明", "未指定", "なし", "none", "unknown", "null", "rpg", "mmo",
    "ps5", "playstation", "playstation5", "playstation6", "xbox", "nintendo", "任天堂",
    "nintendoswitch", "nintendoswitch2", "switch2", "steam",
}


def _feed_source_ids() -> set[str]:
    """YouTube 検索・急上昇の source id  watchlist.load() は Sheets 同期の副作用があるので CSV を直接読む

    CSV が壊れていてもダイジェストは止めない  上限なしで作る
    """
    try:
        sources = watchlist._load_from_csv(watchlist.LOCAL_CACHE)
    except Exception as e:
        log.warning(f"Failed to read {watchlist.LOCAL_CACHE}; YouTube feed cap disabled: {e}")
        return set()
    return {s.id for s in sources if s.platform in FEED_PLATFORMS}


def _newest_first(it: ProcessedItem) -> float:
    ts = it.timestamp if it.timestamp.tzinfo else it.timestamp.replace(tzinfo=timezone.utc)
    return -ts.timestamp()


def _fold_key(it: ProcessedItem) -> tuple[str, str] | None:
    """同じ話題として束ねるキー  載る欄 (高リスク / S・A / ゲームの B / アニメの B) と作品名

    タグの重なりで束ねると別作品がくっついた (PS5+発売日 など) ので作品名の一致で見る
    同じ作品の別の出来事も1行にまとまる (10/28 の GTA VI は容量・労組投票 (2媒体)・Edge 誌の4件)  1作品1行で枠を空けるほうを取った
    カテゴリは揃えない  LLM が記事ごとに揺れて付けるので、同じ出来事が割れて 138日分で余分な行が 1→112 に増えた
    作品名が空・作品名でない値なら束ねない  表記ゆれ (VI と 6) は指示文の「同じ出来事は1行に」に任せる
    """
    title = re.sub(r"[\W_]+", "", (it.related_game_title or it.related_anime_title).lower())
    if len(title) < 2 or title in _NOT_TITLES:
        return None
    if it.risk_level == "high":
        section = "risk"
    elif it.importance in ("S", "A"):
        section = "top"
    elif it.importance == "B" and it.genre in ("games", "anime"):
        section = it.genre
    else:
        return None
    return section, title


def _fold_same_title(pool: list[ProcessedItem], feed_ids: frozenset[str] | set[str]) -> tuple[list[ProcessedItem], dict[str, list[ProcessedItem]]]:
    """同じ話題の item を代表1件に束ねる  代表は YouTube 検索枠以外を優先し、グループの最上位の位置に置く

    切り抜きが代表になると、上限で落ちたときに同じ話題の記事ごと消えるため
    位置を代表に合わせると、S の切り抜きを束ねた A の記事が A の後ろに下がるため
    """
    groups: dict[tuple[str, str], list[ProcessedItem]] = {}
    for it in pool:
        key = _fold_key(it)
        if key:
            groups.setdefault(key, []).append(it)
    reps: list[ProcessedItem] = []
    folded: dict[str, list[ProcessedItem]] = {}
    for it in pool:
        key = _fold_key(it)
        members = groups.get(key, [it]) if key else [it]
        if members[0] is not it:
            continue
        rep = next((m for m in members if m.source_id not in feed_ids), it)
        reps.append(rep)
        if len(members) > 1:
            folded[rep.dedup_key] = [m for m in members if m is not rep]
    return reps, folded


def _take(items: list[ProcessedItem], limit: int, feed_ids: frozenset[str] | set[str], feed_limit: int) -> list[ProcessedItem]:
    out: list[ProcessedItem] = []
    feed = 0
    for it in items:
        if len(out) >= limit:
            break
        if it.source_id in feed_ids:
            if feed >= feed_limit:
                continue
            feed += 1
        out.append(it)
    return out


def _digest_pick(
    items: list[ProcessedItem], feed_ids: frozenset[str] | set[str] = frozenset()
) -> tuple[dict[str, list[ProcessedItem]], dict[str, list[ProcessedItem]]]:
    """セクションごとに載せる item を選ぶ  上段は S→A、同じ重要度なら速報→新しい順  高リスクは別枠

    Returns: (セクション別の item, 代表の dedup_key → 束ねた item)
    """
    seen: set[str] = set()
    pool: list[ProcessedItem] = []
    for it in items:
        if it.dedup_key in seen:
            continue
        seen.add(it.dedup_key)
        pool.append(it)
    pool.sort(key=lambda it: (_RANK.get(it.importance, 3), it.flags.speed != "速報", _newest_first(it)))
    pool, folded = _fold_same_title(pool, feed_ids)
    safe = [it for it in pool if it.risk_level != "high"]
    picked = {
        "top": _take([it for it in safe if it.importance in ("S", "A")], DIGEST_TOP_MAX, feed_ids, DIGEST_FEED_TOP_MAX),
        "games": _take([it for it in safe if it.importance == "B" and it.genre == "games"], DIGEST_GENRE_MAX, feed_ids, DIGEST_FEED_GENRE_MAX),
        "anime": _take([it for it in safe if it.importance == "B" and it.genre == "anime"], DIGEST_GENRE_MAX, feed_ids, DIGEST_FEED_GENRE_MAX),
        "risk": [it for it in pool if it.risk_level == "high"][:DIGEST_RISK_MAX],
    }
    shown = {it.dedup_key for section in picked.values() for it in section}
    return picked, {k: v for k, v in folded.items() if k in shown}


def _digest_stats(
    items: list[ProcessedItem], picked: dict[str, list[ProcessedItem]], folded: dict[str, list[ProcessedItem]] | None = None
) -> dict:
    """サマリー用の件数  載せなかった分も含めて全件で数える  束ねた分は「ほか」に媒体名が出たものだけ載せた扱い"""
    important = sum(1 for it in items if it.importance in ("S", "A") and it.risk_level != "high")
    tags: Counter[str] = Counter(t for it in items if it.risk_level != "high" for t in it.title_tags)
    folded = folded or {}
    shown = sum(
        1 + sum(1 for o in folded.get(it.dedup_key, []) if o.author in _also_authors(it, folded)) for it in picked["top"]
    )
    return {
        "総件数": len(items),
        "速報件数": sum(1 for it in items if it.flags.speed == "速報"),
        "重要件数(S/A)": important,
        "通常件数": sum(1 for it in items if it.flags.speed == "通常"),
        "S/Aで載せなかった件数": important - shown,
        "発信元別": dict(Counter(it.flags.source_role for it in items).most_common()),
        "注目タグTOP5": [[t, n] for t, n in tags.most_common(5)],
    }


def daily_digest(items: list[ProcessedItem], date_str: str) -> str:
    model = settings()["models"]["digest"]
    picked, folded = _digest_pick(items, _feed_source_ids())
    user = prompts.DIGEST_USER_TEMPLATE.format(
        date=date_str,
        items_json=_digest_items_json([it for section in picked.values() for it in section], folded),
        stats_json=json.dumps(_digest_stats(items, picked, folded), ensure_ascii=False, separators=(",", ":")),
        # 件数を明示しないと選別済みでも上段の item を落とした (10/28 のデータで5回とも1〜5件  件数を渡したら3回とも全件出た)
        top_count=len(picked["top"]),
        games_count=len(picked["games"]),
        anime_count=len(picked["anime"]),
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
