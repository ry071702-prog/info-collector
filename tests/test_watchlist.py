"""src/watchlist.py のテスト。

config/watchlist.csv (運用データ) には触れず、LOCAL_CACHE を tmp_path に差し替える。
Google Sheets は gspread / service_account を sys.modules ごと偽物に置き換え、実通信しない。
"""
from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

import pytest

from src import watchlist
from src.models import WatchSource

HEADER = [
    "id", "name", "handle", "url", "platform", "genre", "source_type",
    "subcategory_hints", "priority", "enabled", "check_frequency", "language", "notes",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in HEADER})
    return path


def _row(**over: str) -> dict[str, str]:
    base = {
        "id": "s1",
        "name": "Source 1",
        "handle": "@s1",
        "url": "https://example.com/s1",
        "platform": "X",
        "genre": "games",
        "source_type": "公式",
        "subcategory_hints": "news, release ,",
        "priority": "high",
        "enabled": "TRUE",
        "check_frequency": "realtime",
        "language": "ja",
        "notes": "memo",
    }
    base.update(over)
    return base


def _src(id_: str, freq: str) -> WatchSource:
    return WatchSource(
        id=id_, name=id_, platform="RSS", genre="games", source_type="メディア",
        check_frequency=freq,  # type: ignore[arg-type]
    )


class FakeWorksheet:
    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records or []
        self.calls: list[tuple] = []

    def get_all_records(self) -> list[dict]:
        return self.records

    def clear(self) -> None:
        self.calls.append(("clear",))

    def update(self, *args, **kwargs) -> None:
        self.calls.append(("update", args, kwargs))


@pytest.fixture
def fake_sheets(monkeypatch: pytest.MonkeyPatch) -> dict:
    """gspread と google.oauth2.service_account を偽モジュールに置き換える。"""
    state: dict = {"ws": FakeWorksheet(), "opened": [], "worksheet_names": [], "creds_info": None}

    class FakeSpreadsheet:
        def worksheet(self, name: str) -> FakeWorksheet:
            state["worksheet_names"].append(name)
            return state["ws"]

    class FakeClient:
        def open_by_key(self, key: str) -> FakeSpreadsheet:
            state["opened"].append(key)
            return FakeSpreadsheet()

    fake_gspread = types.ModuleType("gspread")
    fake_gspread.authorize = lambda creds: FakeClient()  # type: ignore[attr-defined]

    class FakeCredentials:
        @staticmethod
        def from_service_account_info(info, scopes):
            state["creds_info"] = info
            state["scopes"] = scopes
            return object()

    fake_sa = types.ModuleType("google.oauth2.service_account")
    fake_sa.Credentials = FakeCredentials  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_sa)
    return state


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SYNC_SHEETS_FROM_CSV", "GOOGLE_SHEETS_CREDENTIALS", "GOOGLE_SHEETS_ID"):
        monkeypatch.delenv(key, raising=False)


# --- _parse_row ---------------------------------------------------------------

def test_parse_row_splits_hints_and_parses_enabled() -> None:
    s = watchlist._parse_row(_row())
    assert s.id == "s1"
    assert s.subcategory_hints == ["news", "release"]
    assert s.enabled is True
    assert s.priority == "high"
    assert s.check_frequency == "realtime"
    assert s.notes == "memo"


@pytest.mark.parametrize("raw,expected", [("TRUE", True), ("true", True), ("1", True), ("yes", True),
                                          ("FALSE", False), ("0", False), ("", False)])
def test_parse_row_enabled_strings(raw: str, expected: bool) -> None:
    assert watchlist._parse_row(_row(enabled=raw)).enabled is expected


def test_parse_row_blank_optionals_fall_back_to_defaults() -> None:
    s = watchlist._parse_row(_row(handle="", url="", priority="", check_frequency="",
                                  language="", notes="", subcategory_hints=""))
    assert s.handle == ""
    assert s.url == ""
    assert s.priority == "medium"
    assert s.check_frequency == "6h"
    assert s.language == "ja"
    assert s.subcategory_hints == []


def test_parse_row_accepts_non_string_values_from_sheets() -> None:
    # Sheets の get_all_records は bool / list をそのまま返しうる
    r = _row()
    r_any: dict = dict(r)
    r_any["enabled"] = False
    r_any["subcategory_hints"] = ["a", "b"]
    s = watchlist._parse_row(r_any)
    assert s.enabled is False
    assert s.subcategory_hints == ["a", "b"]


# --- _load_from_csv / load ----------------------------------------------------

def test_load_from_csv_missing_file_returns_empty(tmp_path: Path) -> None:
    assert watchlist._load_from_csv(tmp_path / "nope.csv") == []


def test_load_from_csv_handles_bom(tmp_path: Path) -> None:
    p = _write_csv(tmp_path / "w.csv", [_row()])
    p.write_bytes("﻿".encode("utf-8") + p.read_bytes())
    rows = watchlist._load_from_csv(p)
    assert [r.id for r in rows] == ["s1"]


def test_load_returns_only_enabled_and_skips_sync_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _write_csv(tmp_path / "w.csv", [_row(id="on"), _row(id="off", enabled="FALSE")])
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", p)
    called: list = []
    monkeypatch.setattr(watchlist, "_sync_csv_to_sheets", lambda s: called.append(s))

    result = watchlist.load()

    assert [s.id for s in result] == ["on"]
    assert called == []  # SYNC_SHEETS_FROM_CSV 未設定なら同期しない


def test_load_syncs_all_sources_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write_csv(tmp_path / "w.csv", [_row(id="on"), _row(id="off", enabled="FALSE")])
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", p)
    monkeypatch.setenv("SYNC_SHEETS_FROM_CSV", "true")
    called: list = []
    monkeypatch.setattr(watchlist, "_sync_csv_to_sheets", lambda s: called.append(s))

    result = watchlist.load()

    assert [s.id for s in result] == ["on"]
    # 同期には無効ソースも含めた CSV 全体を渡す
    assert [[s.id for s in batch] for batch in called] == [["on", "off"]]


# --- _sync_csv_to_sheets ------------------------------------------------------

def test_sync_skips_without_credentials(fake_sheets: dict) -> None:
    watchlist._sync_csv_to_sheets([_src("a", "6h")])
    assert fake_sheets["opened"] == []
    assert fake_sheets["ws"].calls == []


def test_sync_overwrites_worksheet(fake_sheets: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS", json.dumps({"type": "service_account"}))
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-123")
    sources = [watchlist._parse_row(_row(id="a")), watchlist._parse_row(_row(id="b", enabled="FALSE"))]

    watchlist._sync_csv_to_sheets(sources)

    assert fake_sheets["creds_info"] == {"type": "service_account"}
    assert fake_sheets["opened"] == ["sheet-123"]
    assert fake_sheets["worksheet_names"] == ["watchlist"]
    calls = fake_sheets["ws"].calls
    assert calls[0] == ("clear",)
    name, args, kwargs = calls[1]
    assert name == "update" and args == ()
    assert kwargs["range_name"] == "A1"
    values = kwargs["values"]
    assert values[0] == list(WatchSource.model_fields.keys())
    header = values[0]
    assert values[1][header.index("id")] == "a"
    assert values[1][header.index("subcategory_hints")] == "news,release"
    assert values[1][header.index("enabled")] == "TRUE"
    assert values[2][header.index("enabled")] == "FALSE"


def test_sync_swallows_errors(fake_sheets: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS", json.dumps({"type": "service_account"}))
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-123")

    def boom() -> None:
        raise RuntimeError("api down")

    monkeypatch.setattr(fake_sheets["ws"], "clear", boom)
    # 例外は握りつぶされ、呼び出し側に伝播しない
    watchlist._sync_csv_to_sheets([_src("a", "6h")])
    # シートを開くところまでは進み、clear で落ちた後に update へ進んでいないこと
    assert fake_sheets["opened"] == ["sheet-123"]
    assert fake_sheets["ws"].calls == []


# --- _load_from_sheets --------------------------------------------------------

def test_load_from_sheets_parses_records(fake_sheets: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS", json.dumps({"k": "v"}))
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "sheet-9")
    fake_sheets["ws"].records = [_row(id="x"), _row(id="y", enabled="FALSE")]

    rows = watchlist._load_from_sheets()

    assert [(r.id, r.enabled) for r in rows] == [("x", True), ("y", False)]
    assert fake_sheets["opened"] == ["sheet-9"]


def test_load_from_sheets_requires_env(fake_sheets: dict) -> None:
    with pytest.raises(RuntimeError):
        watchlist._load_from_sheets()


# --- _write_local_cache / _source_to_csv_row ---------------------------------

def test_write_local_cache_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "out.csv"
    monkeypatch.setattr(watchlist, "LOCAL_CACHE", p)
    sources = [watchlist._parse_row(_row(id="a")), watchlist._parse_row(_row(id="b", enabled="FALSE"))]

    watchlist._write_local_cache(sources)

    assert watchlist._load_from_csv(p) == sources


def test_source_to_csv_row_stringifies() -> None:
    row = watchlist._source_to_csv_row(watchlist._parse_row(_row(enabled="FALSE")))
    assert row["enabled"] == "FALSE"
    assert row["subcategory_hints"] == "news,release"
    assert all(isinstance(v, str) for v in row.values())


# --- by_frequency -------------------------------------------------------------

@pytest.mark.parametrize("freq,expected", [
    ("realtime", ["rt"]),
    ("hourly", ["rt", "h"]),
    ("6h", ["rt", "h", "6"]),
    ("daily", ["rt", "h", "6", "d"]),
])
def test_by_frequency(freq: str, expected: list[str]) -> None:
    sources = [_src("rt", "realtime"), _src("h", "hourly"), _src("6", "6h"), _src("d", "daily")]
    assert [s.id for s in watchlist.by_frequency(sources, freq)] == expected
