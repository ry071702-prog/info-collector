"""非APIサイトを Browser Use(ローカルFastAPIサーバ)で取得する collector(組織インテリジェンス用)。

platform == "Web" の WatchSource を対象に、~/browser-use-lab の `/run` へ
「このURLの最新の更新・お知らせ見出しを抽出して」と依頼し、結果を RawItem 化する。
サーバ未起動・到達不可でも例外を投げず [] を返す(個人/cloud パイプラインを止めない)。

依存 env:
- BROWSER_USE_URL (既定 http://localhost:8799/run)
- BU_SERVER_TOKEN (任意。設定時は X-Token ヘッダを付与)
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .. import logger
from ..config import env
from ..models import RawItem, WatchSource

log = logger.get(__name__)

_DEFAULT_URL = "http://localhost:8799/run"


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    """platform=="Web" の source を Browser Use で取得。到達不可なら空。"""
    web_sources = [s for s in sources if s.platform == "Web"]
    if not web_sources:
        return []
    base = env("BROWSER_USE_URL", _DEFAULT_URL)
    token = env("BU_SERVER_TOKEN")
    headers = {"X-Token": token} if token else {}

    out: list[RawItem] = []
    for s in web_sources:
        task = (
            f"Open {s.url} and extract the latest news / updates / announcement headlines "
            f"(for each: title and a one-line summary, plus the item URL if visible). "
            f"Return a concise plain-text bullet list. Do not navigate to external sites."
        )
        try:
            resp = httpx.post(
                base,
                json={"task": task, "max_steps": 12, "headless": True},
                headers=headers,
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning(f"browser-use unreachable for {s.name} ({e}); skip")
            continue
        result = str(data.get("result") or "").strip()
        if not result:
            continue
        out.append(
            RawItem(
                source_id=s.id,
                platform="Web",
                author=s.name,
                account_type=s.source_type,
                text=result,
                url=s.url,
                timestamp=datetime.now(timezone.utc),
            )
        )
    log.info(f"web_browseruse: collected {len(out)} from {len(web_sources)} Web sources")
    return out
