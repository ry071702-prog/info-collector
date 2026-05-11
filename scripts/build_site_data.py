"""Build static news-site data from processed JSONL files."""
from __future__ import annotations

import hashlib
import json
import mimetypes
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
OG_CACHE_DIR = ROOT_DIR / "site" / "public" / "og-cache"
OUTPUT_PATH = SITE_DATA_DIR / "articles.json"

ALLOWED_GENRES = {"games", "anime", "disney"}
PRIORITY_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
RECENT_DAYS = 30
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_IMAGE_BYTES = 4 * 1024 * 1024
UTC = timezone.utc
USER_AGENT = (
    "Mozilla/5.0 (compatible; info-collector-site/1.0; "
    "+https://github.com/)"
)


def parse_date_from_filename(path: Path) -> Optional[date]:
    """Return YYYY-MM-DD date from a processed JSONL filename."""
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d").date()
    except ValueError:
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
    for path in sorted(PROCESSED_DIR.glob("*.jsonl")):
        file_date = parse_date_from_filename(path)
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


def build_article(raw: dict[str, Any], client: httpx.Client) -> Optional[dict[str, Any]]:
    """Normalize one ProcessedItem-like dict for the static site."""
    genre = raw.get("genre")
    url = str(raw.get("url") or "")
    if genre not in ALLOWED_GENRES or not url:
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
    favicon_url = (
        f"https://www.google.com/s2/favicons?domain={host}&sz=128" if host else None
    )

    return {
        "url": url,
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
                        article = build_article(raw, client)
                        if article is not None:
                            articles.append(article)
                    except Exception as exc:  # noqa: BLE001 - skip only this row
                        logger.warning("Skipping {}:{}: {}", path, line_number, exc)
            except Exception as exc:  # noqa: BLE001 - skip only this file
                logger.warning("Failed to read processed file {}: {}", path, exc)

    articles.sort(key=sort_key)
    return articles


def list_digests() -> list[dict[str, str]]:
    """List generated daily digest markdown files for Astro routes."""
    if not DIGESTS_DIR.exists():
        return []

    digests: list[dict[str, str]] = []
    for path in sorted(DIGESTS_DIR.glob("*.md"), reverse=True):
        slug = path.stem
        digests.append({"date": slug, "slug": slug})
    return digests


def write_site_data() -> None:
    """Write site/src/data/articles.json."""
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    OG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    articles = load_articles()
    digests = list_digests()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "articles": articles,
        "digests": digests,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
