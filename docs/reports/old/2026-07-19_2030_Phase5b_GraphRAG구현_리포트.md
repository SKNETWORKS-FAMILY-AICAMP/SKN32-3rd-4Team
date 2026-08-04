# Phase 5b (GraphRAG 구현: 그래프 리트리버 + 그래프+벡터 결합) 리포트

- 작성일시: 2026-07-19 20:30
- 계획: `plans/2026-07-19_2000_Phase5a_GraphRAG설계.md` (5b 예고)
- REQ/TEST: REQ-GRAPH-01/02, TEST-GRAPH-RETRIEVE-001

## 1. 구현 (우아한 재사용: 그래프도 RetrieverPort)
- `app/adapters/pg_graph_retriever.py`(`PgGraphRetriever`, RetrieverPort, backend="pg_graph"):
  정책 그래프의 관계를 **정형 사실 문장 Evidence**로 언어화(예: "상품 불량·하자 반품의 배송비는 회사가 부담한다.").
  topic 라우팅(배송비/기한 키워드) + provenance(원천문서+locator) + source 필터 준수. 연결 실패 전파(무폴백).
  → 그래프 검색이 `Evidence`를 내므로 **별도 포트 불필요** — RetrieverPort로 구현.
- `app/adapters/fusion_retriever.py`(`FusionRetriever`, RetrieverPort): N개 리트리버 결합. content 중복 제거 +
  score 내림차순(정형 그래프 사실이 상위) + cap. 하위 리트리버 오류 전파(한쪽 실패 무시 안 함).
- `app/composition.py`: `build_graph_answer_question()` = `AnswerQuestion(FusionRetriever([PgVector, PgGraph]), Llm)`
  → **기존 AnswerQuestion을 수정 없이 재사용**해 GraphRAG(그래프+벡터) 완성.

## 2. 검증
- 결정론(연결 불필요): FusionRetriever 결합·중복제거·정렬·무폴백·조립 — **4 통과**.
- pg 마커(실 PG): 그래프 리트리버 집계 사실 완전 노출·기한 라우팅·fusion 결합 — **3 통과**.
- 전체 CI **188**(회귀 0), pg 스위트 **7**.
- Codex 초점 consult 2건: graph retriever(source필터·locator), fusion(k<=0 cap) → **반영** → 재확인 통과.
  (source 빈문자열은 FaissRetriever/service의 truthy 관례와 일치시켜 유지 — 일관성.)

## 3. ★ 정직한 finding (그래프 vs 벡터, 실측)
집계질의 "회사가 반품 배송비를 부담하는 사유는?"에서:
- **벡터 단독 top-3: 3사유 정형 노출 3/3** — 이 작은 corpus에선 해당 표가 한 청크에 들어 있어 **벡터도 이미 다 회수**함.
- 그래프+벡터: 3/3, 상위 근거가 **정형 사실**("…배송비는 회사가 부담한다.")로 제공됨.

→ 정직한 결론: **이 소규모 corpus에선 그래프가 '회수(recall)'를 이기지 못한다**(둘 다 3/3). 그래프의 실제 가치는
(a) **정형·명료한 관계 사실**(원시 표 blob 대신), (b) **구성상 완전성 보장**(엣지 집계 — 청크 운에 의존 안 함),
(c) **정확한 provenance**다. 이 이점은 **그래프·corpus가 커지고 사실이 여러 청크에 흩어질수록** 커진다.
과장 없이: "그래프가 관계 질의에 구조적 이점을 주지만, 소규모에선 벡터 회수와 대등"으로 기록.

## 4. 다음
- Phase 4(Hybrid+Rerank, 뒤로 미룸) 또는 Phase 6(커머스 승인 루프). 그래프+벡터 결합의 LLM 답변 품질은
  llm 스모크로 확장 가능(현재 결정론+pg로 검색 계층 검증 완료).
- Cypher 필요 시 Neo4j/Kùzu를 `PgGraphRetriever` 자리에 교체(RetrieverPort 동일).

## 참조
- `app/adapters/pg_graph_retriever.py`, `app/adapters/fusion_retriever.py`, `app/composition.py`,
  `tests/test_fusion.py`, `tests/test_graph_retriever.py`
