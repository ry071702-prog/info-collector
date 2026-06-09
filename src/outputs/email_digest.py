"""日次キャッチアップをHTMLメールで送る出力モジュール (Gmail SMTP)。

新聞画像をヒーローに、重要記事をスタイル付きカードで並べた1通を
自分の Gmail へ送る。送信は App Password (GMAIL_APP_PASSWORD) を使う。
DRY_RUN 時 / App Password 未設定時は送信せず、プレビューHTMLをログ・ファイルに出す。
"""
from __future__ import annotations

import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from .. import logger
from ..config import cache_dir, env, is_dry_run
from ..models import ProcessedItem

log = logger.get(__name__)

DEFAULT_ADDRESS = "ry071702@gmail.com"
DEFAULT_SITE_URL = "https://info-collector-a5y.pages.dev"

# ジャンル別アクセント (メールクライアント向けに実色をベタ指定)
_GENRE = {
    "games": ("#0071e3", "ゲーム"),
    "anime": ("#bf5af2", "アニメ"),
    "disney": ("#d6a11f", "Disney"),
    "both": ("#0071e3", "ゲーム/アニメ"),
    "neither": ("#6e6e73", "その他"),
}
_BADGE = {"S": ("#ff3b30", "重要S"), "A": ("#ff9500", "重要A"), "B": ("#34c759", "B"), "C": ("#8e8e93", "C")}


def _site_url() -> str:
    return (env("SITE_URL", DEFAULT_SITE_URL) or DEFAULT_SITE_URL).rstrip("/")


def _card(item: ProcessedItem) -> str:
    accent, genre_label = _GENRE.get(item.genre, _GENRE["neither"])
    badge_color, badge_label = _BADGE.get(item.final_priority, _BADGE["C"])
    title = escape(item.category_name or "(無題)")
    summary = escape(item.summary or "")
    author = escape(item.author or "")
    spoiler = (
        '<span style="color:#ff3b30;font-weight:600">[ネタバレ]</span> '
        if item.flags.spoiler != "なし"
        else ""
    )
    return f"""
      <tr><td style="padding:0 0 14px 0">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e3e3e8;border-radius:16px;border-left:5px solid {accent};
                      background:#ffffff;overflow:hidden">
          <tr><td style="padding:16px 18px">
            <div style="font-size:11px;font-weight:700;letter-spacing:.04em;color:{accent};text-transform:uppercase">
              {genre_label}
              <span style="display:inline-block;margin-left:6px;padding:1px 8px;border-radius:999px;
                           background:{badge_color};color:#fff;font-size:10px;vertical-align:middle">{badge_label}</span>
            </div>
            <a href="{escape(item.url)}" style="text-decoration:none">
              <div style="margin:6px 0 4px 0;font-size:17px;line-height:1.4;font-weight:700;color:#1d1d1f">
                {spoiler}{title}
              </div>
            </a>
            <div style="font-size:14px;line-height:1.7;color:#3a3a3c">{summary}</div>
            <div style="margin-top:8px;font-size:12px;color:#86868b">
              {author} ·
              <a href="{escape(item.url)}" style="color:{accent};text-decoration:none;font-weight:600">元記事を開く ›</a>
            </div>
          </td></tr>
        </table>
      </td></tr>"""


def build_html(
    items: list[ProcessedItem],
    *,
    slot_label: str,
    date_label: str,
    hero_image_url: str | None = None,
    newspaper_url: str | None = None,
    audio_url: str | None = None,
) -> str:
    site = _site_url()
    cards = "".join(_card(it) for it in items)
    audio_btn = ""
    if audio_url:
        audio_btn = f"""
        <tr><td style="padding:0 0 10px 0" align="center">
          <a href="{escape(audio_url)}" style="display:inline-block;background:#1d1d1f;color:#fff;text-decoration:none;
                    font-size:14px;font-weight:700;padding:11px 24px;border-radius:999px">▶ 1分で聴く</a>
        </td></tr>"""
    hero = ""
    if hero_image_url:
        inner = f"""
          <img src="{escape(hero_image_url)}" alt="本日の新聞" width="100%"
               style="display:block;width:100%;border-radius:16px;border:1px solid #e3e3e8" />"""
        hero = f"""
      <tr><td style="padding:0 0 18px 0">
        <a href="{escape(newspaper_url or site)}" style="text-decoration:none">{inner}</a>
      </td></tr>"""
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f7">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f7">
    <tr><td align="center" style="padding:24px 12px">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','Noto Sans JP',sans-serif">
        <tr><td style="padding:0 0 18px 0">
          <div style="font-size:13px;font-weight:700;color:#0071e3;letter-spacing:.04em">情報収集 · キャッチアップ便</div>
          <div style="font-size:24px;font-weight:800;color:#1d1d1f;letter-spacing:-.01em;margin-top:2px">{escape(slot_label)}</div>
          <div style="font-size:13px;color:#86868b;margin-top:2px">{escape(date_label)} · 重要 {len(items)} 件</div>
        </td></tr>
        {hero}
        {cards}
        {audio_btn}
        <tr><td style="padding:8px 0 6px 0" align="center">
          <a href="{site}/feed/" style="display:inline-block;background:#0071e3;color:#fff;text-decoration:none;
                    font-size:15px;font-weight:700;padding:13px 28px;border-radius:999px">サイトで全部見る</a>
        </td></tr>
        <tr><td style="padding:14px 0 0 0" align="center">
          <div style="font-size:11px;color:#a1a1a6;line-height:1.6">
            AIが収集・要約・重要度づけした自動ダイジェストです<br>
            ソース: X / YouTube / Twitch / RSS
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _text_fallback(items: list[ProcessedItem], slot_label: str) -> str:
    lines = [f"情報収集 キャッチアップ便 — {slot_label}", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it.final_priority}] {it.category_name}")
        if it.summary:
            lines.append(f"   {it.summary}")
        lines.append(f"   {it.url}")
        lines.append("")
    lines.append(f"全件: {_site_url()}/feed/")
    return "\n".join(lines)


def send_digest(
    items: list[ProcessedItem],
    *,
    slot_label: str,
    date_label: str,
    hero_image_url: str | None = None,
    newspaper_url: str | None = None,
    audio_url: str | None = None,
) -> bool:
    """HTMLメールを1通送る。送信したら True。DRY_RUN/未設定なら False。"""
    html = build_html(
        items,
        slot_label=slot_label,
        date_label=date_label,
        hero_image_url=hero_image_url,
        newspaper_url=newspaper_url,
        audio_url=audio_url,
    )
    subject = f"☀ {slot_label} — 重要{len(items)}件 ({date_label})"

    addr = env("GMAIL_ADDRESS", DEFAULT_ADDRESS) or DEFAULT_ADDRESS
    recipient = env("MAIL_TO", addr) or addr
    password = env("GMAIL_APP_PASSWORD")

    if is_dry_run() or not password:
        reason = "DRY_RUN" if is_dry_run() else "GMAIL_APP_PASSWORD未設定"
        preview = cache_dir() / "catchup_preview.html"
        preview.write_text(html, encoding="utf-8")
        log.info(f"[{reason}] メール送信スキップ。プレビュー: {preview} / 件名: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"情報収集 <{addr}>"
    msg["To"] = recipient
    msg.attach(MIMEText(_text_fallback(items, slot_label), "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as smtp:
            smtp.login(addr, password)
            smtp.sendmail(addr, [recipient], msg.as_string())
    except Exception as e:  # noqa: BLE001
        log.error(f"メール送信失敗: {e}")
        return False
    log.info(f"メール送信: {recipient} / {subject}")
    return True
