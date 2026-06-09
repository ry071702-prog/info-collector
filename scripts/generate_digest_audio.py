"""日次ダイジェストを Gemini TTS で約1分の音声 (WAV) に変換する。

新聞画像と同じく process_digest の後段で 1 日 1 回生成し、
site/public/audio/<date>.wav に保存 → publish_site でサイト配信される。
キャッチアップ便(メール/Slack/Discord)から「▶ 1分で聴く」で参照する。

使い方:
    GEMINI_API_KEY=xxx python scripts/generate_digest_audio.py [YYYY-MM-DD]

    DIGEST_AUDIO_MODEL で TTS モデルを上書き (既定 gemini-2.5-flash-preview-tts)
    DIGEST_AUDIO_VOICE で声を上書き (既定 Kore)
    DIGEST_AUDIO_FORCE=1 で既存があっても再生成
"""
from __future__ import annotations

import os
import re
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "docs" / "digests"
OUT_DIR = ROOT / "site" / "public" / "audio"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
MAX_HEADLINES = 5

_BULLET_RE = re.compile(r"^\s*[\*\-]\s*(?:⭐\s*)?(.+)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff"
    "←-⇿⌀-⏿⬀-⯿]"
)


def _clean(text: str) -> str:
    """TTS 用に絵文字・Markdown 記号を除去して読み上げ可能な文に。"""
    text = _LINK_RE.sub(r"\1", text)
    text = re.sub(r"[*_`#>]", "", text)
    text = _EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_date(arg: str | None) -> str:
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


def load_headlines(date: str, limit: int = MAX_HEADLINES) -> list[str]:
    headlines: list[str] = []
    for path in sorted(DIGEST_DIR.glob(f"{date}*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _BULLET_RE.match(line)
            if not m:
                continue
            raw = m.group(1)
            # 「**タイトル** 補足」形式なら太字タイトルを優先 (読み上げに最適)
            mb = _BOLD_RE.search(raw)
            text = _clean(mb.group(1) if mb else raw)
            if len(text) >= 8:
                headlines.append(text)
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


def _short(text: str, limit: int = 60) -> str:
    head = re.split(r"[。!?！？]", text)[0].strip()
    return head if len(head) <= limit else head[:limit]


def build_script(date: str, headlines: list[str]) -> str:
    """約1分の読み上げ原稿を作る。"""
    md, dd = date.split("-")[1:]
    intro = f"情報収集、{int(md)}月{int(dd)}日のダイジェストです。今日の注目はこちらです。"
    body = []
    for i, h in enumerate(headlines, 1):
        body.append(f"{i}つ目。{_short(h)}。")
    outro = "以上、本日の主要トピックをお届けしました。詳しくはサイトでご確認ください。"
    return intro + "".join(body) + outro


def _write_wav(path: Path, pcm: bytes, *, rate: int = 24000) -> None:
    """Gemini TTS は 24kHz/16bit/mono の PCM を返すので WAV ヘッダを付けて保存。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    date = resolve_date(arg)

    force = os.environ.get("DIGEST_AUDIO_FORCE", "").lower() in {"1", "true", "yes"}
    existing = next(iter(OUT_DIR.glob(f"{date}.*")), None)
    if existing and not force:
        print(f"既に存在するためスキップ: {existing.relative_to(ROOT)} (DIGEST_AUDIO_FORCE=1 で再生成)")
        raise SystemExit(0)

    headlines = load_headlines(date)
    if not headlines:
        print(f"見出しが無いため音声生成スキップ: {date}")
        raise SystemExit(0)
    script = build_script(date, headlines)
    model = os.environ.get("DIGEST_AUDIO_MODEL", DEFAULT_MODEL)
    voice = os.environ.get("DIGEST_AUDIO_VOICE", DEFAULT_VOICE)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY 未設定。原稿のプレビューのみ表示します。\n")
        print(f"--- {date} / model={model} / voice={voice} ---")
        print(script)
        raise SystemExit(0)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise SystemExit("google-genai が必要です: pip install google-genai")

    print(f"音声生成中… date={date} model={model} voice={voice} 見出し{len(headlines)}件")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=script,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )

    pcm = None
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            pcm = inline.data
            break
    if pcm is None:
        raise SystemExit("音声が返りませんでした。モデル/原稿を見直してください。")

    # 同日の古い拡張子を掃除して WAV を書き出す
    for old in OUT_DIR.glob(f"{date}.*"):
        old.unlink()
    out_path = OUT_DIR / f"{date}.wav"
    _write_wav(out_path, pcm)
    print(f"✓ 保存: {out_path.relative_to(ROOT)}")
    print(f"  サイト表示用パス: /audio/{date}.wav")


if __name__ == "__main__":
    main()
