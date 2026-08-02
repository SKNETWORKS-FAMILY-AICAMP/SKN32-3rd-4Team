---
document_type: phase_plan
phase: 5a
created_at: "2026-07-19"
parent: "plans/2026-07-19_1600_v3.2_학습중심_개정.md"
status: proposed
---

# Phase 5a — GraphRAG 설계 + DB 결정

## 1. DB 결정 (트레이드오프, 확정)
| 후보 | 라이선스 | 이 머신 | 결정 |
|---|---|---|---|
| Apache AGE (PG용 Cypher 그래프 확장) | Apache-2.0(무료) | conda-forge 없음·Windows 빌드 난이도 → **설치 불가**(확인함) | ✗ |
| Neo4j Community | 무료(GPLv3) | Java21 있음, 단 서버+~150MB 다운로드; Enterprise는 유료 | 후속 옵션 |
| Kùzu(임베디드, MIT) | 무료 | pip 설치 가능 | 후속 옵션 |
| **PostgreSQL 네이티브(노드/엣지 + 재귀 CTE)** | **무료** | **이미 구동 중(pgvector와 동일 DB)** | ✅ **채택** |

**결정 사유**: 이미 띄운 무료 PG에 **pg + pgvector + 그래프를 통합**한다. 재귀 CTE 그래프 순회는 라이브 PG에서
검증됨(2-hop 순회 확인). 트레이드오프: Cypher 대신 SQL `WITH RECURSIVE`(실무 정통 기법, 학습가치 충분).
AGE/Neo4j/Kùzu는 필요 시 후속(포트 `GraphRetrieverPort`로 교체 가능하게 설계).

## 2. 지식그래프 설계 (실 corpus 기반 = 진짜 provenance)
**대상: 환불·교환·반품 정책 관계 그래프**(환불교환정책.pdf에서 도출 — 합성 아님, ADR-007 provenance 충족).

### 스키마
```sql
CREATE TABLE graph_nodes (
  id bigserial PRIMARY KEY,
  node_key text UNIQUE NOT NULL,   -- '반품사유:단순변심'
  node_type text NOT NULL,         -- reason | payer | period
  name text NOT NULL,
  props jsonb DEFAULT '{}',        -- {period:'7일'} 등
  source text, locator text,       -- 원천 문서 provenance(문서명/페이지)
  synthetic boolean DEFAULT false
);
CREATE TABLE graph_edges (
  id bigserial PRIMARY KEY,
  src_key text NOT NULL, dst_key text NOT NULL,
  rel text NOT NULL,               -- 배송비부담 | 기한 | 속함
  props jsonb DEFAULT '{}',
  source text                      -- 원천 문서 provenance
);
```

### 인스턴스(정책에서 도출, provenance=환불교환정책.pdf)
- reason 노드: 단순변심(props.period=7일), 상품불량(30일), 오배송(30일), 표시광고상이(3개월/30일)
- payer 노드: 고객, 회사
- edges(배송비부담): 단순변심→고객, 상품불량→회사, 오배송→회사, 표시광고상이→회사

## 3. GraphRAG 검색 흐름
```
질문 → 엔티티 링크(질문 토큰↔node name, 단순 매칭 — 엔티티링크는 별도 난제라 최소화·문서화)
    → 재귀 CTE k-hop 순회(seed 노드에서 서브그래프)
    → 서브그래프 사실 → Evidence(content='A 배송비부담 회사', source=원천문서, score=1.0)
    → **pgvector 근거와 결합**(벡터 RAG 보완)
    → LLM 답변(근거는 그래프 경로가 아니라 원천 문서 인용 — ADR-007)
```

### 왜 그래프인가 (벡터 RAG 한계 보완 — Phase 2 finding 후속)
- **집계 질의**: "회사가 반품 배송비를 부담하는 사유는?" → 엣지 배송비부담→회사인 reason 전부(불량·오배송·표시광고상이).
  벡터 RAG는 청크를 검색할 뿐 이런 **관계 집계**를 못한다. 그래프는 한 쿼리로 정확히 답한다.
- **비교 질의**: "단순변심과 상품불량의 반품 기한 차이는?" → 두 노드 props.period 비교.

## 4. DoD (Phase 5a)
| ID | 검증 |
|---|---|
| TEST-GRAPH-SCHEMA-001 | 스키마 생성 + 정책 그래프 seed + 재귀 CTE 집계/비교 질의 2건이 정답 반환(라이브 PG PoC) |
| REQ-GRAPH-DESIGN-01 | 설계 문서 + DB 트레이드오프 + 사용자 합의(본 문서) |

## 5. Phase 5b 예고(구현)
- `GraphStorePort`/`GraphRetrieverPort` + `PgGraphRetriever`(재귀 CTE) 어댑터.
- 그래프 ingest(정책 도출 규칙), 그래프+pgvector 결합 유스케이스(`AnswerQuestion` 확장 또는 신규),
  그래프 전용 eval(집계·비교 질의셋)에서 벡터 단독 대비 개선 측정.

## 완료 후
- 스키마 PoC 검증 → Codex 초점 consult(설계·provenance·무폴백) → 합의 → 리포트 → Phase 5b.
