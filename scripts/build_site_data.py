"""Build static news-site data from processed JSONL files."""
from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from selectolax.parser import HTMLParser


ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DIGESTS_DIR = ROOT_DIR / "docs" / "digests"
SITE_DATA_DIR = ROOT_DIR / "site" / "src" / "data"
SITE_PUBLIC_DIR = ROOT_DIR / "site" / "public"
OG_CACHE_DIR = ROOT_DIR / "site" / "public" / "og-cache"
OUTPUT_PATH = SITE_DATA_DIR / "articles.json"
PUBLIC_OUTPUT_PATH = SITE_PUBLIC_DIR / "articles.json"
WATCHLIST_PATH = ROOT_DIR / "config" / "watchlist.csv"

ALLOWED_GENRES = {"games", "anime", "disney"}
PRIORITY_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}

# 旧 pin バグの遺残対策: games 表示中で明らかにゲーム関連ワードを含まず
# かつ非ゲーム領域のキーワードを含むものを表示から除外するヒューリスティック。
# data/processed は archive として保持しつつ、site 表示のみで救う。
_NON_GAMES_PATTERNS = re.compile(
    r"(?:"
    r"暗号資産|仮想通貨|ETF|IPO|決算|株式|株主|金融機関|金融商品|"
    r"OpenAI|ChatGPT|Anthropic|生成AI|"
    r"大学|専門学校|教育機関|学習管理システム|"
    r"飲料|食品メーカー|値上げ|低価格戦略|"
    r"ハッカー集団|セキュリティ事案|個人情報流出|"
    r"選挙|国会|議員|政治家|"
    r"気象|天気予報|地震|台風|"
    r"iPhone|iOS|Android|macOS|"
    r"Threads|Instagram|TikTok"
    r")",
    re.IGNORECASE,
)
_GAMES_PATTERNS = re.compile(
    r"(?:"
    r"ゲーム|プレイ|配信|esports|eスポーツ|Steam|Switch|PS5|Xbox|PlayStation|"
    r"VTuber|ストリーマー|大会|発売|アップデート|DLC|アップデ|"
    r"VALORANT|Apex|League of Legends|LoL|FF|ドラクエ|ポケモン|マイクラ|Minecraft|"
    r"ガチャ|ソシャゲ|実況|攻略|RPG|FPS|MOBA|タイトル|キャラクター"
    r")",
    re.IGNORECASE,
)


def _is_off_topic(genre: str, summary: str, title_tags) -> bool:
    """旧 pin バグで games に流れ込んだ非ゲーム記事を除外。

    games genre のみに適用。
    非ゲームキーワードを含み、かつゲーム関連語を一切含まない場合に True。
    """
    if genre != "games":
        return False
    text_parts = [summary or ""]
    if isinstance(title_tags, list):
        text_parts.extend(str(t) for t in title_tags)
    text = " ".join(text_parts)
    if _NON_GAMES_PATTERNS.search(text) and not _GAMES_PATTERNS.search(text):
        return True
    return False
RECENT_DAYS = 30
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_IMAGE_BYTES = 4 * 1024 * 1024
UTC = timezone.utc
USER_AGENT = (
    "Mozilla/5.0 (compatible; info-collector-site/1.0; "
    "+https://github.com/)"
)


def load_source_platforms() -> dict[str, str]:
    """Load source_id -> platform mapping from the local watchlist cache."""
    if not WATCHLIST_PATH.exists():
        return {}

    try:
        with WATCHLIST_PATH.open("r", encoding="utf-8", newline="") as file:
            return {
                str(row.get("id") or "").strip(): str(row.get("platform") or "").strip()
                for row in csv.DictReader(file)
                if str(row.get("id") or "").strip()
            }
    except Exception as exc:  # noqa: BLE001 - site generation should keep going
        logger.warning("Failed to load watchlist platforms: {}", exc)
        return {}


def parse_date_from_processed_path(path: Path) -> Optional[date]:
    """Return YYYY-MM-DD date from nested or legacy processed JSONL paths."""
    for value in (path.parent.name, path.stem):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            continue
    logger.warning("Skipping processed file with unexpected name: {}", path)
    return None


def processed_files(days: int = RECENT_DAYS) -> list[Path]:
    """List processed JSONL files from the last N days."""
    if not PROCESSED_DIR.exists():
        logger.info("Processed directory does not exist: {}", PROCESSED_DIR)
        return []

    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=days - 1)
    files: list[Path] = []
    paths = list(PROCESSED_DIR.glob("*/items.jsonl")) + list(PROCESSED_DIR.glob("*.jsonl"))
    for path in sorted(paths):
        file_date = parse_date_from_processed_path(path)
        if file_date is not None and start_date <= file_date <= today:
            files.append(path)
    return files


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO8601 timestamp with graceful fallback."""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        logger.warning("Invalid timestamp encountered: {}", value)
        return datetime.fromtimestamp(0, UTC)


def sort_key(article: dict[str, Any]) -> tuple[int, float]:
    """Sort by final_priority, then timestamp descending."""
    priority = PRIORITY_ORDER.get(str(article.get("final_priority", "C")), 3)
    timestamp = parse_timestamp(str(article.get("timestamp", ""))).timestamp()
    return (priority, -timestamp)


def timestamp_sort_key(article: dict[str, Any]) -> float:
    """Sort by timestamp descending."""
    return -parse_timestamp(str(article.get("timestamp", ""))).timestamp()


def cache_filename(url: str) -> str:
    """Return deterministic cache filename for an article URL."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"{digest}.jpg"


def extract_meta_image(html: str, base_url: str) -> Optional[str]:
    """Extract an OG/Twitter/image_src URL from HTML."""
    tree = HTMLParser(html)
    selectors = [
        'meta[property="og:image"]',
        'meta[property="og:image:secure_url"]',
        'meta[name="twitter:image"]',
        'link[rel="image_src"]',
    ]
    for selector in selectors:
        node = tree.css_first(selector)
        if node is None:
            continue
        image_url = node.attributes.get("content") or node.attributes.get("href")
        if image_url:
            return urljoin(base_url, image_url)
    return None


def looks_like_image(url: str, content_type: str) -> bool:
    """Return whether a URL/response appears to be an image."""
    if content_type.lower().startswith("image/"):
        return True
    guessed_type, _ = mimetypes.guess_type(url)
    return bool(guessed_type and guessed_type.startswith("image/"))


def download_image(client: httpx.Client, image_url: str, cache_path: Path) -> bool:
    """Download image bytes into cache_path."""
    try:
        with client.stream("GET", image_url, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not looks_like_image(str(response.url), content_type):
                logger.debug("OG candidate is not an image: {}", image_url)
                return False

            chunks: list[bytes] = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_IMAGE_BYTES:
                    logger.warning("Skipping oversized OG image: {}", image_url)
                    return False
                chunks.append(chunk)

        cache_path.write_bytes(b"".join(chunks))
        return True
    except Exception as exc:  # noqa: BLE001 - per-item graceful degradation
        logger.warning("Failed to download OG image {}: {}", image_url, exc)
        return False


def fetch_og_image(client: httpx.Client, article_url: str, cache_path: Path) -> bool:
    """Fetch an OG image for article_url into cache_path if possible."""
    try:
        response = client.get(article_url, follow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if looks_like_image(str(response.url), content_type):
            return download_image(client, str(response.url), cache_path)

        image_url = extract_meta_image(response.text, str(response.url))
        if image_url is None:
            logger.debug("No OG image found for {}", article_url)
            return False
        return download_image(client, image_url, cache_path)
    except Exception as exc:  # noqa: BLE001 - per-item graceful degradation
        logger.warning("Failed to fetch OG metadata {}: {}", article_url, exc)
        return False


def build_article(
    raw: dict[str, Any],
    client: httpx.Client,
    source_platforms: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Normalize one ProcessedItem-like dict for the static site."""
    genre = raw.get("genre")
    url = str(raw.get("url") or "")
    if genre not in ALLOWED_GENRES or not url:
        return None

    if _is_off_topic(genre, str(raw.get("summary") or ""), raw.get("title_tags")):
        logger.debug("Drop off-topic from games: {}", str(raw.get("summary") or "")[:60])
        return None

    filename = cache_filename(url)
    cache_path = OG_CACHE_DIR / filename
    image_url: str | None = None
    if cache_path.exists():
        image_url = f"/og-cache/{filename}"
    elif fetch_og_image(client, url, cache_path):
        image_url = f"/og-cache/{filename}"

    flags = raw.get("flags")
    if not isinstance(flags, dict):
        flags = {}

    host = urlparse(url).hostname or ""
    source_id = str(raw.get("source_id") or "")
    favicon_url = (
        f"https://www.google.com/s2/favicons?domain={host}&sz=128" if host else None
    )

    return {
        "url": url,
        "source_id": source_id,
        "source_platform": source_platforms.get(source_id, str(raw.get("platform") or "")),
        "author": str(raw.get("author") or ""),
        "timestamp": str(raw.get("timestamp") or ""),
        "genre": genre,
        "subcategory_id": str(raw.get("subcategory_id") or ""),
        "category_name": str(raw.get("category_name") or "ニュース"),
        "final_priority": str(raw.get("final_priority") or raw.get("importance") or "C"),
        "summary": str(raw.get("summary") or ""),
        "title_tags": raw.get("title_tags") if isinstance(raw.get("title_tags"), list) else [],
        "entity_tags": raw.get("entity_tags") if isinstance(raw.get("entity_tags"), list) else [],
        "flags": {
            "speed": str(flags.get("speed") or "通常"),
            "spoiler": str(flags.get("spoiler") or "なし"),
            "source_reliability": str(flags.get("source_reliability") or ""),
        },
        "image_url": image_url,
        "favicon_url": favicon_url,
        "domain": host,
    }


def load_articles() -> list[dict[str, Any]]:
    """Load and normalize articles from recent processed JSONL files."""
    articles: list[dict[str, Any]] = []
    source_platforms = load_source_platforms()
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)

    with httpx.Client(headers=headers, timeout=timeout) as client:
        for path in processed_files():
            try:
                for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                        article = build_article(raw, client, source_platforms)
                        if article is not None:
                            articles.append(article)
                    except Exception as exc:  # noqa: BLE001 - skip only this row
                        logger.warning("Skipping {}:{}: {}", path, line_number, exc)
            except Exception as exc:  # noqa: BLE001 - skip only this file
                logger.warning("Failed to read processed file {}: {}", path, exc)

    articles.sort(key=timestamp_sort_key)
    return articles


def list_digests() -> list[dict[str, str]]:
    """List generated daily digest markdown files for Astro routes."""
    if not DIGESTS_DIR.exists():
        return []

    digests: list[dict[str, str]] = []
    for path in sorted(DIGESTS_DIR.glob("*.md"), reverse=True):
        slug = path.stem
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:-(AM|PM))?", slug)
        if match is None:
            logger.warning("Skipping digest with unexpected name: {}", path)
            continue
        date_part, phase = match.groups()
        label = f"{date_part} {phase}" if phase else date_part
        digests.append({"date": date_part, "slug": slug, "label": label})
    return digests


def window_12h_count(articles: list[dict[str, Any]], now: datetime) -> int:
    """Count articles whose timestamp is in the last 12 hours."""
    start = now - timedelta(hours=12)
    return sum(1 for article in articles if parse_timestamp(str(article.get("timestamp", ""))) >= start)


def write_site_data() -> None:
    """Write site/src/data/articles.json."""
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SITE_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    OG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(UTC)
    articles = load_articles()
    digests = list_digests()
    payload = {
        "generated_at": generated_at.isoformat(),
        "window_12h_count": window_12h_count(articles, generated_at),
        "articles": articles,
        "digests": digests,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    OUTPUT_PATH.write_text(serialized, encoding="utf-8")
    PUBLIC_OUTPUT_PATH.write_text(serialized, encoding="utf-8")
    logger.info(
        "Wrote {} articles and {} digests to {}",
        len(articles),
        len(digests),
        OUTPUT_PATH,
    )


def main() -> None:
    """CLI entry point."""
    write_site_data()


if __name__ == "__main__":
    main()
