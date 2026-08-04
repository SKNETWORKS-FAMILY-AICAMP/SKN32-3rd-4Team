# Phase 5a (GraphRAG 설계 + DB 결정) 리포트

- 작성일시: 2026-07-19 20:10
- 계획: `plans/2026-07-19_2000_Phase5a_GraphRAG설계.md`
- REQ/TEST: REQ-GRAPH-DESIGN-01, TEST-GRAPH-SCHEMA-001

## 1. DB 결정 (트레이드오프 → 확정)
사용자 지적("이미 있는 무료 PostgreSQL로 그래프 되지 않냐")을 검증 → **채택: PostgreSQL 네이티브
(노드/엣지 + 재귀 CTE)**.
- Apache AGE(Cypher 확장): Apache-2.0 무료지만 conda-forge 없음·Windows 빌드 난이도 → **설치 불가**(확인).
- Neo4j Community: 무료지만 Java 서버+~150MB 다운로드(Enterprise는 유료). Kùzu: MIT·pip 가능. → **후속 옵션**.
- **PG 네이티브**: 이미 구동 중인 무료 PG에 **pg+pgvector+그래프 통합**. 라이브 PG에서 재귀 CTE 2-hop 순회 검증.
  트레이드오프: Cypher 대신 SQL `WITH RECURSIVE`(실무 정통 기법). 필요 시 `GraphRetrieverPort`로 교체.

## 2. 설계 (실 corpus 기반 = 진짜 provenance)
- **지식그래프**: 환불교환정책.pdf 도출 정책 관계 그래프(합성 아님). 노드(reason/payer, props.period, source/locator),
  엣지(배송비부담). ADR-007: 그래프 근거를 **원천 문서+위치(locator)**로 역추적.
- **GraphRAG 흐름**: 엔티티 링크 → 재귀 CTE k-hop 순회 → 서브그래프 Evidence(원천 인용) → pgvector 근거와 결합 → LLM.
- **왜 그래프인가**(Phase 2 벡터 한계 후속): 관계 **집계**("회사 부담 사유 전부")·**비교**("사유별 기한 차이")는
  벡터 RAG가 약하고 그래프가 강함.

## 3. 검증 (스키마 PoC, 라이브 PG)
`app/adapters/pg_graph.py`(ensure_graph_schema/seed_policy_graph/reasons_by_payer/reason_periods/k_hop) +
`tests/test_pg_graph.py`(pg 마커):
- 스키마 생성 + 정책 그래프 seed(노드6·엣지4).
- **집계**: "회사가 배송비 부담하는 사유" → {상품 불량·하자, 오배송, 표시·광고와 상이} + provenance(환불교환정책.pdf, locator).
- **비교**: 사유별 기한(단순변심 7일 vs 상품불량 30일) + provenance.
- **재귀 CTE**: 단순변심 → 고객 순회. → **pg 테스트 통과**.
- CI **184**(회귀 0, 신규는 pg 마커), pg 스위트 **5**.

## 4. Codex 초점 consult
- 초안: **문제** — 그래프 Evidence에서 원천 locator 유실(ADR-007 provenance 불충족), 비교 질의 미구현.
- 반영: `reasons_by_payer`가 (사유,원천문서,**locator**) 반환, `reason_periods`(비교) 추가.
- 재확인: **설계 합격**(provenance 원천+위치 역추적, 집계·비교 둘 다 구현).

## 5. 다음 = Phase 5b (구현)
- `GraphRetrieverPort` + `PgGraphRetriever`(재귀 CTE) 어댑터, 그래프+pgvector 결합 유스케이스,
  그래프 전용 eval(집계·비교 질의셋)에서 벡터 단독 대비 개선 측정, 그래프 ingest 규칙 확장.

## 참조
- `plans/2026-07-19_2000_Phase5a_GraphRAG설계.md`, `app/adapters/pg_graph.py`, `tests/test_pg_graph.py`
