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

# Gemini が稀に Literal 外の値を返すので、安全な既定値に丸めるホワイトリスト
_VALID_SPOILER = {"なし", "軽微", "重大"}
_VALID_CROSS_GENRE = {
    "ゲーム単独", "アニメ単独", "Disney単独", "両方", "ゲーム+Disney", "アニメ+Disney", "その他",
}
_VALID_SPEED = {"速報", "通常", "アーカイブ"}
_VALID_CONTENT_TYPE = {"text", "image", "video", "live"}
_VALID_SOURCE_RELIABILITY = {"公式確定", "公式予告中", "信頼リーカー", "噂", "二次"}
_VALID_LANGUAGE = {"ja", "en", "multi"}
_VALID_SOURCE_ROLE = {"公式", "メディア", "個人", "リーカー", "大会", "VTuber"}


def _coerce_flags(raw: dict | None) -> dict:
    """Gemini 出力の Flags を安全な既定値に丸める（Literal バリデーション失敗を防ぐ）。"""
    out = dict(raw or {})
    if out.get("spoiler") not in _VALID_SPOILER:
        out["spoiler"] = "なし"
    if out.get("cross_genre") not in _VALID_CROSS_GENRE:
        out["cross_genre"] = "その他"
    if out.get("speed") not in _VALID_SPEED:
        out["speed"] = "通常"
    if out.get("content_type") not in _VALID_CONTENT_TYPE:
        out["content_type"] = "text"
    if out.get("source_reliability") not in _VALID_SOURCE_RELIABILITY:
        out["source_reliability"] = "公式確定"
    if out.get("language") not in _VALID_LANGUAGE:
        out["language"] = "ja"
    if out.get("source_role") not in _VALID_SOURCE_ROLE:
        out["source_role"] = "メディア"
    return out
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
    # バケット境界 (100/1k/10k/50k/200k) が経過時間の微小なドリフトで
    # 揺れないよう、丸めてから判定する。例: 100k views / 10h はちょうど
    # 10k/hour = 70 バケットに乗せたいが、実経過が 10h+ε だと rate が
    # 9999.99... になり 50 バケットへ落ちてしまうため。
    rate = round(n / age_hours)
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


def _filter_without_llm(item: RawItem) -> FilterResult | None:
    """LLM を呼ばずに判定できる分だけ返す。決められなければ None（= LLM 行き）。"""
    extra = item.extra or {}
    source_type = str(extra.get("source_type") or item.account_type or "")
    if source_type == "個人":
        return FilterResult(spam=True, genre="neither", confidence=1.0, reason="personal-source-skip")

    prefilter = _heuristic_prefilter(item)
    if prefilter:
        return prefilter

    source_genre = str(extra.get("source_genre") or "")
    # 公式ソースのみ pin（信号対雑音比が高い）。メディア系は genre 横断するので Gemini フィルタで判定。
    if source_genre in _PINNED_GENRES and source_type == "公式":
        return FilterResult(
            spam=False,
            genre=source_genre,  # type: ignore[arg-type]
            confidence=1.0,
            reason="watchlist-pinned-official",
        )
    return None


def filter_and_genre(item: RawItem) -> FilterResult | None:
    pre = _filter_without_llm(item)
    if pre is not None:
        return pre

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


def _genre_prompt(genre: str) -> tuple[str, str]:
    """genre -> (system prompt, taxonomy)。"""
    if genre == "anime":
        return prompts.CLASSIFY_ANIME_SYSTEM, taxonomy.ANIME_TAXONOMY
    if genre == "disney":
        return prompts.CLASSIFY_DISNEY_SYSTEM, taxonomy.DISNEY_TAXONOMY
    return prompts.CLASSIFY_GAMES_SYSTEM, taxonomy.GAMES_TAXONOMY


def _build_processed(item: RawItem, data: dict, genre: str) -> ProcessedItem:
    """LLM の生 JSON 1件分 -> ProcessedItem。単件・バッチ両経路で共用。

    必須キー欠落などは例外を投げる（呼び出し側が握って None 扱いにする）。
    """
    flags = Flags(**_coerce_flags(data.get("flags")))
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
        genre=genre if genre != "both" else "both",  # type: ignore[arg-type]
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
        final_priority=final_pri,  # type: ignore[arg-type]
        streamer_name=str(data.get("streamer_name") or "")[:80],
        streamer_group=str(data.get("streamer_group") or "")[:80],
        is_clip=bool(data.get("is_clip", False)),
        related_game_title=str(data.get("related_game_title") or "")[:120],
        related_anime_title=str(data.get("related_anime_title") or "")[:120],
    )


def classify_full(item: RawItem, genre: str) -> ProcessedItem | None:
    model = settings()["models"]["classify"]
    system, tax = _genre_prompt(genre)

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
        return _build_processed(item, data, genre)
    except llm_client.QuotaExhausted:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning(f"classify_full failed for {item.fingerprint}: {e}")
        return None


# ============================================================
# バッチ LLM 呼び出し (コスト削減 2026-07-13)
#
# 1件1呼び出しだと判定ルール文 (filter 約570tok / classify は taxonomy 込み約1,140tok)
# を毎件送ることになる。実測 (2026-07-06 / raw 730件) では classify 入力 1.20M tok の
# うち 0.52M tok = 43% が taxonomy の再送だった。まとめて送れば入力が大幅に減る。
#
# 出力トークンは減らないので、削減効果は入力側のみ。
# バッチが失敗したら必ず単件にフォールバックする（安さより落とさないことを優先）。
# ============================================================
def _batch_item_text(idx: int, item: RawItem, text_limit: int) -> str:
    return prompts.BATCH_ITEM_TEMPLATE.format(
        id=idx,
        source=item.platform,
        author=item.author,
        account_type=item.account_type,
        text=item.text[:text_limit],
        url=item.url,
        timestamp=item.timestamp.isoformat(),
    )


def _results_by_id(data: dict, n: int) -> dict[int, dict]:
    """LLM の {"results":[{"id":..}]} を id -> dict に。範囲外 id は捨てる。"""
    out: dict[int, dict] = {}
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id")
        if raw_id is None:
            continue
        try:
            i = int(raw_id)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            out[i] = row
    return out


def filter_and_genre_batch(items: list[RawItem]) -> dict[int, FilterResult | None]:
    """複数件を1回の LLM 呼び出しで filter。返らなかった件は欠番（呼び出し側が単件で埋める）。"""
    if not items:
        return {}
    model = settings()["models"]["filter"]
    body = "\n\n".join(_batch_item_text(i, it, 1500) for i, it in enumerate(items))
    user = prompts.FILTER_BATCH_USER.format(n=len(items), items=body)
    # 1件あたり約60tok + 余裕
    max_tokens = min(8192, 200 * len(items) + 512)
    data = llm_client.call_json(
        model=model, system=prompts.FILTER_SYSTEM, user=user, max_tokens=max_tokens
    )
    rows = _results_by_id(data, len(items))
    out: dict[int, FilterResult | None] = {}
    for i, row in rows.items():
        row.pop("id", None)
        try:
            out[i] = FilterResult(**row)
        except Exception as e:  # noqa: BLE001
            log.warning(f"filter batch: bad row id={i}: {e}")
    return out


def classify_full_batch(pairs: list[tuple[int, RawItem]], genre: str) -> dict[int, ProcessedItem]:
    """同一 genre の複数件を1回の LLM 呼び出しで classify。taxonomy は1回だけ送る。

    pairs は (呼び出し側のキー, item)。返らなかった件は欠番。
    """
    if not pairs:
        return {}
    model = settings()["models"]["classify"]
    system, tax = _genre_prompt(genre)
    items = [it for _, it in pairs]
    body = "\n\n".join(_batch_item_text(i, it, 2000) for i, it in enumerate(items))
    user = prompts.CLASSIFY_BATCH_USER_TEMPLATE.format(taxonomy=tax, n=len(items), items=body)
    # 1件あたり実測 約250tok（processed 実績）。余裕を持って 600tok/件
    max_tokens = min(32768, 600 * len(items) + 1024)
    data = llm_client.call_json(model=model, system=system, user=user, max_tokens=max_tokens)
    rows = _results_by_id(data, len(items))
    out: dict[int, ProcessedItem] = {}
    for i, row in rows.items():
        key, item = pairs[i]
        try:
            out[key] = _build_processed(item, row, genre)
        except Exception as e:  # noqa: BLE001
            log.warning(f"classify batch: bad row id={i} ({item.fingerprint}): {e}")
    return out


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def process(items: list[RawItem]) -> list[ProcessedItem]:
    """Pipeline: filter -> classify. Gemini クォータ枯渇時は残りバッチを早期終了。

    LLM 呼び出しはまとめて行い（コスト削減）、返らなかった件だけ単件で埋める。
    settings の [cost] batch_llm = false で単件のみの旧挙動に戻せる。
    """
    cfg = settings()
    cost_cfg = cfg.get("cost", {}) or {}
    use_batch = bool(cost_cfg.get("batch_llm", True))
    f_size = int(cost_cfg.get("filter_batch", 25))
    c_size = int(cost_cfg.get("classify_batch", 10))

    out: list[ProcessedItem] = []
    skipped = 0
    quota_dead = False

    # ---- Stage 0: LLM 前の足切り ----
    candidates: list[RawItem] = []
    for item in items:
        if not should_classify(item):
            skipped += 1
            continue
        candidates.append(item)

    # ---- Stage 1: filter (ヒューリスティック/pin で決まる分は LLM を呼ばない) ----
    verdicts: dict[int, FilterResult | None] = {}
    need_llm: list[int] = []
    for i, item in enumerate(candidates):
        pre = _filter_without_llm(item)
        if pre is not None:
            verdicts[i] = pre
        else:
            need_llm.append(i)

    if use_batch and need_llm:
        for group in _chunks(need_llm, f_size):
            if quota_dead:
                break
            batch_items = [candidates[i] for i in group]
            try:
                f_got = filter_and_genre_batch(batch_items)
            except llm_client.QuotaExhausted as e:
                log.error(f"Aborting at filter batch due to Gemini quota exhaustion: {e}")
                quota_dead = True
                break
            except Exception as e:  # noqa: BLE001
                log.warning(f"filter batch failed ({len(group)} items); falling back to per-item: {e}")
                f_got = {}
            for local_i, gi in enumerate(group):
                if local_i in f_got:
                    verdicts[gi] = f_got[local_i]

    # バッチで返らなかった / バッチ無効 の分を単件で埋める
    for i in need_llm:
        if quota_dead:
            break
        if i in verdicts:
            continue
        try:
            verdicts[i] = filter_and_genre(candidates[i])
        except llm_client.QuotaExhausted as e:
            log.error(f"Aborting at filter (single) due to Gemini quota exhaustion: {e}")
            quota_dead = True
            break

    # ---- Stage 2: classify (genre ごとにまとめる = taxonomy を1回だけ送る) ----
    by_genre: dict[str, list[tuple[int, RawItem]]] = {}
    both_ids: set[int] = set()
    for i, item in enumerate(candidates):
        fr = verdicts.get(i)
        if not fr or fr.spam or fr.genre == "neither":
            continue
        # disney は単独 taxonomy で分類。both は games/anime のクロスのみ扱う
        if fr.genre == "disney":
            target = "disney"
        elif fr.genre == "anime":
            target = "anime"
        else:
            target = "games"
        by_genre.setdefault(target, []).append((i, item))
        if fr.genre == "both":
            both_ids.add(i)
            # both は anime 側でも分類し、重要度の高い方を採る
            by_genre.setdefault("anime", []).append((i, item))

    results: dict[str, dict[int, ProcessedItem]] = {}
    for genre, pairs in by_genre.items():
        got: dict[int, ProcessedItem] = {}
        if use_batch and not quota_dead:
            for group in _chunks(pairs, c_size):
                if quota_dead:
                    break
                try:
                    got.update(classify_full_batch(group, genre))
                except llm_client.QuotaExhausted as e:
                    log.error(f"Aborting at classify batch due to Gemini quota exhaustion: {e}")
                    quota_dead = True
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        f"classify batch failed (genre={genre}, {len(group)} items); "
                        f"falling back to per-item: {e}"
                    )
        # 返らなかった分を単件で埋める
        for key, item in pairs:
            if quota_dead:
                break
            if key in got:
                continue
            try:
                proc = classify_full(item, genre)
            except llm_client.QuotaExhausted as e:
                log.error(f"Aborting at classify (single) due to Gemini quota exhaustion: {e}")
                quota_dead = True
                break
            if proc:
                got[key] = proc
        results[genre] = got

    # ---- Stage 3: 元の順序で組み立て (both は重要度の高い方を採用) ----
    for i in range(len(candidates)):
        fr = verdicts.get(i)
        if not fr or fr.spam or fr.genre == "neither":
            continue
        primary = "disney" if fr.genre == "disney" else ("anime" if fr.genre == "anime" else "games")
        proc = results.get(primary, {}).get(i)
        if i in both_ids:
            alt = results.get("anime", {}).get(i)
            if alt and (not proc or _imp_rank(alt.importance) > _imp_rank(proc.importance)):
                proc = alt
        if proc:
            out.append(proc)

    if skipped:
        log.info(f"Skipped {skipped} items before LLM classification")
    return out


def _imp_rank(imp: str) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(imp, 0)


_RECENT_RAW_FINGERPRINTS = dedup.recent_raw_fingerprints(days=30)
