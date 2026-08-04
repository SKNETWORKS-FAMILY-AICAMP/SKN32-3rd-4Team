# 데이터 매니페스트 (Phase 0 역사 기준선)
- 최초 작성: 2026-07-19
- 현행화: 2026-08-04
- 현행 보험 데이터 정본: `docs/handoff/01_데이터_현황.md`

> 아래 목록은 커머스 실습 당시의 역사 기준선이며 현행 파일 목록으로 사용하지 않는다.
> 커머스 시드 CSV는 현재 활성 `data/`에 없고 `legacy/v3_commerce.zip`에만 보존한다.
> 보험 애플리케이션의 DB 준비 과정은 이 CSV들을 요구하지 않는다. 구형 RAG corpus와 FAISS
> `ingest`의 격리는 별도 작업으로 남아 있다.

## Phase 0 RAG corpus (역사 경로)
- `loop_safety.txt` — 376 bytes (현재 활성 경로에 없음)
- `react_agent_overview.txt` — 332 bytes (현재 활성 경로에 없음)
- `tool_design_rules.txt` — 315 bytes (현재 활성 경로에 없음)
- `환불교환정책.pdf` — 9293 bytes (구형 FAISS 격리 전까지 `data/docs/`에 남음)

## 레거시 시드 데이터 (보관 위치: legacy/v3_commerce.zip)
- `cs_inquiries.csv` — 61 행, 7173 bytes
- `inventory.csv` — 6 행, 312 bytes
- `orders.csv` — 5 행, 268 bytes
- `products.csv` — 6 행, 342 bytes

## 현행 생성물(복제 제외, 명시 명령으로 재생성)
- `data/db/insurance.sqlite3` (애플리케이션의 기본 로컬 SQLite DB)
- `data/vector_store/` (build_index로 생성)

## 라이선스·출처
- 위 레거시 자료는 프로젝트 자체 생성 합성 데이터(커머스 실습 가상 도메인)다.
- 현행 보험 약관의 출처·수집시각·해시·격리 상태는 보험 데이터 정본과 전처리 manifest에서 관리한다.
