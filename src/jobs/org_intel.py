"""組織インテリジェンス・エージェント(★6・parallel org mode)。

競合/業界/採用市場の `config/watchlist_org.csv` を自律監視 → 前回スナップショットとの
差分を抽出 → LLM が「何が変わったか」を出典付きで要約 → Slack(#intel)へブリーフ配信。

個人パイプライン(genre 分類 classify/process_digest)には一切触れない**独立ジョブ**。
genre は "neither" 固定で WatchSource を流用し、Genre Literal 拡張の全体波及を避ける。

- 知覚: rss_generic(API有サイト) + web_browseruse(API無=Browser Use)
- 差分: change_detect(baseline スナップショット)
- 頭脳: llm_client.call_text(Gemini・無料枠)
- 出力: Slack webhook(SLACK_WEBHOOK_INTEL、無ければ SLACK_WEBHOOK_URL)。DRY_RUN で print のみ。

    DRY_RUN=true python -m src.jobs.org_intel --dry-run
    DRY_RUN=true python -m src.jobs.org_intel --dry-run --lookback-hours 72

設計: ~/Downloads/★6プログラム設計書.md §4。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from .. import logger, watchlist
from ..collectors import rss_generic, web_browseruse
from ..config import CONFIG_DIR, env, is_dry_run, settings
from ..llm_client import call_text
from ..models import RawItem, WatchSource
from ..processors import change_detect

log = logger.get(__name__)

_ORG_CSV = CONFIG_DIR / "watchlist_org.csv"


def _load_org_sources() -> list[WatchSource]:
    sources = watchlist._load_from_csv(_ORG_CSV)
    return [s for s in sources if s.enabled]


def _collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    items: list[RawItem] = []
    items.extend(rss_generic.collect(sources, since))
    items.extend(web_browseruse.collect(sources, since))
    return items


def _brief(items: list[RawItem]) -> str:
    listing = "\n".join(
        f"- [{it.author}] {it.text.strip()[:600]} ({it.url})" for it in items[:60]
    )
    model = str(settings().get("models", {}).get("digest", "gemini-2.5-flash"))
    system = (
        "あなたは事業会社の競合・業界インテリジェンス担当アナリストです。"
        "収集された最新アイテム群から『前回から何が変わったか・注目すべき動き』を抽出し、"
        "出典URLを必ず添えた Slack mrkdwn のブリーフを日本語で作成します。"
        "読み手は毎朝これだけ読めば業界の動きを把握できる想定なので、"
        "見出しの羅列で終わらせず、各トピックの中身・背景・意味合いまで書き切ってください。"
        "憶測は避け、収集アイテムに書かれている事実だけを根拠にし、固有名詞・数値は原文のまま保持してください。"
        "アイテムに書かれていない数値や推測は補わず、不明な点は触れないでください。"
    )
    user = (
        "次の新規アイテムから、競合動向・業界トレンド・採用市場の観点で重要な変化を5〜8点にまとめてください。\n"
        "構成:\n"
        "1. 冒頭に `*今日の要点*` の行を置き、その下に全体の流れを2〜3行で書く。\n"
        "2. 続けて各トピックを次の形式で書く。\n"
        "   `• *見出し*`\n"
        "   その下にインデントなしで3〜5行:\n"
        "     - 何が起きたか(主体・時期・規模を具体的に)\n"
        "     - 背景や前回からの変化(なぜ今これが起きたか)\n"
        "     - 業界・採用市場への意味合い\n"
        "   最終行の末尾に `<URL|出典>` を置く。複数ソースがあれば並べる。\n"
        "3. 末尾に `*来週の注視点*` として2〜3行、続報を追うべき論点を書く。\n"
        "分量の目安: 全体で1200〜2000字。1トピック150〜250字。\n"
        "禁止: 挨拶・前置き・『以上です』等の締め・情報の水増しのための一般論。\n\n"
        f"{listing}"
    )
    return call_text(model=model, system=system, user=user, max_tokens=8192, temperature=0.3).strip()


def _post_slack(text: str) -> None:
    url = env("SLACK_WEBHOOK_INTEL") or env("SLACK_WEBHOOK_URL")
    if not url:
        log.warning("SLACK_WEBHOOK_INTEL / SLACK_WEBHOOK_URL 未設定。投稿スキップ")
        return
    httpx.post(url, json={"text": text}, timeout=20.0).raise_for_status()


def _today_label() -> str:
    jst = ZoneInfo(str(settings().get("timezone", {}).get("name", "Asia/Tokyo")))
    return datetime.now(jst).date().isoformat()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="組織インテリジェンス・ブリーフ")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args(argv)

    sources = _load_org_sources()
    since = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)
    collected = _collect(sources, since)
    fresh = change_detect.detect_changes(collected)

    header = f"*🛰️ 組織インテリジェンス・ブリーフ*（{_today_label()}）"
    if not fresh:
        body = "前回から新しい変化は検知されませんでした。"
    else:
        try:
            body = _brief(fresh)
        except Exception as e:  # noqa: BLE001
            log.error(f"brief generation failed: {e}; fall back to raw list")
            body = "\n".join(
                f"• *{it.author}*\n{it.text.strip()[:400]} <{it.url}|出典>" for it in fresh[:10]
            )
    message = f"{header}\n\n{body}"

    if args.dry_run or is_dry_run():
        print(message)
        print(f"\n[debug] sources={len(sources)} collected={len(collected)} fresh={len(fresh)}")
        return

    _post_slack(message)
    change_detect.commit_baseline(collected)


if __name__ == "__main__":
    main()
