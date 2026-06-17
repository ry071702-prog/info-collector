"""キャッチアップ便: 直近の重要記事を厳選して1通のメールで送る。

朝(8時)/昼(12時)/夕方(18時) の3便を想定。各便は「前回便以降の重要上位5件」を
選び、便をまたいだ重複は catchup_sent.json で抑止する (溜めずに流す設計)。

使い方:
    python -m src.jobs.send_catchup [morning|noon|evening]
    引数なしのときは現在の JST 時刻からスロットを推定する。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from .. import logger
from ..config import DATA_DIR, cache_dir
from ..models import ProcessedItem
from ..outputs import discord, email_digest, slack_digest
from ..storage import read_processed

log = logger.get(__name__)

JST = timezone(timedelta(hours=9))
SENT_FILE = cache_dir() / "catchup_sent.json"
SENT_RETAIN_DAYS = 3
LOOKBACK_HOURS = 16          # 便間の最大ギャップ(14h)+ 余裕
MAX_ITEMS = 5
MAX_PER_GENRE = 3           # 1便あたり同一ジャンルの上限 (偏り防止)
_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}

SLOTS = {
    "morning": "朝のニュース",
    "noon": "昼のニュース",
    "evening": "夕方のニュース",
}


def _slot_from_hour(hour: int) -> str:
    """JST 時刻から最も近いスロットを決める。"""
    if hour < 10:
        return "morning"
    if hour < 15:
        return "noon"
    return "evening"


def _load_sent() -> dict[str, str]:
    if not SENT_FILE.exists():
        return {}
    try:
        return json.loads(SENT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_sent(d: dict[str, str]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SENT_RETAIN_DAYS)).isoformat()
    d = {k: v for k, v in d.items() if v >= cutoff}
    SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENT_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _recent_candidates(now: datetime) -> list[ProcessedItem]:
    """直近 LOOKBACK_HOURS の processed を集める (UTC日付の今日+昨日を走査)。"""
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    items: list[ProcessedItem] = []
    for offset in (0, 1):
        date_str = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        items.extend(read_processed(date_str))
    out: list[ProcessedItem] = []
    for it in items:
        ts = it.timestamp if it.timestamp.tzinfo else it.timestamp.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            out.append(it)
    return out


def _select(items: list[ProcessedItem], sent: dict[str, str]) -> list[ProcessedItem]:
    """重要度順 + ジャンル分散で上位 MAX_ITEMS を選ぶ。送信済み・高リスクは除外。"""
    # 同一URLの重複を畳む
    seen_keys: set[str] = set()
    pool: list[ProcessedItem] = []
    for it in items:
        if it.dedup_key in sent:
            continue
        if it.risk_level == "high":  # 未確認(噂)は便に載せない
            continue
        if it.final_priority not in ("S", "A", "B"):
            continue
        if it.dedup_key in seen_keys:
            continue
        seen_keys.add(it.dedup_key)
        pool.append(it)

    def sort_key(it: ProcessedItem):
        ts = it.timestamp if it.timestamp.tzinfo else it.timestamp.replace(tzinfo=timezone.utc)
        return (_RANK.get(it.final_priority, 3), -it.freshness_score, -ts.timestamp())

    pool.sort(key=sort_key)

    picked: list[ProcessedItem] = []
    genre_count: dict[str, int] = {}
    # まずジャンル上限を尊重して選ぶ
    for it in pool:
        if len(picked) >= MAX_ITEMS:
            break
        if genre_count.get(it.genre, 0) >= MAX_PER_GENRE:
            continue
        picked.append(it)
        genre_count[it.genre] = genre_count.get(it.genre, 0) + 1
    # 枠が余ったら上限を無視して補充
    if len(picked) < MAX_ITEMS:
        for it in pool:
            if len(picked) >= MAX_ITEMS:
                break
            if it not in picked:
                picked.append(it)
    return picked


def _hero(date_jst: str) -> tuple[str | None, str | None]:
    """当日の新聞画像があればヒーロー画像URLとして使う。"""
    base = DATA_DIR.parent / "site" / "public" / "newspaper-img"
    for ext in ("png", "jpg"):
        if (base / f"{date_jst}.{ext}").exists():
            site = email_digest._site_url()
            return f"{site}/newspaper-img/{date_jst}.{ext}", f"{site}/newspaper/{date_jst}/"
    return None, None


def _audio(date_jst: str) -> str | None:
    """当日の1分音声ダイジェスト (process_digest が生成) があればURLを返す。"""
    base = DATA_DIR.parent / "site" / "public" / "audio"
    for ext in ("mp3", "wav"):
        if (base / f"{date_jst}.{ext}").exists():
            return f"{email_digest._site_url()}/audio/{date_jst}.{ext}"
    return None


def main() -> None:
    now = datetime.now(timezone.utc)
    now_jst = now.astimezone(JST)
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    slot = arg if arg in SLOTS else _slot_from_hour(now_jst.hour)
    slot_label = SLOTS[slot]
    date_label = now_jst.strftime("%-m月%-d日")
    date_jst = now_jst.strftime("%Y-%m-%d")

    sent = _load_sent()
    # 便×日付マーカー: 同じ便(slot)をその日のうちに二度送らない。
    # 保険トリガー(GitHub純正cronの大幅遅延・cron-job.org)が後から発火しても、
    # 新着が増えていても再送しない (item単位dedupとは別の冪等ガード)。
    slot_marker = f"__slot__:{slot}:{date_jst}"
    if slot_marker in sent:
        log.info(f"catchup[{slot}]: {date_jst} はこの便を配信済みのためスキップ (便×日付の重複防止)")
        return
    candidates = _recent_candidates(now)
    picked = _select(candidates, sent)
    log.info(f"catchup[{slot}]: 候補{len(candidates)}件 → 選定{len(picked)}件")

    if not picked:
        log.info("送る新着がないため送信スキップ (溜めない設計)")
        return

    hero_url, newspaper_url = _hero(date_jst)
    audio_url = _audio(date_jst)
    site_url = email_digest._site_url()

    # 各チャネルへ展開 (設定されているものだけ送られる)。1つでも届けば既送扱い。
    results = {
        "email": email_digest.send_digest(
            picked,
            slot_label=slot_label,
            date_label=date_label,
            hero_image_url=hero_url,
            newspaper_url=newspaper_url,
            audio_url=audio_url,
        ),
        "slack": slack_digest.send_digest(
            picked, slot_label=slot_label, date_label=date_label, audio_url=audio_url
        ),
        "discord": discord.post_digest(
            picked, slot_label=slot_label, date_label=date_label,
            audio_url=audio_url, site_url=site_url,
        ),
    }
    delivered = [ch for ch, ok in results.items() if ok]
    log.info(f"配信結果: {results}")

    if delivered:
        now_iso = now.isoformat()
        for it in picked:
            sent[it.dedup_key] = now_iso
        sent[slot_marker] = now_iso  # 便×日付マーカー: 後発の保険トリガーによる再送を防ぐ
        _save_sent(sent)
        log.info(f"配信完了 ({'/'.join(delivered)}) + 既送マーク {len(picked)}件")
    else:
        log.info("どのチャネルにも配信されず (既送マークしない)")


if __name__ == "__main__":
    main()
