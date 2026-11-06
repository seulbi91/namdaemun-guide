# 남대문 아동복 쇼핑 가이드

남대문 아동복 상가를 돌 때 쓰는 모바일 웹 가이드(남아·여아). 빌드 없이 `index.html` 한 파일로 동작합니다.

## 주요 기능
- 카드 넘기며 매장 고르기 / 목록 / 지도 / 동선 / 정보
- **내 찜 동선**: 찜한 매장만 상가 지리 순서로 이어 시각·소요시간을 계산하고, 동선은 매장명으로 표시(매장 단위 체크). 추천 동선과 토글로 전환. 소요시간 가정은 `MINE`(이동 5분 + 매장당 8분)
- **일정 설정**: 요일(평일·토요일) + 출발 시간(09:30~) → 마감에 맞춰 동선 자동 재계산
- **시즌 자동**: 서울 시간 날짜로 겨울·봄·여름·가을 라벨과 시즌 전용 콘텐츠 선택

## 배포 (Vercel)
빌드 설정이 필요 없습니다. Framework Preset은 `Other`, Build Command·Output Directory는 비워 둡니다.
`main`에 푸시하면 자동 배포됩니다. 배포 확인: 사이트 콘솔에서
`document.querySelector('meta[name=build]').content`

## 시즌 콘텐츠 채우기
`index.html`의 `SEASON_CONTENT` 블록에서 `spring`, `summer`, `fall`을 채우면 됩니다(주석 참고).
- 미리보기: 주소 끝에 `?s=spring` (토요일 화면은 `?d=sat`)
- 빈 슬롯 점검: 콘솔에서 `seasonReport()`
- 입고 현황처럼 시점이 중요한 정보는 `until: "YYYY-MM-DD"`로 만료일을 지정하면 자동으로 숨겨집니다.

## 테스트
```bash
pip install playwright && playwright install chromium
python tests/qa_browser_test.py
```
콘솔 오류, 화면 폭별 레이아웃, 기능 흐름, 손상된 저장값, 접근성, 데이터 정합성, 시간 경계, 무작위 클릭을 점검합니다.
