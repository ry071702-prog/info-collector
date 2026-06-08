"""日次ダイジェストから新聞風 1 枚画像を生成する。

Gemini 画像モデルには文字を描かせず、文字は Pillow + 実フォントで合成する。

使い方:
    GEMINI_API_KEY=xxxx python scripts/generate_newspaper_image.py [YYYY-MM-DD]

    日付を省略すると、data/processed/ にある記事 timestamp の最新 UTC 日付を使う。
    processed を読めない場合のみ docs/digests/ の最新日付へフォールバックする。
    モデルは環境変数 NEWSPAPER_IMAGE_MODEL で上書き可
    (既定: gemini-3-pro-image-preview / 安価に試すなら gemini-2.5-flash-image)。
    フォントは NEWSPAPER_FONT=/path/to/font で明示指定可。

出力:
    site/public/newspaper-img/<date>.png
    API キー未設定時は site/public/newspaper-img/<date>.preview.png
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "docs" / "digests"
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "site" / "public" / "newspaper-img"
DEFAULT_MODEL = "gemini-3-pro-image-preview"
CANVAS_SIZE = (1600, 900)

# digest 1 行から「先頭の絵文字・記号」を落として本文だけ取り出す
_BULLET_RE = re.compile(r"^\s*[\*\-]\s*(?:⭐\s*)?(.+)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_UNSUPPORTED_SYMBOL_RE = re.compile(
    "["
    "\u200d"  # zero width joiner
    "\u20e3"  # combining enclosing keycap
    "\u2190-\u21ff"  # arrows
    "\u2300-\u23ff"  # miscellaneous technical symbols
    "\u25a0-\u25ff"  # geometric shapes
    "\u2600-\u27bf"  # miscellaneous symbols and dingbats
    "\u2b00-\u2bff"  # miscellaneous symbols and arrows
    "\ufe00-\ufe0f"  # variation selectors
    "\U0001f000-\U0001faff"  # emoji and pictographs
    "\U000e0100-\U000e01ef"  # variation selectors supplement
    "]"
)


@dataclass(frozen=True)
class NewspaperContent:
    headline_title: str
    headline_summary: str
    lead_titles: list[str]


@dataclass(frozen=True)
class FontSet:
    regular_path: Path
    bold_path: Path


def resolve_date(arg: str | None) -> str:
    """対象日付を決める。引数なしなら記事 timestamp の最新 UTC 日付。"""
    if arg:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
            raise SystemExit(f"日付は YYYY-MM-DD 形式で: {arg!r}")
        return arg

    article_dates = [date for item in load_processed_items() if (date := article_date(item))]
    if article_dates:
        return max(article_dates)

    # processed が無い・読めない場合のみ digest 実行日にフォールバックする。
    dates = sorted(
        {
            m.group(1)
            for p in DIGEST_DIR.glob("*.md")
            if (m := re.match(r"(\d{4}-\d{2}-\d{2})", p.name))
        },
        reverse=True,
    )
    if not dates:
        raise SystemExit(f"digest が見つかりません: {DIGEST_DIR}")
    return dates[0]


def article_date(item: dict[str, object]) -> str:
    """Astro の timestamp.slice(0, 10) と同じ規則で UTC 日付を返す。"""
    timestamp = item.get("timestamp")
    return timestamp[:10] if isinstance(timestamp, str) else ""


def load_processed_items(date: str | None = None) -> list[dict[str, object]]:
    """processed 配下の JSONL を読み、必要なら UTC 記事日で絞り込む。"""
    items: list[dict[str, object]] = []
    try:
        paths = sorted(PROCESSED_DIR.glob("**/items.jsonl"))
    except OSError:
        return items

    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(item, dict):
                continue
            if date is None or article_date(item) == date:
                items.append(item)
    return items


def load_headlines(date: str, limit: int = 6) -> list[str]:
    """同日の digest、無ければ processed 記事から見出しを集める。"""
    headlines: list[str] = []
    digest_paths = sorted(DIGEST_DIR.glob(f"{date}*.md"))
    for path in digest_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _BULLET_RE.match(line)
            if not m:
                continue
            text = clean_text(_LINK_RE.sub(r"\1", m.group(1)))
            # リンクや記号だけの行・短すぎる行は除外
            if len(text) >= 10:
                headlines.append(text)

    if not digest_paths:
        priority_rank = {"S": 0, "A": 1, "B": 2, "C": 3}
        items = sorted(
            load_processed_items(date),
            key=lambda item: str(item.get("timestamp", "")),
            reverse=True,
        )
        items.sort(
            key=lambda item: priority_rank.get(str(item.get("final_priority", "")), 9)
        )
        for item in items:
            title = clean_text(str(item.get("category_name") or ""))
            summary = clean_text(str(item.get("summary") or ""))
            text = "。".join(part for part in (title, summary) if part)
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


def clean_text(text: str) -> str:
    """日本語フォントで tofu になりやすい絵文字・装飾記号と制御文字を除く。"""
    text = _UNSUPPORTED_SYMBOL_RE.sub("", unicodedata.normalize("NFC", text))
    text = "".join(
        char
        for char in text
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
    )
    return re.sub(r"\s+", " ", text).strip()


def _short(text: str, limit: int = 26) -> str:
    """画像の見出し用に短縮: 最初の句点まで、なお長ければ切り詰める。"""
    head = re.split(r"[。!?！？]", clean_text(text))[0].strip()
    return head if len(head) <= limit else head[:limit] + "…"


def build_content(headlines: list[str]) -> NewspaperContent:
    if not headlines:
        return NewspaperContent(
            headline_title=clean_text("本日の主要記事データなし"),
            headline_summary=clean_text("ダイジェストから掲載できる主要記事が見つかりませんでした。"),
            lead_titles=[],
        )
    return NewspaperContent(
        headline_title=clean_text(_short(headlines[0], 24)),
        headline_summary=clean_text(headlines[0][:130]),
        lead_titles=[_short(text, 30) for text in headlines[1:4]],
    )


def build_prompt(date: str, headlines: list[str]) -> str:
    """文字なし新聞背景を生成するプロンプト。実テキストは Pillow で後から描く。"""
    _ = date, headlines
    return """横長16:9の上品な日本の新聞風ビジュアル背景を生成してください。

最重要: 文字・テキスト・題字・ロゴ・数字・記号・読める文字を一切描かない。絶対に文字を入れない。

【構図】
- 上部は大見出しを後から合成するため、淡く明るい余白を大きく取る。
- 左側にニュースを象徴する品のある挿絵。ゲーム、アニメ、エンタメ、配信、テクノロジーを連想する抽象的なビジュアル。
- 右端に縦帯の題字スペースを作る。ただし無地で、文字や数字は入れない。
- 下部に3つの小見出しを後から合成できる余白を作る。
- 全体は淡い和紙テクスチャ、生成物は落ち着いた新聞紙面調。
- 罫線、淡い幾何学模様、余白の区切り線は可。ただし文字に見えるものは禁止。

【禁止】
- 日本語、英語、数字、疑似文字、看板、新聞名、題字、キャプション、ロゴ、透かしを描かない。
- 読めない崩れた文字も描かない。
- 文字スペースには何も描かず、淡い無地のままにする。
"""


def existing_final_output(date: str) -> Path | None:
    for ext in ("png", "jpg", "jpeg"):
        path = OUT_DIR / f"{date}.{ext}"
        if path.exists():
            return path
    return None


def existing_preview_output(date: str) -> Path | None:
    path = OUT_DIR / f"{date}.preview.png"
    if path.exists():
        return path
    return None


def font_candidates() -> tuple[list[Path], list[Path]]:
    env_font = os.environ.get("NEWSPAPER_FONT")
    if env_font:
        path = Path(env_font).expanduser()
        return [path], [path]

    regular = [
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Regular.otf"),
        Path("/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf"),
        Path("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    ]
    bold = [
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Bold.otf"),
        Path("/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf"),
        Path("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        Path("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    ]
    return regular, bold


def resolve_fonts() -> FontSet:
    regular_candidates, bold_candidates = font_candidates()
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), None)
    if not regular or not bold:
        checked = "\n".join(str(path) for path in [*regular_candidates, *bold_candidates])
        raise SystemExit(
            "日本語フォントが見つかりません。NEWSPAPER_FONT=/path/to/font を指定するか、"
            "CI では fonts-noto-cjk をインストールしてください。\n"
            f"探索候補:\n{checked}"
        )
    return FontSet(regular_path=regular, bold_path=bold)


def load_font(path: Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size=size)


def make_blank_background() -> "Image.Image":
    from PIL import Image, ImageDraw

    image = Image.new("RGB", CANVAS_SIZE, "#f5efdf")
    overlay = Image.new("RGBA", CANVAS_SIZE, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    for x in range(0, CANVAS_SIZE[0], 28):
        alpha = 13 if (x // 28) % 2 == 0 else 8
        draw.line([(x, 0), (x - 220, CANVAS_SIZE[1])], fill=(128, 112, 84, alpha), width=1)
    for y in range(0, CANVAS_SIZE[1], 36):
        draw.line([(0, y), (CANVAS_SIZE[0], y + 18)], fill=(255, 255, 255, 18), width=1)
    draw.ellipse((90, 170, 610, 690), fill=(88, 130, 160, 26))
    draw.ellipse((240, 250, 760, 760), fill=(172, 125, 95, 20))
    draw.rectangle((1360, 0, 1600, 900), fill=(238, 231, 212, 150))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def image_from_bytes(image_bytes: bytes) -> "Image.Image":
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.convert("RGB")


def fit_cover(image: "Image.Image", size: tuple[int, int]) -> "Image.Image":
    src_w, src_h = image.size
    dst_w, dst_h = size
    scale = max(dst_w / src_w, dst_h / src_h)
    resized = image.resize((round(src_w * scale), round(src_h * scale)))
    left = (resized.width - dst_w) // 2
    top = (resized.height - dst_h) // 2
    return resized.crop((left, top, left + dst_w, top + dst_h))


def wrap_japanese(text: str, chars_per_line: int, max_lines: int) -> list[str]:
    """日本語向けの文字数ベース折り返し。空白に依存しない。"""
    cleaned = clean_text(text)
    if not cleaned:
        return []
    lines = [cleaned[index : index + chars_per_line] for index in range(0, len(cleaned), chars_per_line)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("、。，．") + "…"
    return lines


def text_size(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.FreeTypeFont",
) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text or "国", font=font, anchor="lt")
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def truncate_to_width(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.FreeTypeFont",
    max_width: int,
    *,
    add_ellipsis: bool,
    force_ellipsis: bool = False,
) -> str:
    """1行を実測幅に収め、必要なら末尾を省略する。"""
    text = clean_text(text).strip()
    if not text:
        return ""
    if text_size(draw, text, font)[0] <= max_width and not force_ellipsis:
        return text

    suffix = "…" if add_ellipsis else ""
    if text_size(draw, text + suffix, font)[0] <= max_width:
        return text + suffix

    while text and text_size(draw, text.rstrip() + suffix, font)[0] > max_width:
        text = text[:-1]
    return text.rstrip(" 、。，．") + suffix if text else suffix


def fit_text_lines(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.FreeTypeFont",
    *,
    max_width: int,
    max_height: int,
    max_lines: int,
    line_gap: int,
) -> tuple[list[str], int]:
    """実測した幅・行高で折り返し、描画領域を超える内容を省略する。"""
    cleaned = clean_text(text)
    if not cleaned or max_width <= 0 or max_height <= 0:
        return [], 0

    _sample_width, line_height = text_size(draw, "国Ag", font)
    height_limited_lines = max(1, (max_height + line_gap) // (line_height + line_gap))
    allowed_lines = max(1, min(max_lines, height_limited_lines))

    lines: list[str] = []
    current = ""
    for char in cleaned:
        candidate = current + char
        if not current or text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
            continue
        lines.append(current.rstrip())
        current = char.lstrip()
    if current:
        lines.append(current.rstrip())

    truncated = len(lines) > allowed_lines
    visible = lines[:allowed_lines]
    if truncated and visible:
        visible[-1] = truncate_to_width(
            draw,
            visible[-1],
            font,
            max_width,
            add_ellipsis=True,
            force_ellipsis=True,
        )
    else:
        visible = [
            truncate_to_width(draw, line, font, max_width, add_ellipsis=False)
            for line in visible
        ]
    return visible, line_height


def draw_panel(draw: "ImageDraw.ImageDraw", box: tuple[int, int, int, int], alpha: int = 212) -> None:
    draw.rounded_rectangle(box, radius=20, fill=(255, 255, 250, alpha), outline=(48, 42, 34, 44), width=2)


def draw_vertical_text(
    draw: "ImageDraw.ImageDraw",
    text: str,
    x: int,
    y: int,
    font: "ImageFont.FreeTypeFont",
    fill: tuple[int, int, int, int],
    spacing: int = 4,
) -> int:
    cursor = y
    for char in text:
        if char == "\n":
            x -= int(font.size * 1.18)
            cursor = y
            continue
        bbox = draw.textbbox((0, 0), char, font=font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        draw.text((x - width // 2, cursor), char, font=font, fill=fill)
        cursor += height + spacing
    return cursor


def compose_newspaper_image(background: "Image.Image", date: str, content: NewspaperContent, fonts: FontSet) -> "Image.Image":
    from PIL import Image, ImageDraw

    canvas = fit_cover(background, CANVAS_SIZE).convert("RGBA")
    veil = Image.new("RGBA", CANVAS_SIZE, (255, 250, 238, 28))
    canvas = Image.alpha_composite(canvas, veil)
    draw = ImageDraw.Draw(canvas)

    regular_34 = load_font(fonts.regular_path, 34)
    bold_30 = load_font(fonts.bold_path, 30)
    bold_68 = load_font(fonts.bold_path, 68)
    bold_78 = load_font(fonts.bold_path, 78)

    sumi = (26, 26, 26, 255)
    muted = (58, 52, 45, 230)
    rule = (26, 26, 26, 92)

    # 右端の縦帯
    draw_panel(draw, (1370, 34, 1558, 866), alpha=226)
    draw.line([(1362, 34), (1362, 866)], fill=rule, width=2)
    draw_vertical_text(draw, "週刊\n情報収集", 1498, 78, bold_78, sumi, spacing=6)
    draw_vertical_text(draw, date.replace("-", "."), 1412, 610, bold_30, muted, spacing=2)

    # 上部バナー
    draw_panel(draw, (58, 52, 1320, 332), alpha=224)
    headline = truncate_to_width(
        draw,
        content.headline_title,
        bold_68,
        max_width=1180,
        add_ellipsis=True,
    )
    draw.text((88, 78), headline, font=bold_68, fill=sumi, anchor="lt")
    draw.line([(88, 165), (1288, 165)], fill=rule, width=2)
    summary_lines, summary_line_height = fit_text_lines(
        draw,
        content.headline_summary,
        regular_34,
        max_width=1180,
        max_height=118,
        max_lines=3,
        line_gap=8,
    )
    y = 188
    for line in summary_lines:
        draw.text((92, y), line, font=regular_34, fill=muted, anchor="lt")
        y += summary_line_height + 8

    # 中央の控えめな罫線
    for y_line in (380, 598):
        draw.line([(72, y_line), (1328, y_line)], fill=(26, 26, 26, 46), width=2)
    for x_line in (472, 878, 1284):
        draw.line([(x_line, 625), (x_line, 840)], fill=(26, 26, 26, 50), width=2)

    # 下部3記事
    lead_boxes = [(70, 632, 450, 834), (486, 632, 866, 834), (902, 632, 1282, 834)]
    for index, box in enumerate(lead_boxes):
        title = clean_text(
            content.lead_titles[index] if index < len(content.lead_titles) else "続報を待つトピック"
        )
        draw_panel(draw, box, alpha=214)
        x1, y1, x2, y2 = box
        draw.text((x1 + 20, y1 + 18), f"記事 {index + 1}", font=bold_30, fill=(72, 64, 54, 235))
        draw.line([(x1 + 20, y1 + 58), (x2 - 20, y1 + 58)], fill=rule, width=1)
        text_left = x1 + 20
        text_top = y1 + 72
        text_right = x2 - 20
        text_bottom = y2 - 16
        lead_lines, lead_line_height = fit_text_lines(
            draw,
            title,
            regular_34,
            max_width=text_right - text_left,
            max_height=text_bottom - text_top,
            max_lines=3,
            line_gap=4,
        )
        y_text = text_top
        for line in lead_lines:
            draw.text((text_left, y_text), line, font=regular_34, fill=sumi, anchor="lt")
            y_text += lead_line_height + 4

    # 左側の視覚領域を紙面らしく締める
    draw.rectangle((58, 52, 1558, 866), outline=(26, 26, 26, 68), width=3)
    draw.rectangle((74, 68, 1542, 850), outline=(255, 255, 255, 92), width=2)

    return canvas.convert("RGB")


def normalize_inline_image_data(data: object) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return base64.b64decode(data)
    raise TypeError("unsupported inline image data")


def generate_background_with_gemini(api_key: str, model: str, prompt: str) -> bytes:
    try:
        from google import genai  # google-genai (新 SDK)
    except ImportError:
        raise SystemExit("google-genai が必要です: pip install google-genai")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)

    image_bytes = None
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            image_bytes = normalize_inline_image_data(inline.data)
            break
    if image_bytes is None:
        raise SystemExit("画像が返りませんでした。モデル/プロンプトを見直してください。")
    return image_bytes


def save_final_image(image: "Image.Image", date: str, preview: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob(f"{date}.*"):
        old.unlink()
    suffix = "preview.png" if preview else "png"
    out_path = OUT_DIR / f"{date}.{suffix}"
    image.save(out_path, format="PNG", optimize=True)
    return out_path


def main() -> None:
    # .env から GEMINI_API_KEY 等を読み込む (中身は表示しない)
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    date = resolve_date(arg)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    # 当日分が既にあれば再生成しない (NEWSPAPER_FORCE=1 で上書き)。
    # process_digest は 1 日 2 回走るため、これで「1 日 1 枚」=コスト 1 回/日 に抑える。
    force = os.environ.get("NEWSPAPER_FORCE", "").lower() in {"1", "true", "yes"}
    existing = existing_final_output(date)
    if existing and not force:
        print(f"既に存在するためスキップ: {existing.relative_to(ROOT)} (NEWSPAPER_FORCE=1 で再生成)")
        raise SystemExit(0)

    if not api_key:
        existing_preview = existing_preview_output(date)
        if existing_preview and not force:
            print(f"既に preview が存在するためスキップ: {existing_preview.relative_to(ROOT)} (NEWSPAPER_FORCE=1 で再生成)")
            raise SystemExit(0)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow が必要です: pip install Pillow")

    headlines = load_headlines(date)
    content = build_content(headlines)
    prompt = build_prompt(date, headlines)
    model = os.environ.get("NEWSPAPER_IMAGE_MODEL", DEFAULT_MODEL)
    fonts = resolve_fonts()

    if not api_key:
        print(f"GEMINI_API_KEY が未設定です。無地背景で preview を生成します。date={date}")
        background = make_blank_background()
        preview = True
    else:
        print(f"背景生成中… date={date} model={model} 見出し{len(headlines)}件")
        print("Gemini には文字なし背景のみを生成させ、文字は Pillow で合成します。")
        image_bytes = generate_background_with_gemini(api_key, model, prompt)
        background = image_from_bytes(image_bytes)
        preview = False

    final_image = compose_newspaper_image(background, date, content, fonts)
    out_path = save_final_image(final_image, date, preview=preview)
    print(f"✓ 保存: {out_path.relative_to(ROOT)}")
    if preview:
        print("  API キー無しのレイアウト検証用 preview です。サイト埋め込み対象ではありません。")
    else:
        print(f"  サイト表示用パス: /newspaper-img/{date}.png")
    print(f"  regular font: {fonts.regular_path}")
    print(f"  bold font: {fonts.bold_path}")


if __name__ == "__main__":
    main()
