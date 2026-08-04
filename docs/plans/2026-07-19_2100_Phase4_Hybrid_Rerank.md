---
document_type: phase_plan
phase: 4
created_at: "2026-07-19"
parent: "plans/2026-07-19_1600_v3.2_학습중심_개정.md"
status: proposed
---

# Phase 4 — Hybrid 검색(dense+lexical, RRF) + Rerank

## 목표
pgvector(dense) 위에 **PG 키워드 검색(pg_trgm word_similarity)**을 얹어 **RRF**로 결합(하이브리드),
그 위에 **Reranker**를 올린다. 모두 같은 `RetrieverPort`로 구현해 교체·비교 가능.

## 설계 (같은 포트, 결합·비교)
- `PgLexicalRetriever`(RetrieverPort, backend="pg_lexical"): `pg_trgm` `word_similarity(query, content)`로
  랭킹(임계 없이 top-k) → Evidence(score=word_similarity∈[0,1]). 한국어 형태소분석기 없이 동작(검증됨).
- `HybridRetriever`(RetrieverPort, backend="hybrid"): dense(pgvector)+lexical 랭킹을 **RRF**(1/(k+rank) 합)로 결합.
  문서 identity=content. RRF score 정규화. 무폴백: 하위 실패 전파.
- `RerankerPort` + `LlmReranker`: (query, 후보 Evidence)→관련도 재점수·재정렬(LLM-as-reranker, 다운로드 없음).
  `RerankedRetriever`(RetrieverPort): base 검색(over-fetch) → rerank → top-k. deterministic FakeReranker로 결정론 검증.
- 인프라: `ensure_schema`에 `CREATE EXTENSION pg_trgm` + GIN trigram 인덱스 추가.

## DoD / 검증
| ID | 검증 |
|---|---|
| TEST-RAG-HYBRID-001 (pg) | 하이브리드가 dense·lexical 근거를 RRF로 결합, rag_v1 Hit@3 측정 |
| TEST-RAG-RERANK-001 | 결정론: RRF 로직 + RerankedRetriever가 reranker 점수로 재정렬(Fake) |
| REQ-RAG-03 | 하이브리드 결합이 단일 대비 정합(소규모 corpus에선 개선 미미 예상 — 정직 기록) |
| REQ-RAG-RERANK-01 | rerank 단계가 후보를 재정렬(결정론) + LLM reranker(llm 마커) |
| 회귀 | 결정론 188 유지 |

## 정직 주의(Phase 2·3 finding 연장)
- 소규모 corpus(8청크)에선 dense가 이미 Hit@3=1.0 → 하이브리드·rerank의 **지표 개선이 미미**할 수 있다.
  과장 없이 "기법 구현·작동 검증 + 규모에서의 이점"으로 기록(측정값 그대로).

## 완료 후
- Codex 초점 consult(RRF·무폴백·rerank) → 리포트 → Phase 6(커머스 승인).
