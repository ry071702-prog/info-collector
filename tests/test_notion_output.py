"""src/outputs/notion.py のテスト。notion_client / httpx はすべて fake に差し替え、実 API は呼ばない。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from notion_client.errors import APIResponseError

from src.models import Flags, ProcessedItem
from src.outputs import notion

UUID = "0123456789abcdef0123456789abcdef"
UUID_DASHED = "01234567-89ab-cdef-0123-456789abcdef"
DB_GAMES = "11111111111111111111111111111111"
DB_ANIME = "22222222222222222222222222222222"
DB_DISNEY = "33333333333333333333333333333333"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """fake を差し忘れたテストや src 側の早期 return が崩れた場合でも実 API に出ないための安全網
    個々のテストが monkeypatch で fake を入れればそちらが優先される
    """
    import notion_client

    def _blocked(*a: Any, **k: Any) -> Any:
        pytest.fail("実ネットワーク呼び出しは禁止 (fake を差し替えてください)")

    class _BlockedClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            _blocked()

    monkeypatch.setattr(notion_client, "Client", _BlockedClient)
    for name in ("get", "post", "patch", "put", "delete", "request"):
        monkeypatch.setattr(httpx, name, _blocked)


def _dashed(h: str) -> str:
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _item(key: str = "k1", genre: str = "games", **kw: Any) -> ProcessedItem:
    base: dict[str, Any] = dict(
        source_id="src1",
        raw_fingerprint=key,
        timestamp=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        url=f"https://example.com/{key}",
        author="author",
        genre=genre,
        subcategory_id="G1",
        category_name="Category",
        importance="A",
        summary="Summary",
        flags=Flags(source_role="公式"),
        dedup_key=key,
    )
    base.update(kw)
    return ProcessedItem(**base)


def _api_error(message: str) -> APIResponseError:
    return APIResponseError(
        code="validation_error",
        status=400,
        message=message,
        headers=httpx.Headers(),
        raw_body_text="",
    )


class FakeDatabases:
    def __init__(self, schemas: dict[str, Any]):
        self.schemas = schemas
        self.calls: list[str] = []

    def retrieve(self, database_id: str) -> dict:
        self.calls.append(database_id)
        schema = self.schemas.get(database_id)
        if isinstance(schema, Exception):
            raise schema
        return {"properties": {k: {} for k in (schema or [])}}


class FakePages:
    def __init__(self, errors: list[Exception | None] | None = None):
        self.errors = list(errors or [])
        self.created: list[dict] = []

    def create(self, parent: dict, properties: dict) -> dict:
        err = self.errors.pop(0) if self.errors else None
        if err is not None:
            raise err
        self.created.append({"parent": parent, "properties": properties})
        return {"id": "page"}


class FakeClient:
    def __init__(self, schemas: dict[str, Any] | None = None, errors: list[Exception | None] | None = None):
        self.databases = FakeDatabases(schemas or {})
        self.pages = FakePages(errors)


@pytest.fixture
def notion_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("NOTION_TOKEN", "secret-token")
    monkeypatch.setenv("NOTION_DATABASE_ID_GAMES", DB_GAMES)
    monkeypatch.setenv("NOTION_DATABASE_ID_ANIME", DB_ANIME)
    monkeypatch.setenv("NOTION_DATABASE_ID_DISNEY", DB_DISNEY)


def _install_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(notion, "_client", lambda: client)


# --- normalize_db_id / helpers ------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (UUID, UUID_DASHED),
        (UUID_DASHED, UUID_DASHED),
        (f"  https://www.notion.so/ws/Games-{UUID}?v=abc  ", UUID_DASHED),
        ("  not-an-id  ", "not-an-id"),
        ("", ""),
        (None, None),
    ],
)
def test_normalize_db_id(raw, expected):
    assert notion.normalize_db_id(raw) == expected


def test_disney_category_label():
    assert notion._disney_category_label("DA1") == "公式発表・ニュース"
    assert notion._disney_category_label("do3") == "トレーラー・予告映像"
    assert notion._disney_category_label("ZZ1") is None
    assert notion._disney_category_label("") is None


def test_filter_existing_drops_unknown_props():
    props = {"Title": 1, "Importance": 2, "RiskLevel": 3}
    assert notion._filter_existing(props, {"Title", "RiskLevel"}) == {"Title": 1, "RiskLevel": 3}
    assert notion._filter_existing(props, set()) == {}


def test_client_uses_pinned_api_version(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class StubClient:
        def __init__(self, **kw):
            captured.update(kw)

    import notion_client

    monkeypatch.setattr(notion_client, "Client", StubClient)
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    notion._client()
    assert captured == {"auth": "tok", "notion_version": "2022-06-28"}


def test_client_requires_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        notion._client()


# --- _properties ---------------------------------------------------------------


def test_properties_basic_mapping():
    it = _item(
        title_tags=["t1", "t2"],
        entity_tags=["t2", "e1"],
        risk_level="high",
        final_priority="S",
        freshness_score=90,
        streamer_influence_score=10,
        is_clip=True,
    )
    p = notion._properties(it)
    assert p["Title"] == {"title": [{"text": {"content": "Summary"}}]}
    assert p["Importance"] == {"select": {"name": "A"}}
    assert p["Category"] == {"select": {"name": "G1"}}
    assert p["Genre"] == {"select": {"name": "games"}}
    assert p["URL"] == {"url": "https://example.com/k1"}
    assert p["Timestamp"] == {"date": {"start": "2026-10-01T12:00:00+00:00"}}
    assert p["Spoiler"] == {"select": {"name": "なし"}}
    assert p["Source"] == {"select": {"name": "公式"}}
    assert p["RiskLevel"] == {"select": {"name": "high"}}
    assert p["FinalPriority"] == {"select": {"name": "S"}}
    assert p["FreshnessScore"] == {"number": 90}
    assert p["StreamerInfluence"] == {"number": 10}
    assert p["IsClip"] == {"checkbox": True}
    # tags は重複除去されて TagsText に入る。旧 multi_select "Tags" は書かない
    assert "Tags" not in p
    tags_text = p["TagsText"]["rich_text"][0]["text"]["content"]
    assert sorted(tags_text.split(", ")) == ["e1", "t1", "t2"]


def test_properties_empty_optionals_and_truncation():
    it = _item(url="", summary="x" * 500, dedup_key="d" * 500)
    p = notion._properties(it)
    assert p["URL"] == {"url": None}
    assert p["TagsText"] == {"rich_text": []}
    assert p["StreamerName"] == {"rich_text": []}
    assert p["StreamerGroup"] == {"select": None}
    assert p["RelatedGameTitle"] == {"rich_text": []}
    assert p["RelatedAnimeTitle"] == {"rich_text": []}
    assert len(p["Title"]["title"][0]["text"]["content"]) == 200
    assert len(p["DedupKey"]["rich_text"][0]["text"]["content"]) == 200


def test_properties_streamer_fields_filled():
    it = _item(
        streamer_name="SHAKA",
        streamer_group="Crazy Raccoon",
        related_game_title="VALORANT",
        related_anime_title="Frieren",
    )
    p = notion._properties(it)
    assert p["StreamerName"]["rich_text"][0]["text"]["content"] == "SHAKA"
    assert p["StreamerGroup"] == {"select": {"name": "Crazy Raccoon"}}
    assert p["RelatedGameTitle"]["rich_text"][0]["text"]["content"] == "VALORANT"
    assert p["RelatedAnimeTitle"]["rich_text"][0]["text"]["content"] == "Frieren"


# --- schema / error helpers ------------------------------------------------------


def test_db_property_names_success_and_failure():
    client = FakeClient(schemas={"ok": ["Title", "URL"], "ng": RuntimeError("boom")})
    assert notion._db_property_names(client, "ok") == {"Title", "URL"}
    assert notion._db_property_names(client, "ng") == set()


def test_missing_property_names():
    err = _api_error("RiskLevel is not a property that exists. ClipVirality is not a property that exists.")
    assert notion._missing_property_names(err) == {"RiskLevel", "ClipVirality"}
    # APIResponseError でも別種のメッセージは対象外
    assert notion._missing_property_names(_api_error("body failed validation")) == set()
    # APIResponseError 以外は対象外
    assert notion._missing_property_names(RuntimeError("RiskLevel is not a property that exists")) == set()


def test_create_page_with_retry_success():
    client = FakeClient()
    ok, dropped = notion._create_page_with_retry(client, "db", {"Title": 1}, "k")
    assert (ok, dropped) == (True, set())
    assert client.pages.created == [{"parent": {"database_id": "db"}, "properties": {"Title": 1}}]


def test_create_page_with_retry_drops_missing_and_retries():
    client = FakeClient(errors=[_api_error('"RiskLevel" is not a property that exists.')])
    ok, dropped = notion._create_page_with_retry(client, "db", {"Title": 1, "RiskLevel": 2}, "k")
    assert ok is True
    assert dropped == {"RiskLevel"}
    assert client.pages.created[0]["properties"] == {"Title": 1}


def test_create_page_with_retry_non_schema_error_fails():
    client = FakeClient(errors=[RuntimeError("network down")])
    assert notion._create_page_with_retry(client, "db", {"Title": 1}, "k") == (False, set())
    assert client.pages.created == []


def test_create_page_with_retry_missing_prop_not_in_payload_fails():
    client = FakeClient(errors=[_api_error("Other is not a property that exists.")])
    assert notion._create_page_with_retry(client, "db", {"Title": 1}, "k") == (False, set())


def test_create_page_with_retry_second_failure():
    client = FakeClient(
        errors=[_api_error("RiskLevel is not a property that exists."), RuntimeError("still down")]
    )
    ok, dropped = notion._create_page_with_retry(client, "db", {"Title": 1, "RiskLevel": 2}, "k")
    assert ok is False
    assert dropped == {"RiskLevel"}


# --- write ---------------------------------------------------------------------------


def test_write_dry_run_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DRY_RUN", "true")

    def boom():
        raise AssertionError("client must not be created in DRY_RUN")

    monkeypatch.setattr(notion, "_client", boom)
    assert notion.write([_item()]) == (0, [])


def test_write_without_db_ids_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    for k in ("NOTION_DATABASE_ID_GAMES", "NOTION_DATABASE_ID_ANIME", "NOTION_DATABASE_ID_DISNEY"):
        monkeypatch.delenv(k, raising=False)
    # 設定漏れは再送しても直らないので failed にも積まない
    assert notion.write([_item()]) == (0, [])


def test_write_auth_failure_returns_all_as_failed(monkeypatch: pytest.MonkeyPatch, notion_env):
    def fail():
        raise RuntimeError("auth")

    monkeypatch.setattr(notion, "_client", fail)
    items = [_item("a"), _item("b")]
    assert notion.write(items) == (0, items)


def test_write_routes_by_genre_and_filters_schema(monkeypatch: pytest.MonkeyPatch, notion_env):
    schemas = {
        _dashed(DB_GAMES): ["Title", "Importance", "Genre"],
        _dashed(DB_ANIME): ["Title", "Genre", "RiskLevel"],
        _dashed(DB_DISNEY): ["Title", "Category", "SubcategoryRaw"],
    }
    client = FakeClient(schemas=schemas)
    _install_client(monkeypatch, client)

    items = [
        _item("g", genre="games"),
        _item("b", genre="both"),
        _item("n", genre="neither"),
        _item("a", genre="anime"),
        _item("d", genre="disney", subcategory_id="DB2"),
    ]
    success, failed = notion.write(items)
    assert (success, failed) == (5, [])

    by_db = [(c["parent"]["database_id"], c["properties"]) for c in client.pages.created]
    assert [db for db, _ in by_db] == [
        _dashed(DB_GAMES),
        _dashed(DB_GAMES),
        _dashed(DB_GAMES),
        _dashed(DB_ANIME),
        _dashed(DB_DISNEY),
    ]
    assert set(by_db[0][1]) == {"Title", "Importance", "Genre"}
    assert set(by_db[3][1]) == {"Title", "Genre", "RiskLevel"}
    disney_props = by_db[4][1]
    assert set(disney_props) == {"Title", "Category", "SubcategoryRaw"}
    assert disney_props["Category"] == {"select": {"name": "映画・劇場公開"}}
    assert disney_props["SubcategoryRaw"] == {"rich_text": [{"text": {"content": "DB2"}}]}
    # schema は DB ごとに 1 回だけ取得する
    assert sorted(client.databases.calls) == sorted(schemas)


def test_write_disney_unknown_group_keeps_raw_category(monkeypatch: pytest.MonkeyPatch, notion_env):
    client = FakeClient(schemas={_dashed(DB_DISNEY): ["Category"]})
    _install_client(monkeypatch, client)
    notion.write([_item("d", genre="disney", subcategory_id="X9")])
    assert client.pages.created[0]["properties"] == {"Category": {"select": {"name": "X9"}}}


def test_write_schema_failure_falls_back_to_core_props(monkeypatch: pytest.MonkeyPatch, notion_env):
    client = FakeClient(schemas={_dashed(DB_GAMES): RuntimeError("schema down")})
    _install_client(monkeypatch, client)
    success, failed = notion.write([_item("g")])
    assert (success, failed) == (1, [])
    props = client.pages.created[0]["properties"]
    assert set(props) == notion._CORE_SAFE_PROPS
    assert "RiskLevel" not in props


def test_write_skips_genre_without_db(monkeypatch: pytest.MonkeyPatch, notion_env):
    monkeypatch.delenv("NOTION_DATABASE_ID_ANIME")
    client = FakeClient(schemas={_dashed(DB_GAMES): ["Title"]})
    _install_client(monkeypatch, client)
    success, failed = notion.write([_item("a", genre="anime"), _item("g")])
    # DB 未設定の genre は成功にも失敗にも数えない
    assert (success, failed) == (1, [])
    assert len(client.pages.created) == 1


def test_write_collects_failures_and_learns_dropped_props(monkeypatch: pytest.MonkeyPatch, notion_env):
    db = _dashed(DB_GAMES)
    client = FakeClient(
        schemas={db: ["Title", "RiskLevel"]},
        errors=[
            _api_error("RiskLevel is not a property that exists."),  # 1件目: 欠落列を落として再試行
            None,
            None,  # 2件目: 学習済みなので RiskLevel なしで一発成功
            RuntimeError("down"),  # 3件目: 失敗 → failed に積む
        ],
    )
    _install_client(monkeypatch, client)
    items = [_item("1"), _item("2"), _item("3")]
    success, failed = notion.write(items)
    assert success == 2
    assert [it.dedup_key for it in failed] == ["3"]
    assert client.pages.created[0]["properties"].keys() == {"Title"}
    assert client.pages.created[1]["properties"].keys() == {"Title"}


# --- archive_by_urls ---------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def test_archive_dry_run(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no HTTP in DRY_RUN"))
    assert notion.archive_by_urls(["https://example.com/a"]) == 0


def test_archive_empty_urls(notion_env):
    assert notion.archive_by_urls([]) == 0


def test_archive_without_db_ids_or_token(monkeypatch: pytest.MonkeyPatch, notion_env):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.delenv("NOTION_TOKEN")
    assert notion.archive_by_urls(["u"]) == 0
    for k in ("NOTION_DATABASE_ID_GAMES", "NOTION_DATABASE_ID_ANIME", "NOTION_DATABASE_ID_DISNEY"):
        monkeypatch.delenv(k)
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    assert notion.archive_by_urls(["u"]) == 0


def test_archive_queries_each_db_and_archives_pages(monkeypatch: pytest.MonkeyPatch, notion_env):
    posts: list[tuple[str, dict, dict]] = []
    patches: list[tuple[str, dict]] = []
    results = {
        _dashed(DB_GAMES): FakeResponse(200, {"results": [{"id": "p1"}, {"id": "p2"}, {}]}),
        _dashed(DB_ANIME): FakeResponse(500, text="server error"),
    }

    def fake_post(url, headers, json, timeout):
        posts.append((url, headers, json))
        db_id = url.split("/databases/")[1].split("/")[0]
        if db_id == _dashed(DB_DISNEY):
            raise httpx.ConnectError("unreachable")
        return results[db_id]

    def fake_patch(url, headers, json, timeout):
        patches.append((url, json))
        page = url.rsplit("/", 1)[1]
        if page == "p2":
            return FakeResponse(404, text="not found")
        return FakeResponse(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "patch", fake_patch)

    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/a"]
    assert notion.archive_by_urls(urls) == 1  # p1 のみ成功、p2 は 404

    assert len(posts) == 3
    url, headers, body = posts[0]
    assert url == f"https://api.notion.com/v1/databases/{_dashed(DB_GAMES)}/query"
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Notion-Version"] == "2022-06-28"
    # URL は順序を保って重複除去される
    assert body["filter"]["or"] == [
        {"property": "URL", "url": {"equals": "https://example.com/a"}},
        {"property": "URL", "url": {"equals": "https://example.com/b"}},
    ]
    assert sorted(u for u, _ in patches) == [
        "https://api.notion.com/v1/pages/p1",
        "https://api.notion.com/v1/pages/p2",
    ]
    assert all(body == {"archived": True} for _, body in patches)


def test_archive_batches_by_100_and_handles_patch_exception(monkeypatch: pytest.MonkeyPatch, notion_env):
    monkeypatch.delenv("NOTION_DATABASE_ID_ANIME")
    monkeypatch.delenv("NOTION_DATABASE_ID_DISNEY")
    batch_sizes: list[int] = []

    def fake_post(url, headers, json, timeout):
        batch_sizes.append(len(json["filter"]["or"]))
        return FakeResponse(200, {"results": [{"id": "p1"}]})

    def fake_patch(url, headers, json, timeout):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "patch", fake_patch)
    urls = [f"https://example.com/{i}" for i in range(250)]
    assert notion.archive_by_urls(urls) == 0
    assert batch_sizes == [100, 100, 50]
