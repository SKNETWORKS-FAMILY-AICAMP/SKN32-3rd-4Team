# Phase 4 (Hybrid 검색 + Reranker) 리포트

- 작성일시: 2026-07-19 21:30
- 계획: `plans/2026-07-19_2100_Phase4_Hybrid_Rerank.md`
- REQ/TEST: REQ-RAG-HYBRID-01, REQ-RAG-RERANK-01, TEST-RAG-HYBRID-001(pg), TEST-RAG-RERANK-001

## 1. 구현 (모두 같은 RetrieverPort — 조합 가능)
- `app/adapters/pg_lexical_retriever.py`(`PgLexicalRetriever`, backend="pg_lexical"):
  한국어 형태소분석기 없이 `word_similarity(query, content)`로 랭킹(임계 없이 top-k).
  → hybrid의 **sparse(키워드) 측**. dense(pgvector)와 동일 포트라 그대로 결합된다.
- `app/adapters/pgvector_index.py` `ensure_schema`: `pg_trgm` 확장 + GIN 트라이그램 인덱스
  (`rag_chunks_content_trgm ... using gin (content gin_trgm_ops)`) idempotent 추가.
- `app/adapters/hybrid_retriever.py`(`HybridRetriever`, backend="hybrid"):
  dense+lexical 랭킹을 **RRF(Reciprocal Rank Fusion)** `score += 1/(rrf_k+rank)`로 결합.
  RRF를 [0,1] 정규화(최상위=1)해 Evidence.score 계약 유지. 하위 리트리버 오류 전파(무폴백).
- `app/adapters/reranker.py`:
  - `RerankerPort`(ports.py): `rerank(query, evidence, top_n) -> list[Evidence]`.
  - `LlmReranker`: **LLM-as-reranker**(다운로드 없음) — 후보별 관련도 0~10을 LLM에 물어 재정렬.
    점수를 [0,1]로 정규화해 Evidence.score에 반영(순위=score 내림차순 일치).
  - `RerankedRetriever`(RetrieverPort, backend="reranked"): base로 over-fetch 후 reranker로 top-k.
- `app/composition.py` `build_hybrid_answer_question(rerank=False)`: Hybrid(+선택적 Rerank)를
  **기존 AnswerQuestion 수정 없이** 주입.

## 2. 검증
- 결정론(연결 불필요, `tests/test_hybrid.py`): RRF 결합·정규화, retriever/rrf_k 검증,
  reranker 정렬·정규화 score·범위/모호출력 거부(LLMOutputError)·over-fetch≥k·retriever내 중복투표 차단 — **12 통과**.
- pg 마커(실 PG, `tests/test_hybrid_pg.py`): lexical word_similarity 랭킹·source 필터, hybrid Hit@3 — **3 통과**.
- 전체 CI **201**(회귀 0), pg 스위트 **10**(pgvector 4 + graph 3 + hybrid 3).
- Codex 정적 consult **3라운드**: 최초 7건 지적 → 판정 → 수정 → 재확인 → **FINAL: OK**.

### Codex 지적 처리 (정직)
반영(6): (a) reranker 점수 [0,1] 정규화로 순위=score 일치, (b) 0~10 범위 밖 점수 거부,
(c) 응답 strip 후 `^숫자(.소수)?(점|/10)?$` fullmatch — `8 and 20`·`1e2` 모호출력 거부,
(d) Hybrid/Reranked가 `k>over_fetch`면 `max(over_fetch,k)`로 조회(누락 방지),
(e) `rrf_k<=0` 거부(0나눗셈·정규화 붕괴 방지), (f) 한 retriever 내 동일 content 중복 RRF 투표 차단.
유지(3, 기존 컨벤션과 일관): `k<=0`→무제한(FusionRetriever와 동일 문서화 관례),
page 비정수→None·NULL source→""(faiss `_locator`/`get("source","")`와 동일 방어),
content 기준 병합(FusionRetriever dedup과 동일 식별자 관례).

### 부수 수정 (Phase 3 잔여 가드레일 위반)
`test_llm_reg_002_no_hardcoded_model_ids_in_new_code`가 `pgvector_index.py` **주석**의
`ko-sroberta`를 하드코딩 모델ID로 탐지(Phase 3 커밋에 잔존, 당시 미검출). 다른 어댑터는
주석에서도 모델을 명명하지 않고 레지스트리에 위임 — 컨벤션에 맞춰 주석을 레지스트리 중립으로
수정(가드레일 약화 없이 위반 제거).

## 3. ★ 정직한 finding (Hybrid/Rerank 실측)
`rag_v1`(8청크 corpus) Hit@3:

| retriever | Hit@3 |
|---|---|
| faiss | 1.000 (22/22) |
| pgvector | 1.000 (22/22) |
| **lexical(pg_trgm)** | **1.000 (22/22)** |
| **hybrid(RRF)** | **1.000 (22/22)** |

→ 정직한 결론: **이 소규모 corpus에선 lexical 단독조차 Hit@3=1.0** — dense가 이미 천장이라
hybrid가 **회수(recall)에서 이길 여지가 없다**(모두 1.0). 이는 Phase 3/5b와 동일한 천장 효과다.
Hybrid/Rerank의 실제 가치는:
(a) **어휘 불일치 보강**(임베딩이 놓치는 정확한 키워드/희귀어를 lexical이, 반대로 dense가 의미를 보강),
(b) **랭킹 품질**(reranker가 top-k 정밀도를 올림 — 회수가 아니라 순서),
(c) **규모 견고성**(corpus·질의 다양성이 커질수록 단일 신호의 실패를 상호 보완).
과장 없이: "소규모에선 단일 검색과 대등, 구조적 이점은 규모·다양성에서 발현"으로 기록.
(reranker 품질은 실 LLM 스모크로 확장 가능 — 현재는 결정론으로 재정렬 로직·무폴백 계약을 검증.)

## 4. 다음
- v3.2 순서: Phase 6(커머스 승인 루프) → 7(에이전트+CoT) → 8(MCP 통합) → 9(관리자·역할) → 10(안정화·시연).
- 실 크로스인코더 reranker(bge-reranker 등)로 교체 시 `RerankedRetriever`의 reranker 자리에 주입(RerankerPort 동일).

## 참조
- `app/adapters/pg_lexical_retriever.py`, `app/adapters/hybrid_retriever.py`, `app/adapters/reranker.py`,
  `app/application/ports.py`(RerankerPort), `app/adapters/pgvector_index.py`(pg_trgm), `app/composition.py`,
  `tests/test_hybrid.py`, `tests/test_hybrid_pg.py`
