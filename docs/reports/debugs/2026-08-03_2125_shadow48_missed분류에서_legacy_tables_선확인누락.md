# shadow48 `missed` 분류에서 기존 `pages.tables` 선확인 누락

- 시각: 2026-08-03 21:25 KST
- 위치: `scripts/eval/prepare_ocr_shadow48.py:page_category`

## 결함

기존 구현은 `tables_coords`가 비면 즉시 `missed`를 반환했다. 그러나 s5 페이지에는 좌표 후보가 없어도
PyMuPDF 기존 표 결과인 `pages[].tables`가 존재할 수 있다. 실제 첫 smoke 페이지
`6452aee156c9 p36`에도 2열 기존 표가 있었지만 `missed`로 분류됐다.

## 영향

- 최초 48문서 manifest의 `missed=16`은 “좌표 후보 없음” 층이지 “기존 표 결과 전부 없음” 층이 아니었다.
- OCR 출력과 입력 SHA는 유효하지만 기존 미탐 recall을 논하는 층화 근거로는 무효다.
- 진행 중인 원격 결과는 탐색 배치 v0로만 보존하고, 수정된 정식 manifest와 겹치는 이미지 결과만 SHA로 재사용한다.

## 수정

1. `pages.tables` 또는 `is_table=true`를 먼저 `accepted`로 판정한다.
2. 그 뒤 `tables_coords`까지 없을 때만 `missed`, 후보가 있으나 수락되지 않았으면 `withheld`로 판정한다.
3. 정식 manifest를 재생성하고 16/16/16·고유 SHA·이미지 SHA를 다시 검사한다.

