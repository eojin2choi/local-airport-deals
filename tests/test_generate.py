import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate as g  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 6, 0, tzinfo=g.KST)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))["data"]


@pytest.fixture
def rt():
    return g.parse_rows(load("pus_roundtrip.json"), TODAY)


@pytest.fixture
def ow():
    return g.parse_rows(load("pus_oneway.json"), TODAY)


@pytest.fixture
def places():
    cities = {"FUK": {"name": "후쿠오카", "country_code": "JP"}, "OSA": {"name": "오사카", "country_code": "JP"}}
    return g.Places(cities, {"JP": "일본", "KR": "대한민국"})


def test_parse_roundtrip(rt):
    assert len(rt) == 8
    f = rt[0]
    assert (f.origin, f.destination, f.depart, f.ret, f.price) == ("PUS", "CJU", date(2026, 12, 8), date(2026, 12, 15), 65402)
    assert f.transfers == 0 and f.return_transfers == 0


def test_parse_oneway(ow):
    assert len(ow) == 5
    assert all(f.ret is None and f.return_transfers is None for f in ow)


def test_parse_skips_past_and_bad_rows():
    rows = load("pus_roundtrip.json")
    later = g.parse_rows(rows, date(2026, 12, 9))  # 12/8 이전 출발은 빠짐
    assert all(f.depart >= date(2026, 12, 9) for f in later)
    assert g.parse_rows([{"origin": "PUS"}, {"price": "x"}], TODAY) == []


def test_cheapest_by_dest(rt):
    best = g.cheapest_by_dest(rt)
    assert best["CJU"].price == 65402
    assert best["FUK"].price == 249052


def test_cheapest_by_month(rt):
    m = g.cheapest_by_month(rt)
    assert list(m["FUK"]) == ["2026-11", "2027-01", "2027-03"]
    assert m["CJU"]["2026-12"].price == 65402
    assert m["CJU"]["2026-11"].price == 69171


def test_search_url_roundtrip_and_oneway(rt, ow):
    f = g.cheapest_by_dest(rt)["CJU"]
    assert g.search_url(f, "") == "https://www.aviasales.com/search/PUS0812CJU15121"
    assert g.search_url(f, "123456") == "https://www.aviasales.com/search/PUS0812CJU15121?marker=123456"
    o = g.cheapest_by_dest(ow)["FUK"]
    assert g.search_url(o, "") == "https://www.aviasales.com/search/PUS2712FUK1"


def test_stops_text(rt):
    f = rt[0]
    assert g.stops(f) == "직항"
    assert g.stops(f.__class__(**{**f.__dict__, "transfers": 1})) == "경유 (가는 편 1회 · 오는 편 0회)"


def test_origin_page_has_disclosure_and_placeholder(rt, ow, places):
    html = g.render_origin("PUS", rt, ow, places, NOW, "")
    assert "제휴 링크 안내" in html and "수수료를 받을 수 있습니다" in html
    assert "캐시 기준이며" in html and "실제와 다를 수 있습니다" in html
    assert "Travelpayouts" in html
    assert "데이터 기준 시각: 2026-11-22 06:00" in html
    assert "제휴 ID 미설정" in html
    assert "후쿠오카" in html and "제주" in html and "65,402원" in html
    assert 'rel="sponsored nofollow noopener"' in html
    assert "marker=" not in html


def test_origin_page_with_marker(rt, ow, places, monkeypatch):
    monkeypatch.delenv("TRAVELPAYOUTS_TRS", raising=False)
    html = g.render_origin("PUS", rt, ow, places, NOW, "123456")
    assert "?marker=123456" in html
    assert "제휴 ID 미설정" not in html


def test_index_page(rt, ow, places):
    html = g.render_index({"PUS": (rt, ow)}, places, NOW, "")
    assert "서울·지방 출발 항공권 특가 모음" in html
    assert "제휴 링크 안내" in html and "pus.html" in html
    assert "후쿠오카" in html  # 해외 TOP 10 에 들어감
    assert "<script>" not in html  # 필터 없는 페이지엔 스크립트 없음


def test_read_env_key_prefers_environment(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nTRAVELPAYOUTS_MARKER='777'\n", encoding="utf-8")
    monkeypatch.setattr(g, "ENV_FILES", [env])
    monkeypatch.delenv("TRAVELPAYOUTS_MARKER", raising=False)
    assert g.read_env_key("TRAVELPAYOUTS_MARKER") == "777"
    monkeypatch.setenv("TRAVELPAYOUTS_MARKER", "888")
    assert g.read_env_key("TRAVELPAYOUTS_MARKER") == "888"
    assert g.read_env_key("NOPE") == ""


def test_index_compares_seoul_and_local(places):
    f = lambda o, p: g.Fare(o, "FUK", g.date(2026, 12, 1), g.date(2026, 12, 4), p, 0, 0, "7C")
    html = g.render_index({"SEL": ([f("SEL", 150000)], []), "PUS": ([f("PUS", 120000)], [])}, places, NOW, "")
    assert "서울(인천·김포) 출발 해외 왕복 TOP 10" in html and "지방공항 출발 해외 왕복 TOP 10" in html
    assert "같은 목적지, 서울 vs 지방" in html
    assert "<strong>120,000원</strong>" in html  # 더 싼 쪽(지방)이 굵게
    assert "SEL0112FUK04121" in html and "PUS0112FUK04121" in html


def test_official_partner_link_when_project_id_set(monkeypatch):
    monkeypatch.setenv("TRAVELPAYOUTS_TRS", "605555")
    f = g.Fare("SEL", "FUK", g.date(2026, 12, 2), g.date(2027, 1, 7), 1, 0, 0, "")
    # 링크 변환 API(links/v1/create)가 11-23 실제로 돌려준 형식과 같아야 한다
    assert g.search_url(f, "809902") == (
        "https://tp.media/r?campaign_id=100&marker=809902&p=4114&trs=605555"
        "&u=https%3A%2F%2Fwww.aviasales.com%2Fsearch%2FSEL0212FUK07011"
    )
