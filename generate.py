"""지방공항 출발 항공권 최저가 정적 사이트 생성기.

Travelpayouts Data API(/aviasales/v3/prices_for_dates)에서 출발 공항별
왕복·편도 캐시 가격을 받아 목적지별 최저가를 골라 site/ 에 HTML로 쓴다.

실행: python generate.py
환경변수: TRAVELPAYOUTS_TOKEN(필수), TRAVELPAYOUTS_MARKER(선택, 제휴 ID)
"""

from __future__ import annotations

import html
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
KST = timezone(timedelta(hours=9))
API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
CITIES_URL = "https://api.travelpayouts.com/data/ko/cities.json"
COUNTRIES_URL = "https://api.travelpayouts.com/data/ko/countries.json"
# 로컬 실행 때 토큰을 찾는 .env 파일들 (환경변수가 먼저)
ENV_FILES = [HERE / ".env", HERE.parent / "데일리_루틴_자동화" / ".env"]

# 출발 공항: 도시 코드 -> 표시 이름 (페이지 파일은 코드 소문자.html)
ORIGINS = {
    "SEL": "서울(인천·김포)",  # 도시 코드라 인천·김포 출발을 함께 받는다
    "PUS": "김해(부산)",
    "CJJ": "청주",
    "TAE": "대구",
    "KWJ": "광주",
    "CJU": "제주",
    "MWX": "무안",
    "YNY": "양양",
}

# 국내 도시는 API 이름이 "부산광역시"처럼 길어서 짧게 고친다
KR_NAMES = {
    "SEL": "서울", "CJU": "제주", "PUS": "부산", "CJJ": "청주", "TAE": "대구",
    "KWJ": "광주", "MWX": "무안", "YNY": "양양", "RSU": "여수", "USN": "울산",
    "KPO": "포항", "HIN": "사천", "WJU": "원주", "KUV": "군산",
}

SEOUL = "SEL"

REGIONS = {  # 국가 코드 -> 필터 묶음
    "KR": "국내",
    "JP": "일본",
    "CN": "중화권", "HK": "중화권", "MO": "중화권", "TW": "중화권",
    "VN": "동남아", "TH": "동남아", "PH": "동남아", "MY": "동남아", "SG": "동남아",
    "ID": "동남아", "KH": "동남아", "LA": "동남아", "MM": "동남아",
}
REGION_ORDER = ["국내", "일본", "중화권", "동남아", "기타"]
WEEKDAYS = "월화수목금토일"


@dataclass(frozen=True)
class Fare:
    origin: str
    destination: str
    depart: date
    ret: date | None  # None 이면 편도
    price: int  # 원, 성인 1명
    transfers: int
    return_transfers: int | None
    airline: str


# ---------- 설정 ----------

def read_env_key(key: str) -> str:
    """환경변수 → .env 파일 순서로 key 하나만 읽는다. 값은 출력하지 않는다."""
    value = os.environ.get(key, "").strip()
    if value:
        return value
    for path in ENV_FILES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return ""


# ---------- 데이터 ----------

def parse_rows(rows: list[dict], today: date) -> list[Fare]:
    """API data 배열 → Fare 목록. 지난 날짜·잘못된 줄은 뺀다."""
    fares = []
    for r in rows:
        try:
            depart = date.fromisoformat(r["departure_at"][:10])
            ret = date.fromisoformat(r["return_at"][:10]) if r.get("return_at") else None
            price = int(r["price"])
            fare = Fare(
                origin=r["origin"],
                destination=r["destination"],
                depart=depart,
                ret=ret,
                price=price,
                transfers=int(r.get("transfers") or 0),
                return_transfers=int(r["return_transfers"]) if ret and r.get("return_transfers") is not None else None,
                airline=r.get("airline", ""),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if depart < today or price <= 0 or fare.origin == fare.destination:
            continue
        fares.append(fare)
    return fares


def cheapest_by_dest(fares: list[Fare]) -> dict[str, Fare]:
    best: dict[str, Fare] = {}
    for f in fares:
        if f.destination not in best or (f.price, f.depart) < (best[f.destination].price, best[f.destination].depart):
            best[f.destination] = f
    return best


def cheapest_by_month(fares: list[Fare]) -> dict[str, dict[str, Fare]]:
    """목적지 -> {"2026-12": 그 달 출발 최저가}. 달 순서로 정렬."""
    out: dict[str, dict[str, Fare]] = {}
    for f in fares:
        month = f.depart.strftime("%Y-%m")
        cur = out.setdefault(f.destination, {}).get(month)
        if cur is None or (f.price, f.depart) < (cur.price, cur.depart):
            out[f.destination][month] = f
    return {d: dict(sorted(m.items())) for d, m in out.items()}


def fetch_fares(origin: str, one_way: bool, token: str, today: date) -> list[Fare]:
    params = {
        "origin": origin,
        "currency": "krw",
        "one_way": "true" if one_way else "false",
        "sorting": "price",
        "limit": 1000,
    }
    r = requests.get(API, params=params, headers={"X-Access-Token": token}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict) or not body.get("success"):
        raise RuntimeError(f"API 실패: {origin} one_way={one_way}")
    fares = parse_rows(body.get("data") or [], today)
    # 왕복 요청인데 귀국일이 없는 줄은 왕복으로 쓸 수 없다(화면에서 귀국일을 그리다 멈춤)
    return fares if one_way else [f for f in fares if f.ret is not None]


def fetch_places() -> tuple[dict[str, dict], dict[str, str]]:
    """도시(코드 -> {name, country_code})와 국가(코드 -> 이름) 한국어 목록. 토큰 불필요."""
    try:
        cities = {c["code"]: c for c in requests.get(CITIES_URL, timeout=60).json()}
        countries = {c["code"]: c["name"] for c in requests.get(COUNTRIES_URL, timeout=60).json()}
        return cities, countries
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"[경고] 도시 이름 목록을 못 받음({type(e).__name__}). 코드로 표시합니다.", file=sys.stderr)
        return {}, {}


# ---------- 링크 ----------

def search_url(f: Fare, marker: str) -> str:
    """Aviasales 검색 결과 링크. 형식: /search/{출발}{DDMM}{도착}[{DDMM}]{성인수}."""
    params = f"{f.origin}{f.depart:%d%m}{f.destination}{f.ret:%d%m}1" if f.ret else f"{f.origin}{f.depart:%d%m}{f.destination}1"
    url = f"https://www.aviasales.com/search/{params}"
    return f"{url}?marker={marker}" if marker else url


# ---------- 표시 ----------

def won(n: int) -> str:
    return f"{n:,}원"


def day(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def stops(f: Fare) -> str:
    if f.ret is None:
        return "직항" if f.transfers == 0 else f"경유 {f.transfers}회"
    back = f.return_transfers or 0
    if f.transfers == 0 and back == 0:
        return "직항"
    return f"경유 (가는 편 {f.transfers}회 · 오는 편 {back}회)"


class Places:
    def __init__(self, cities: dict[str, dict], countries: dict[str, str]):
        self.cities = cities
        self.countries = countries

    def country(self, code: str) -> str:
        if code in KR_NAMES:
            return "KR"
        return (self.cities.get(code) or {}).get("country_code") or ""

    def name(self, code: str) -> str:
        if code in KR_NAMES:
            return KR_NAMES[code]
        return (self.cities.get(code) or {}).get("name") or code

    def country_name(self, code: str) -> str:
        return self.countries.get(self.country(code), "")

    def region(self, code: str) -> str:
        return REGIONS.get(self.country(code), "기타")


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1b1f24;--muted:#5f6b7a;--line:#e3e6ea;--accent:#0a66c2;--warn:#fff6db;--warnline:#f0d98a}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1c1f24;--ink:#e8eaed;--muted:#9aa4b1;--line:#2c3138;--accent:#5aa9ff;--warn:#2e2a1a;--warnline:#6b5a22}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2em 0}h2{font-size:1.1rem;margin:1.4em 0 .5em}
a{color:var(--accent)}.muted{color:var(--muted);font-size:.85rem}
.notice{background:var(--warn);border:1px solid var(--warnline);border-radius:8px;padding:10px 12px;font-size:.85rem;margin:10px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.city{font-weight:700;font-size:1.05rem}.price{font-weight:700;font-size:1.1rem}
.fare{border-top:1px dashed var(--line);padding-top:8px;margin-top:8px}
.btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;border-radius:6px;padding:6px 12px;font-size:.9rem;white-space:nowrap}
.tag{display:inline-block;font-size:.75rem;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-left:4px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.filters button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:16px;padding:4px 12px;font-size:.85rem}
.filters button[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
details summary{cursor:pointer;color:var(--muted);font-size:.85rem;margin-top:6px}
table{width:100%;border-collapse:collapse;font-size:.85rem}td{padding:4px 2px;border-top:1px solid var(--line)}td.r{text-align:right}
nav a{margin-right:10px;white-space:nowrap}footer{margin:24px 0 8px;font-size:.8rem;color:var(--muted)}
"""

FILTER_JS = """
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{
document.querySelectorAll('.filters button').forEach(x=>x.setAttribute('aria-pressed',x===b));
const r=b.dataset.region;document.querySelectorAll('.card[data-region]').forEach(c=>{c.hidden=r!=='전체'&&c.dataset.region!==r})}));
"""


def e(s: object) -> str:
    return html.escape(str(s))


def disclosure() -> str:
    return (
        '<p class="notice"><strong>제휴 링크 안내</strong> · 이 페이지의 「항공권 보기」 버튼은 '
        "Travelpayouts 제휴(파트너) 링크입니다. 이 링크를 통해 예약하면 운영자가 수수료를 받을 수 있습니다. "
        "가격은 최근 검색 결과를 모은 캐시 기준이며, 실제 예약 가격·좌석과 다를 수 있습니다. "
        "예약 전에 이동한 사이트에서 최종 가격을 꼭 확인하세요.</p>"
    )


def page(title: str, description: str, body: str, generated: datetime, marker: str) -> str:
    marker_note = "" if marker else (
        '\n<p class="muted"><!-- TRAVELPAYOUTS_MARKER 미설정 -->[제휴 ID 미설정: 링크에 수수료 추적이 붙지 않은 테스트 빌드]</p>'
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<style>{CSS}</style></head>
<body><main>
<nav class="muted"><a href="index.html">전체 공항</a>{''.join(f'<a href="{c.lower()}.html">{e(n)}</a>' for c, n in ORIGINS.items())}</nav>
{body}
<footer>
<p>데이터 기준 시각: {generated:%Y-%m-%d %H:%M} (한국 시간) · 하루 한 번 갱신</p>
<p>가격 데이터: Travelpayouts / Aviasales Data API (최근 사용자 검색에서 찾은 가격 캐시). 성인 1명, 일반석, 원화 기준. 가격은 캐시 기준이며 실제와 다를 수 있습니다.</p>
<p>이 사이트의 일부 링크는 제휴 링크이며 운영자가 수수료를 받을 수 있습니다(공정거래위원회 「추천·보증 등에 관한 표시·광고 심사지침」에 따른 표시). 이 사이트는 개인정보를 수집하지 않고 쿠키·방문 분석 도구를 쓰지 않습니다.</p>{marker_note}
</footer>
</main>{'<script>' + FILTER_JS + '</script>' if 'class="filters"' in body else ''}</body></html>
"""


def fare_line(label: str, f: Fare, marker: str) -> str:
    dates = f"{day(f.depart)} → {day(f.ret)}" if f.ret else f"{day(f.depart)} 출발"
    return (
        f'<div class="fare row"><div><span class="muted">{label}</span> <span class="price">{won(f.price)}</span>'
        f'<br><span class="muted">{dates} · {stops(f)}</span></div>'
        f'<a class="btn" href="{e(search_url(f, marker))}" rel="sponsored nofollow noopener" target="_blank">항공권 보기<span class="tag" style="color:#fff;border-color:#fff8">제휴</span></a></div>'
    )


def render_origin(code: str, rt: list[Fare], ow: list[Fare], places: Places, generated: datetime, marker: str) -> str:
    name = ORIGINS[code]
    best_rt, best_ow = cheapest_by_dest(rt), cheapest_by_dest(ow)
    months = cheapest_by_month(rt)
    dests = sorted(set(best_rt) | set(best_ow), key=lambda d: (best_rt.get(d) or best_ow[d]).price)
    present = [r for r in REGION_ORDER if any(places.region(d) == r for d in dests)]
    filters = '<div class="filters">' + "".join(
        f'<button type="button" data-region="{r}" aria-pressed="{str(r == "전체").lower()}">{r}</button>'
        for r in ["전체", *present]
    ) + "</div>"
    cards = []
    for d in dests:
        parts = []
        if d in best_rt:
            parts.append(fare_line("왕복 최저", best_rt[d], marker))
        if d in best_ow:
            parts.append(fare_line("편도 최저", best_ow[d], marker))
        month_rows = months.get(d, {})
        if len(month_rows) > 1:
            trs = "".join(
                f'<tr><td>{m[:4]}년 {int(m[5:])}월</td><td>{day(f.depart)} → {day(f.ret)}</td>'
                f'<td class="r">{won(f.price)}</td><td class="r"><a href="{e(search_url(f, marker))}" rel="sponsored nofollow noopener" target="_blank">보기</a></td></tr>'
                for m, f in month_rows.items()
            )
            parts.append(f"<details><summary>월별 왕복 최저가 ({len(month_rows)}개월)</summary><table>{trs}</table></details>")
        cards.append(
            f'<div class="card" data-region="{places.region(d)}"><div class="city">{e(places.name(d))}'
            f'<span class="tag">{e(places.country_name(d) or places.region(d))}</span><span class="tag">{e(d)}</span></div>{"".join(parts)}</div>'
        )
    body = (
        f"<h1>{e(name)} 출발 항공권 최저가</h1>"
        f'<p class="muted">{e(name)} 공항({code})에서 출발하는 목적지별 가장 싼 왕복·편도 항공권. 목적지 {len(dests)}곳, 싼 순서.</p>'
        + disclosure()
        + (filters + "".join(cards) if dests else "<p>지금 캐시에 이 공항 출발 가격이 없습니다. 내일 다시 확인해 주세요.</p>")
    )
    return page(
        f"{name} 출발 항공권 최저가 모음",
        f"{name}공항 출발 일본·중국·동남아·제주 왕복/편도 최저가를 하루 한 번 모아 보여 줍니다.",
        body, generated, marker,
    )


def render_index(data: dict[str, tuple[list[Fare], list[Fare]]], places: Places, generated: datetime, marker: str) -> str:
    cards = []
    intl: list[tuple[str, Fare]] = []
    for code, name in ORIGINS.items():
        rt, ow = data.get(code, ([], []))
        best = cheapest_by_dest(rt)
        n_dest = len(set(best) | set(cheapest_by_dest(ow)))
        abroad = sorted((f for d, f in best.items() if places.region(d) != "국내"), key=lambda f: f.price)
        intl += [(code, f) for f in abroad]
        top = "".join(
            f'<li>{e(places.name(f.destination))} 왕복 <strong>{won(f.price)}</strong> <span class="muted">{day(f.depart)}~</span></li>'
            for f in abroad[:3]
        ) or '<li class="muted">해외 왕복 가격 없음</li>'
        cards.append(
            f'<div class="card"><div class="row"><span class="city">{e(name)} 출발</span>'
            f'<a class="btn" href="{code.lower()}.html">목적지 {n_dest}곳 보기</a></div><ul>{top}</ul></div>'
        )
    def top_table(rows: list[tuple[str, Fare]]) -> str:
        rows = sorted(rows, key=lambda x: x[1].price)[:10]
        trs = "".join(
            f'<tr><td>{e(ORIGINS[c])} → {e(places.name(f.destination))}</td><td>{day(f.depart)} → {day(f.ret)}</td>'
            f'<td class="r"><strong>{won(f.price)}</strong></td><td class="r"><a href="{e(search_url(f, marker))}" rel="sponsored nofollow noopener" target="_blank">보기</a></td></tr>'
            for c, f in rows
        )
        return f'<div class="card"><table>{trs}</table></div>' if trs else ""

    seoul_top = top_table([x for x in intl if x[0] == SEOUL])
    local_top = top_table([x for x in intl if x[0] != SEOUL])

    # 같은 해외 목적지를 서울 출발과 지방 출발(가장 싼 공항) 가격으로 나란히 비교
    seoul_best = {f.destination: f for c, f in intl if c == SEOUL}
    local_best: dict[str, tuple[str, Fare]] = {}
    for c, f in intl:
        if c != SEOUL and (f.destination not in local_best or f.price < local_best[f.destination][1].price):
            local_best[f.destination] = (c, f)
    both = sorted(set(seoul_best) & set(local_best), key=lambda d: seoul_best[d].price)[:15]

    def cell(c: str, f: Fare, cheaper: bool) -> str:
        price = f"<strong>{won(f.price)}</strong>" if cheaper else won(f.price)
        return (f'<td class="r">{price}<br><a class="muted" href="{e(search_url(f, marker))}" rel="sponsored nofollow noopener" '
                f'target="_blank">{e(ORIGINS[c])} 출발 보기</a></td>')

    compare = "".join(
        f"<tr><td>{e(places.name(d))}</td>"
        + cell(SEOUL, seoul_best[d], seoul_best[d].price <= local_best[d][1].price)
        + cell(*local_best[d], local_best[d][1].price < seoul_best[d].price) + "</tr>"
        for d in both
    )
    body = (
        "<h1>서울·지방 출발 항공권 특가 모음</h1>"
        '<p class="muted">인천·김포와 김해·청주·대구·광주·제주·무안·양양에서 출발하는 해외·국내 항공권 최저가를 공항별로 하루 한 번 모읍니다. 같은 목적지를 서울 출발과 지방 출발로 나란히 비교해 보세요.</p>'
        + disclosure()
        + (f"<h2>서울(인천·김포) 출발 해외 왕복 TOP 10</h2>{seoul_top}" if seoul_top else "")
        + (f"<h2>지방공항 출발 해외 왕복 TOP 10</h2>{local_top}" if local_top else "")
        + (f'<h2>같은 목적지, 서울 vs 지방</h2><div class="card"><table><tr><td class="muted">목적지</td><td class="r muted">서울 출발</td>'
           f'<td class="r muted">지방 출발 최저</td></tr>{compare}</table></div>' if compare else "")
        + "<h2>출발 공항 고르기</h2>" + "".join(cards)
    )
    return page(
        "서울·지방 출발 항공권 특가 모음 | 인천·김포·김해·청주·대구 출발 최저가",
        "인천·김포와 김해·청주·대구·광주·제주·무안·양양 공항 출발 해외·국내 항공권 최저가를 공항별로 모아 하루 한 번 갱신하고, 같은 목적지를 서울 출발과 지방 출발로 비교합니다.",
        body, generated, marker,
    )


# ---------- 실행 ----------

def main() -> int:
    token = read_env_key("TRAVELPAYOUTS_TOKEN")
    if not token:
        print("[오류] TRAVELPAYOUTS_TOKEN 이 없습니다(환경변수 또는 .env).", file=sys.stderr)
        return 1
    marker = read_env_key("TRAVELPAYOUTS_MARKER")
    if not marker:
        print("[경고] TRAVELPAYOUTS_MARKER 미설정: 링크는 작동하지만 수수료가 추적되지 않습니다.", file=sys.stderr)
    elif not marker.isdigit():
        print("[오류] TRAVELPAYOUTS_MARKER 는 숫자 제휴 ID여야 합니다.", file=sys.stderr)
        return 1

    generated = datetime.now(KST)
    today = generated.date()
    places = Places(*fetch_places())
    data: dict[str, tuple[list[Fare], list[Fare]]] = {}
    for code in ORIGINS:
        pair = []
        for one_way in (False, True):   # 왕복·편도를 따로 받아 한쪽 실패가 다른 쪽을 버리지 않게
            try:
                pair.append(fetch_fares(code, one_way, token, today))
            except (requests.RequestException, RuntimeError, ValueError) as err:
                # 예외 문구에 토큰이 들어가지 않는다(토큰은 헤더로만 보냄)
                print(f"[경고] {code} {'편도' if one_way else '왕복'} 가격을 못 받음: {type(err).__name__}", file=sys.stderr)
                pair.append([])
        data[code] = (pair[0], pair[1])
    if not any(rt or ow for rt, ow in data.values()):
        print("[오류] 받은 가격이 하나도 없습니다. 사이트를 만들지 않습니다.", file=sys.stderr)
        return 1

    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(render_index(data, places, generated, marker), encoding="utf-8")
    for code in ORIGINS:
        rt, ow = data.get(code, ([], []))
        (SITE / f"{code.lower()}.html").write_text(render_origin(code, rt, ow, places, generated, marker), encoding="utf-8")
        n_dest = len(set(cheapest_by_dest(rt)) | set(cheapest_by_dest(ow)))
        print(f"{code} {ORIGINS[code]}: 왕복 {len(rt)}줄, 편도 {len(ow)}줄, 목적지 {n_dest}곳")
    print(f"완료: {SITE} ({generated:%Y-%m-%d %H:%M} KST)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
