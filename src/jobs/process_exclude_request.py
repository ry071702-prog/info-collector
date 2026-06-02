"""GitHub Issue の本文から URL を抽出し、Sheets / Notion から該当記事を除去する。

Issue body は site の「不要リスト送信」ボタンが生成した形式を前提:

    ## 削除対象 URL

    - https://example.com/article-a
    - https://example.com/article-b

実行時は環境変数 ISSUE_BODY に Issue 本文を渡す。
"""
from __future__ import annotations

import os
import re
import sys

from .. import logger
from ..outputs import notion as notion_out
from ..outputs import sheets as sheets_out

log = logger.get(__name__)

URL_PATTERN = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def extract_urls(body: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_PATTERN.finditer(body or ""):
        url = match.group(0).rstrip(".,;:")
        if url in seen:
            continue
        # github.com 関連 URL は除外 (テンプレ末尾の案内文に紛れることがある)
        if "github.com" in url:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    urls = extract_urls(body)
    log.info(f"extracted {len(urls)} URL(s) from issue body")
    if not urls:
        print("No URLs found in issue body.")
        return 0

    sheets_deleted = sheets_out.delete_by_urls(urls)
    notion_archived = notion_out.archive_by_urls(urls)

    summary = (
        f"Sheets: {sheets_deleted} 行削除\n"
        f"Notion: {notion_archived} ページ archive\n"
        f"対象 URL: {len(urls)} 件"
    )
    log.info(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
