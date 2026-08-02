# 데이터 매니페스트 (Phase 0 기준선)
- 작성: 2026-07-19

## RAG corpus (data/docs/)
- `loop_safety.txt` — 376 bytes
- `react_agent_overview.txt` — 332 bytes
- `tool_design_rules.txt` — 315 bytes
- `환불교환정책.pdf` — 9293 bytes

## 시드 데이터 (data/*.csv)
- `cs_inquiries.csv` — 61 행, 7173 bytes
- `inventory.csv` — 6 행, 291 bytes
- `orders.csv` — 5 행, 251 bytes
- `products.csv` — 6 행, 321 bytes

## 생성물(복제 제외, 명시 명령으로 재생성 — Phase 2 REQ-OPS-01)
- `data/mall.db` (seed_products로 생성)
- `data/vector_store/` (build_index로 생성)

## 라이선스·출처
- 전부 프로젝트 자체 생성 합성 데이터(바로봄 가상 도메인). 외부 저작물 없음.
- 향후 외부 문서 수집 시 출처·수집시각·버전·라이선스를 본 매니페스트에 추가한다(REQ-RAG-02, 후속).
