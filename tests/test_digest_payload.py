"""daily_digest に送る入力の中身のテスト

全項目を indent つきで送ると 403件で約20万トークンになっていた
指示文が使う項目だけに絞ると約8.4万トークン (2026-10-28 count_tokens で実測)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.models import Flags, ProcessedItem, WatchSource
from src.processors import digest


def _item() -> ProcessedItem:
    return ProcessedItem(
        source_id="src1",
        raw_fingerprint="fp1",
        timestamp=datetime(2026, 10, 28, 9, 30, 15, tzinfo=timezone.utc),
        url="https://example.com/1",
        author="公式X",
        genre="games",
        subcategory_id="cat1",
        category_name="新作・リリース情報",
        importance="S",
        summary="新作発表",
        title_tags=["作品A"],
        entity_tags=["会社B"],
        flags=Flags(source_role="公式", speed="速報", spoiler="軽微"),
        dedup_key="key1",
        risk_level="high",
        streamer_influence_score=80,
        streamer_name="配信者C",
    )


def test_digest_payload_keeps_fields_the_prompt_uses():
    row = json.loads(digest._digest_items_json([_item()]))[0]
    assert row == {
        "url": "https://example.com/1",
        "author": "公式X",
        "timestamp": "2026-10-28T09:30+00:00",
        "genre": "games",
        "category_name": "新作・リリース情報",
        "importance": "S",
        "risk_level": "high",
        "summary": "新作発表",
        "title_tags": ["作品A"],
        "entity_tags": ["会社B"],
        "speed": "速報",
        "source_role": "公式",
        "spoiler": "軽微",
    }


def test_digest_payload_is_compact_and_smaller():
    items = [_item() for _ in range(20)]
    new = digest._digest_items_json(items)
    assert "\n" not in new and ", " not in new
    assert len(new) < len(digest._items_to_json(items)) / 2


def test_daily_digest_sends_trimmed_payload(monkeypatch):
    sent = {}
    monkeypatch.setattr(digest.llm_client, "call_text", lambda **kw: sent.update(kw) or "ok")
    monkeypatch.setattr(digest, "_feed_source_ids", lambda: frozenset())
    digest.daily_digest([_item()], "2026-10-28 AM")
    assert "streamer_influence_score" not in sent["user"]
    assert '"importance":"S"' in sent["user"]


def _mk(n: int, importance: str = "A", genre: str = "games", speed: str = "通常", risk: str = "low", tags=None,
        source: str = "src", title: str = "", author: str = "media", category: str = "新作・リリース情報") -> ProcessedItem:
    return ProcessedItem(
        source_id=source,
        raw_fingerprint=f"fp{n}",
        timestamp=datetime(2026, 10, 28, 0, n % 60, tzinfo=timezone.utc),
        url=f"https://example.com/{n}",
        author=author,
        genre=genre,
        subcategory_id="cat",
        category_name=category,
        importance=importance,
        summary=f"item {n}",
        title_tags=tags or [],
        flags=Flags(source_role="メディア", speed=speed),
        dedup_key=f"key{n}",
        risk_level=risk,
        related_game_title=title,
    )


def test_pick_lists_s_before_a_and_caps_top():
    """S が A に埋もれない  上限15件  高リスクは上段に入れない (2026-10-28 指示文だけで絞ると S 32件を1件も選ばなかった)"""
    items = [_mk(i, "A", speed="速報") for i in range(20)]
    items += [_mk(100 + i, "S") for i in range(3)]
    items += [_mk(200, "S", risk="high")]
    picked, _ = digest._digest_pick(items)
    top_urls = [it.url for it in picked["top"]]
    assert len(top_urls) == digest.DIGEST_TOP_MAX == 15
    assert set(top_urls[:3]) == {f"https://example.com/{100 + i}" for i in range(3)}
    assert "https://example.com/200" not in top_urls
    assert [it.url for it in picked["risk"]] == ["https://example.com/200"]


def test_pick_caps_b_per_genre_and_drops_c():
    items = [_mk(i, "B", "games") for i in range(8)]
    items += [_mk(100 + i, "B", "anime") for i in range(8)]
    items += [_mk(200, "C", "games")]
    picked, _ = digest._digest_pick(items)
    assert len(picked["games"]) == len(picked["anime"]) == digest.DIGEST_GENRE_MAX == 5
    assert all(it.importance == "B" for it in picked["games"] + picked["anime"])


def test_pick_folds_duplicate_dedup_keys():
    a, b = _mk(1, "S"), _mk(2, "S")
    b.dedup_key = a.dedup_key
    assert len(digest._digest_pick([a, b])[0]["top"]) == 1


def test_stats_count_every_item_not_only_picked():
    items = [_mk(i, "A", speed="速報", tags=["作品X"]) for i in range(20)]
    items += [_mk(100 + i, "B", tags=["作品Y"]) for i in range(3)]
    stats = digest._digest_stats(items, *digest._digest_pick(items))
    assert stats["総件数"] == 23
    assert stats["速報件数"] == 20 and stats["通常件数"] == 3
    assert stats["重要件数(S/A)"] == 20
    assert stats["S/Aで載せなかった件数"] == 5
    assert stats["発信元別"] == {"メディア": 23}
    assert stats["注目タグTOP5"][0] == ["作品X", 20]


def test_daily_digest_sends_only_picked_items_and_stats(monkeypatch):
    sent = {}
    monkeypatch.setattr(digest.llm_client, "call_text", lambda **kw: sent.update(kw) or "ok")
    monkeypatch.setattr(digest, "_feed_source_ids", lambda: frozenset())
    items = [_mk(i, "A") for i in range(20)]
    digest.daily_digest(items, "2026-10-28 AM")
    assert "https://example.com/19" in sent["user"]
    assert "https://example.com/0\"" not in sent["user"]  # 新しい順に選んで上限から外れた古い分
    assert '"総件数":20' in sent["user"]


FEED = frozenset({"YSG01"})


def test_pick_caps_youtube_feed_items():
    """YouTube 検索・急上昇の投稿は上段3件・B 各2件まで (2026-10-28 は上段15件中13件が切り抜き・配信だった)"""
    items = [_mk(i, "S", source="YSG01") for i in range(10)]
    items += [_mk(100 + i, "A") for i in range(20)]
    items += [_mk(200 + i, "B", source="YSG01") for i in range(5)]
    items += [_mk(300 + i, "B") for i in range(5)]
    picked, _ = digest._digest_pick(items, FEED)
    top_sources = [it.source_id for it in picked["top"]]
    assert len(top_sources) == 15
    assert top_sources.count("YSG01") == digest.DIGEST_FEED_TOP_MAX == 3
    assert top_sources[:3] == ["YSG01"] * 3  # 上限内では順位どおり S が先
    games_sources = [it.source_id for it in picked["games"]]
    assert len(games_sources) == 5
    assert games_sources.count("YSG01") == digest.DIGEST_FEED_GENRE_MAX == 2


def test_pick_does_not_cap_sources_outside_feed():
    """公式チャンネル (platform=YouTube) は上限の対象外"""
    items = [_mk(i, "S", source="W710") for i in range(10)]
    picked, _ = digest._digest_pick(items, FEED)
    assert len(picked["top"]) == 10


def test_feed_source_ids_come_from_watchlist_platform(monkeypatch):
    sources = [
        WatchSource(id="SRQ001", name="検索", platform="YouTubeSearch", genre="games", source_type="メディア"),
        WatchSource(id="TR001", name="急上昇", platform="YouTubeTrending", genre="games", source_type="メディア"),
        WatchSource(id="W710", name="Crunchyroll", platform="YouTube", genre="anime", source_type="メディア"),
    ]
    paths = []
    monkeypatch.setattr(digest.watchlist, "_load_from_csv", lambda path: paths.append(path) or sources)
    assert digest._feed_source_ids() == {"SRQ001", "TR001"}
    assert paths == [digest.watchlist.LOCAL_CACHE]  # Sheets 同期をする load() でなく手元の CSV


def test_feed_source_ids_survive_broken_csv(monkeypatch):
    """CSV が壊れていてもダイジェストは止めず、上限なしで作る"""
    def broken(_path):
        raise KeyError("platform")
    monkeypatch.setattr(digest.watchlist, "_load_from_csv", broken)
    assert digest._feed_source_ids() == set()


def test_pick_folds_same_title_and_passes_other_sources():
    """同じ作品の別 URL は1件に束ね、ほかの媒体名を渡す (10/28 の ArcheAge Chronicles 早期アクセスが3媒体で並んだ)"""
    items = [
        _mk(1, "S", title="ArcheAge Chronicles", author="電ファミ", category="早期アクセス"),
        _mk(2, "A", title="archeage chronicles", author="AUTOMATON", category="早期アクセス"),
        _mk(3, "A", title="ArcheAge Chronicles", author="Gematsu", category="早期アクセス"),
        _mk(4, "A", title="Grand Theft Auto VI", author="Kotaku"),
    ]
    picked, folded = digest._digest_pick(items)
    assert [it.author for it in picked["top"]] == ["電ファミ", "Kotaku"]
    rows = json.loads(digest._digest_items_json(picked["top"], folded))
    assert rows[0]["also"] == ["Gematsu", "AUTOMATON"]  # 束ねた側も重要度→新しい順
    assert "also" not in rows[1]


def test_fold_ignores_category():
    """カテゴリが違っても同じ作品なら1行  カテゴリは LLM が記事ごとに揺れて付けるので、揃えると同じ出来事が割れた
    (10/22 の BioWare 閉鎖が「サービス終了」「続編」「新タイトル発表」の3行)"""
    items = [
        _mk(1, "S", title="Mass Effect", author="Siliconera", category="サービス終了"),
        _mk(2, "S", title="Mass Effect", author="IGN", category="続編"),
        _mk(3, "S", title="Mass Effect", author="電ファミ", category="新タイトル発表"),
    ]
    picked, folded = digest._digest_pick(items)
    assert [it.author for it in picked["top"]] == ["電ファミ"]  # 同じ S なら新しい順
    assert [it.author for it in folded[picked["top"][0].dedup_key]] == ["IGN", "Siliconera"]


def test_fold_keeps_b_genres_apart():
    """ゲームの B とアニメの B は別の欄  束ねるとアニメ欄から item が消えた"""
    items = [_mk(1, "B", "games", title="作品X"), _mk(2, "B", "anime", title="作品X")]
    picked, folded = digest._digest_pick(items)
    assert len(picked["games"]) == len(picked["anime"]) == 1 and folded == {}


def test_fold_skips_c_and_placeholder_titles():
    """作品名の欄に入った「anime」「不明」などで別作品を束ねない  C は載せないので束ねない"""
    items = [_mk(1, "A", title="anime"), _mk(2, "A", title="Anime"), _mk(3, "A", title="不明"), _mk(4, "A", title="不明")]
    items += [_mk(5, "A", title="n"), _mk(6, "A", title="N")]
    items += [_mk(7, "C", title="作品X"), _mk(8, "C", title="作品X")]
    items += [_mk(9, "A", title="Xbox"), _mk(10, "A", title="Xbox")]  # 07/07 は議員の発言と CEO の表明が束なった
    picked, folded = digest._digest_pick(items)
    assert len(picked["top"]) == 8 and folded == {}
    assert all(digest._fold_key(it) is None for it in items)


def test_fold_prefers_representative_outside_feed():
    """切り抜きが代表になると上限で落ちたとき記事ごと消えるので、記事を代表にする"""
    clip = _mk(1, "S", source="YSG01", title="Zenless Zone Zero", author="切り抜きch")
    article = _mk(2, "A", title="Zenless Zone Zero", author="Gematsu")
    picked, folded = digest._digest_pick([clip, article], FEED)
    assert [it.author for it in picked["top"]] == ["Gematsu"]
    assert [it.author for it in folded[article.dedup_key]] == ["切り抜きch"]
    assert json.loads(digest._digest_items_json(picked["top"], folded))[0]["importance"] == "S"  # グループの最上位


def test_fold_places_group_where_its_best_member_was():
    """記事を代表にしても、グループは S の切り抜きの位置に置く  A の記事の位置だと上段15件から押し出された"""
    clip = _mk(1, "S", source="YSG01", title="作品X", author="切り抜きch")
    others = [_mk(100 + i, "A") for i in range(20)]
    article = _mk(2, "A", title="作品X", author="Gematsu")  # 他の A より古い
    picked, _ = digest._digest_pick([clip, article, *others], FEED)
    assert picked["top"][0] is article


def test_feed_cap_counts_a_folded_group_once():
    """切り抜きだけのグループは代表1件として上限を数え、上限で落ちたグループの束ねは返さない"""
    items = [_mk(i * 10 + j, "S", source="YSG01", title=f"作品{i}", author=f"ch{j}") for i in range(4) for j in range(2)]
    picked, folded = digest._digest_pick(items, FEED)
    assert len(picked["top"]) == digest.DIGEST_FEED_TOP_MAX == 3
    assert set(folded) == {it.dedup_key for it in picked["top"]}


def test_risk_section_has_no_feed_cap():
    """高リスク欄は YouTube 検索枠の上限を掛けない (見落としたくない欄なので従来どおり)"""
    items = [_mk(i, "S", source="YSG01", risk="high") for i in range(5)]
    picked, _ = digest._digest_pick(items, FEED)
    assert len(picked["risk"]) == digest.DIGEST_RISK_MAX == 5


def test_fold_skips_items_without_title():
    """作品名が空なら束ねない  タグの重なりで束ねると別作品がくっついた (Aloft と Moonlight Peaks)"""
    items = [_mk(1, "A", tags=["PlayStation 5", "発売日"]), _mk(2, "A", tags=["PlayStation 5", "発売日"])]
    picked, folded = digest._digest_pick(items)
    assert len(picked["top"]) == 2 and folded == {}


def test_fold_keeps_high_risk_apart():
    items = [_mk(1, "S", title="作品X", risk="high"), _mk(2, "A", title="作品X")]
    picked, _ = digest._digest_pick(items)
    assert len(picked["top"]) == 1 and len(picked["risk"]) == 1


def test_stats_count_folded_items_only_when_named():
    """束ねた分は「ほか」に媒体名が出たものだけ載せた扱い  媒体名は3つまでなので5件中1件は載せなかった側"""
    items = [_mk(i, "A", title="作品X", author=f"ch{i}") for i in range(5)]
    stats = digest._digest_stats(items, *digest._digest_pick(items))
    assert stats["S/Aで載せなかった件数"] == 1


def test_daily_digest_passes_feed_ids_and_also(monkeypatch):
    sent = {}
    monkeypatch.setattr(digest.llm_client, "call_text", lambda **kw: sent.update(kw) or "ok")
    monkeypatch.setattr(digest, "_feed_source_ids", lambda: FEED)
    items = [_mk(i, "S", source="YSG01") for i in range(5)]
    items += [_mk(100, "A", title="作品X", author="媒体1"), _mk(101, "A", title="作品X", author="媒体2")]
    digest.daily_digest(items, "2026-10-28 AM")
    assert sent["user"].count('"importance":"S"') == 3
    assert "この欄の item は 4件" in sent["user"]  # S 3件 + 束ねた A 1件
    assert '"also":["媒体2"]' in sent["user"] or '"also":["媒体1"]' in sent["user"]


def test_also_lists_at_most_three_other_sources():
    """ゼンゼロの切り抜きは1作品に9件束なった  媒体名は3つまで・代表と同じ媒体名は出さない"""
    items = [_mk(i, "A", title="Zenless Zone Zero", author=f"ch{i}") for i in range(9)]
    items.append(_mk(99, "A", title="Zenless Zone Zero", author="ch8"))
    picked, folded = digest._digest_pick(items)
    rows = json.loads(digest._digest_items_json(picked["top"], folded))
    assert len(rows) == 1
    assert len(rows[0]["also"]) == digest.DIGEST_ALSO_MAX == 3
    assert rows[0]["author"] not in rows[0]["also"]
