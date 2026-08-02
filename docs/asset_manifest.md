# 자산 매니페스트 (Phase 0 기준선 → v3.1 계층 목표)

- 작성: 2026-07-19
- 출처: `../_unified_mall_agent_project` 무변경 복제. v3.1 §3 Strangler 매핑 기준.

| 모듈 | 현재 성격 | v3.1 목표 계층 | 전환 Phase |
|---|---|---|---|
| `app/db/{models,database,seed}.py` | SQLAlchemy+SQLite | Adapter/persistence | 3, 6 |
| `app/services/order_service.py` | 정책+ORM 혼합 | Application(`Prepare/ApproveOrder`)+legacy | 3 |
| `app/services/payment_service.py` | 샌드박스 결제 | Application | 3 |
| `app/services/user_service.py` | 인증 CRUD | Application | 6 |
| `app/tools/commerce_tools.py` | DB쿼리+Tool 계약 | Interface adapter(legacy wrapper) | 3, 5 |
| `app/agent/react.py` | 도구 루프(주 에이전트) | Application 경계 strangler | 4 |
| `app/agent/{lc_agent,lc_tools}.py` | 2번째 에이전트 | **lab/legacy(운영 제외)** | 4 |
| `app/agent/planning.py` | 미사용 | lab/후속 | — |
| `app/rag/{build_index,embeddings}.py` | ingest·FAISS 빌드 | Adapter/retrieval(`IndexBuilder`) | 1, 2 |
| `app/rag/service.py` | FAISS 검색 | Adapter(`RetrieverPort`) | 1 |
| `app/rag/qa.py` | 검색+프롬프트+LLM | Application(`AnswerQuestion`) | 1 |
| `app/core/llm_clients.py` | provider factory | Adapter(`ModelGateway`)+composition root | 1 |
| `app/core/config.py` | 설정(모델ID 하드코딩) | config + `model_registry.yaml` | 1 |
| `app/mcp/{server,client}.py` | stdio MCP | Interface(use case 호출) | 5 |
| `app/workflow/rules.py` | 순수 규칙 | Domain | 유지 |
| `app/workflow/ticket_graph.py` | LangGraph | Adapter orchestration(티켓만) | 유지 |
| `app/ml/*` | 의도·감성·추천 | Adapter/ML(의도·추천), 감성 lab | 필요시 |
| `app/auth/security.py` | JWT+Depends | Interface/Auth(역할정책은 App/Domain) | 6 |
| `app/routers/*`, `app/schemas/*` | HTTP·Pydantic | Interface(use case만 호출) | 1,3,5,6 |
| `app/static/*` | 단일 챗 UI | Interface/UI(출처·미리보기·승인 확장) | 4 |
| `app/lab/*` | 파라미터 실험 | lab 유지 | — |

## 승계 검증 자산 (그대로 재사용, 회귀 유지)
- 결정론 182 테스트(CI 154 + MCP 8 + ML 20), MCP 오류 taxonomy·nonce 주입방지,
  주문 트랜잭션·rollback E2E, RAG 출처인용 QA, 커머스 도구 계약.

## 원본 대비 이번 복제에서 제외
- 학습 artifact(`교과목3_LLM_학습_공략집.md`, `reference/`), `debug_notes/`, 원본 `plans/history/reports/legacy`,
  생성물(`data/mall.db`, `data/vector_store/`), 캐시(`__pycache__`, `.pytest_cache`).
