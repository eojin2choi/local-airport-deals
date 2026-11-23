# 지방공항 출발 항공권 특가 모음

김해·청주·대구·광주·제주·무안·양양 공항 출발 항공권의 목적지별 최저가(왕복·편도·월별)를 하루 한 번 모아 정적 HTML로 만든다. 예약 버튼은 Aviasales 검색 결과로 가는 Travelpayouts 제휴 링크.

## 로컬 실행

```
C:\pythoncode\데일리_루틴_자동화\.venv\Scripts\python.exe generate.py
```

- 토큰은 환경변수 `TRAVELPAYOUTS_TOKEN` → 이 폴더 `.env` → `..\데일리_루틴_자동화\.env` 순서로 찾는다.
- `TRAVELPAYOUTS_MARKER`(제휴 ID, 숫자)가 없으면 경고만 내고 마커 없는 링크로 만든다.
- 결과: `site\index.html` 과 공항별 `site\pus.html`, `cjj.html` … 브라우저로 바로 열면 된다.

## 시험

```
C:\pythoncode\데일리_루틴_자동화\.venv\Scripts\python.exe -m pytest -q tests
```

## 배포 (GitHub Pages, 무료)

이 폴더 내용을 **새 저장소의 루트**에 그대로 올린다(`.github\workflows\build.yml` 포함). Secrets 2개를 넣고 Pages 소스를 "GitHub Actions"로 바꾸면 매일 06:00(KST)에 새로 만들어 올린다. 자세한 순서는 `인계.md` 「사용자 할 일」.

## 데이터

- 가격: `GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates` (출발지만 지정, 왕복·편도 각 1회, 공항당 2회 호출). 최근 48시간 Aviasales 사용자 검색에서 찾은 캐시라 실제 가격과 다를 수 있다.
- 도시·나라 한국어 이름: `https://api.travelpayouts.com/data/ko/cities.json`, `countries.json` (토큰 불필요).
