"""Twitch API collector (Helix). App access token flow."""
from __future__ import annotations
from datetime import datetime, timezone

import httpx

from .. import logger
from ..config import env, settings
from ..models import RawItem, WatchSource

log = logger.get(__name__)
_token_cache: dict = {"token": None, "expires_at": None}


def _get_token() -> str:
    if _token_cache["token"] and _token_cache["expires_at"] and datetime.utcnow() < _token_cache["expires_at"]:
        return _token_cache["token"]
    cid = env("TWITCH_CLIENT_ID", required=True)
    csec = env("TWITCH_CLIENT_SECRET", required=True)
    resp = httpx.post(
        "https://id.twitch.tv/oauth2/token",
        params={"client_id": cid, "client_secret": csec, "grant_type": "client_credentials"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    from datetime import timedelta
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 300)
    return data["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Client-Id": env("TWITCH_CLIENT_ID", required=True)}


def _user_id(login: str) -> str | None:
    r = httpx.get("https://api.twitch.tv/helix/users", params={"login": login}, headers=_headers(), timeout=15.0)
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def _collect_streamer(source: WatchSource, since: datetime) -> list[RawItem]:
    login = source.handle.lstrip("@")
    uid = _user_id(login)
    if not uid:
        log.warning(f"Twitch user not found: {login}")
        return []

    items: list[RawItem] = []

    # Live streams
    r = httpx.get("https://api.twitch.tv/helix/streams", params={"user_id": uid}, headers=_headers(), timeout=15.0)
    if r.status_code == 200:
        for s in r.json().get("data", []):
            items.append(
                RawItem(
                    source_id=source.id,
                    platform="Twitch",
                    author=login,
                    account_type=source.source_type,
                    text=f"[LIVE] {s.get('title','')} | game: {s.get('game_name','')}",
                    url=f"https://twitch.tv/{login}",
                    timestamp=datetime.fromisoformat(s["started_at"].replace("Z", "+00:00")),
                    extra={"viewer_count": s.get("viewer_count", 0)},
                )
            )

    # Recent VODs
    vod_max = settings()["collectors"]["twitch"]["recent_videos_max"]
    r = httpx.get(
        "https://api.twitch.tv/helix/videos",
        params={"user_id": uid, "first": vod_max, "type": "archive"},
        headers=_headers(),
        timeout=15.0,
    )
    if r.status_code == 200:
        for v in r.json().get("data", []):
            published = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            if published < since:
                continue
            items.append(
                RawItem(
                    source_id=source.id,
                    platform="Twitch",
                    author=login,
                    account_type=source.source_type,
                    text=f"[VOD] {v.get('title','')}",
                    url=v.get("url", f"https://twitch.tv/{login}"),
                    timestamp=published,
                    extra={"duration": v.get("duration", "")},
                )
            )
    return items


def collect(sources: list[WatchSource], since: datetime) -> list[RawItem]:
    tw_sources = [s for s in sources if s.platform == "Twitch"]
    out: list[RawItem] = []
    for s in tw_sources:
        try:
            out.extend(_collect_streamer(s, since))
        except Exception as e:  # noqa: BLE001
            log.error(f"Twitch collection failed for {s.handle}: {e}")
    return out
