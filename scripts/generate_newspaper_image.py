"""日次ダイジェストを Gemini (Nano Banana Pro) で新聞風 1 枚画像に変換するプロトタイプ。

検討段階のプロト: まず 1 日分を生成して品質 (特に日本語テキストの正確さ) を見る。
本実装に昇格する場合は publish_site の前段 (GitHub Actions) に組み込む想定。

使い方:
    GEMINI_API_KEY=xxxx python scripts/generate_newspaper_image.py [YYYY-MM-DD]

    日付を省略すると、docs/digests/ にある最新日付を使う。
    モデルは環境変数 NEWSPAPER_IMAGE_MODEL で上書き可
    (既定: gemini-3-pro-image-preview / 安価に試すなら gemini-2.5-flash-image)。

出力:
    site/public/newspaper-img/<date>.png
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "docs" / "digests"
OUT_DIR = ROOT / "site" / "public" / "newspaper-img"
DEFAULT_MODEL = "gemini-3-pro-image-preview"

# digest 1 行から「先頭の絵文字・記号」を落として本文だけ取り出す
_BULLET_RE = re.compile(r"^\s*[\*\-]\s*(?:⭐\s*)?(.+)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def resolve_date(arg: str | None) -> str:
    """対象日付 (YYYY-MM-DD) を決める。引数なしなら最新の digest 日付。"""
    if arg:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
            raise SystemExit(f"日付は YYYY-MM-DD 形式で: {arg!r}")
        return arg
    dates = sorted(
        {m.group(1) for p in DIGEST_DIR.glob("*.md")
         if (m := re.match(r"(\d{4}-\d{2}-\d{2})", p.name))},
        reverse=True,
    )
    if not dates:
        raise SystemExit(f"digest が見つかりません: {DIGEST_DIR}")
    return dates[0]


def load_headlines(date: str, limit: int = 6) -> list[str]:
    """その日の digest (AM/PM 両方) から箇条書きの見出しを集める。"""
    headlines: list[str] = []
    for path in sorted(DIGEST_DIR.glob(f"{date}*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _BULLET_RE.match(line)
            if not m:
                continue
            text = _LINK_RE.sub(r"\1", m.group(1)).strip()
            # リンクや記号だけの行・短すぎる行は除外
            if len(text) >= 10:
                headlines.append(text)
    # 重複を避けつつ上位 limit 件
    seen: set[str] = set()
    uniq: list[str] = []
    for h in headlines:
        key = h[:30]
        if key not in seen:
            seen.add(key)
            uniq.append(h)
        if len(uniq) >= limit:
            break
    return uniq


def _short(text: str, limit: int = 26) -> str:
    """画像の見出し用に短縮: 最初の句点まで、なお長ければ切り詰める。"""
    head = re.split(r"[。!?！？]", text)[0].strip()
    return head if len(head) <= limit else head[:limit] + "…"


def build_prompt(date: str, headlines: list[str]) -> str:
    """新聞・号外風レイアウトの生成プロンプト。見出しは正確な日本語テキストで指示する。"""
    if not headlines:
        body = "(本日の主要記事データなし)"
    else:
        top = headlines[0]
        rest = headlines[1:]
        lines = [
            f"トップ記事の大見出し(短く・正確に): 「{_short(top, 24)}」",
            f"トップ記事のリード文: 「{top[:90]}」",
        ]
        for i, h in enumerate(rest, start=1):
            lines.append(f"記事{i}の見出し: 「{_short(h)}」")
        body = "\n".join(lines)

    return f"""日本の新聞・号外風の 1 枚レイアウト画像を作成してください。

【全体スタイル】
- 横長 (16:9)、明朝体、白背景にスミ文字の上品な紙面。
- 右端に縦書きの大きな題字「週刊 情報収集」。その下に「{date}」。
- 紙面上部に灰色帯の大見出しバナー。
- 左側にニュースを象徴するメインビジュアル(ゲーム/アニメ/エンタメ系)。
- 中央〜下部に本文と 3 段組の記事。罫線で区切る。

【掲載する実際のニュース(日本語テキストを正確に・誤字なく描画すること)】
{body}

【重要】
- 見出しの日本語は上記の文言を改変せず正確に表示する。
- 読みやすさ最優先。装飾より可読性。実在の新聞のような端正なレイアウト。
"""


def main() -> None:
    # .env から GEMINI_API_KEY 等を読み込む (中身は表示しない)
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    date = resolve_date(arg)

    # 当日分が既にあれば再生成しない (NEWSPAPER_FORCE=1 で上書き)。
    # process_digest は 1 日 2 回走るため、これで「1 日 1 枚」=コスト 1 回/日 に抑える。
    force = os.environ.get("NEWSPAPER_FORCE", "").lower() in {"1", "true", "yes"}
    existing = next(iter(OUT_DIR.glob(f"{date}.*")), None)
    if existing and not force:
        print(f"既に存在するためスキップ: {existing.relative_to(ROOT)} (NEWSPAPER_FORCE=1 で再生成)")
        raise SystemExit(0)

    headlines = load_headlines(date)
    prompt = build_prompt(date, headlines)
    model = os.environ.get("NEWSPAPER_IMAGE_MODEL", DEFAULT_MODEL)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY が未設定です。プロンプトのプレビューのみ表示します。\n")
        print(f"--- {date} / model={model} ---")
        print(prompt)
        raise SystemExit(0)

    try:
        from google import genai  # google-genai (新 SDK)
    except ImportError:
        raise SystemExit(
            "google-genai が必要です:  pip install google-genai\n"
            "(情報収集の既存依存は google-generativeai 旧 SDK のため、プロトは別途インストール)"
        )

    print(f"生成中… date={date} model={model} 見出し{len(headlines)}件")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)

    image_bytes = None
    mime = "image/png"
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            image_bytes = inline.data
            mime = getattr(inline, "mime_type", "") or "image/png"
            break
    if image_bytes is None:
        raise SystemExit("画像が返りませんでした。モデル/プロンプトを見直してください。")

    # 中身の MIME に合わせて拡張子を決める (Nano Banana は JPEG を返すことがある)
    ext = "jpg" if ("jpeg" in mime or "jpg" in mime) else "png"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 同じ日付の古い拡張子ファイルが残らないよう掃除
    for old in OUT_DIR.glob(f"{date}.*"):
        old.unlink()
    out_path = OUT_DIR / f"{date}.{ext}"
    out_path.write_bytes(image_bytes)
    print(f"✓ 保存: {out_path.relative_to(ROOT)}")
    print(f"  サイト表示用パス: /newspaper-img/{date}.{ext}")


if __name__ == "__main__":
    main()
