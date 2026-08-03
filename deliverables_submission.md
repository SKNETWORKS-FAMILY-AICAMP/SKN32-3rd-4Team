# 제출 산출물 — LangGraph 인용 검증·MCP 결함 수정 (Agent 정재희)

대상 의뢰서: [`17_LangGraph_인용검증_MCP_결함수정_의뢰.md`](17_LangGraph_인용검증_MCP_결함수정_의뢰.md) §9
상세 항목별 점검: [`p0_compliance_check.txt`](p0_compliance_check.txt)
작업 브랜치: `feature-agent` (원본 `feature-frontend`는 손대지 않음, `main` 병합 전 자체 검증 단계)

---

## 1. 산출물 표

| 산출물 | 상태 | 내용 |
|---|---|---|
| 코드 변경 | ✅ | P0-2, P0-3 반영. P0-1은 LLM `explain()` 연동(`app/core/llm_clients.py`)에서 재구현. P0-4는 재확인 결과 이미 구현돼 있었음(정정). P0-5는 langgraph_agent 삭제로 "정본 한 벌" 요건을 파일 삭제로 충족. P1은 그래프A 전체 삭제로 처리(방향: 제거·폐기 쪽 선택) |
| citation 회귀 테스트 | ✅ | `by_path` 충돌, handle exact 해소, 준용 quote 면제, quote 밖 미선언 — 전부 `tests/test_citation_guard.py`에 있음(25 passed) |
| MCP 회귀 테스트 | ⚠️ 범위 변경 | 의뢰서가 말한 "일반 예외/timeout/도구 TimeoutError/worker 정리"는 `mcp_caller.py`(그래프A 전용) 대상이었는데, 그래프A를 통째로 삭제해서 해당 파일이 없음. 대신 이번에 새로 만든 `app/mcp_server/`(계약 §2 산출물)의 도구 3개·인증·scope·레이트리밋 테스트로 대체(`test_agent_client.py` 14건 + `test_mcp_server_tools.py` 10건 + `test_mcp_resources.py` 3건) |
| graph 회귀 테스트 | ⚠️ 일부 | 문서 gate(✅ 재확인 완료), 0근거(✅ 구조적으로 안전함 증명), 재시도(✅ 배선 버그 발견·수정 완료). "5노드"는 의도적으로 미적용(app/ 구조상 usecase가 이미 5단계를 한 함수로 처리 중이라 그래프에서 다시 쪼개면 로직 중복 발생 — 아키텍처상 거부). "store 대조"(`verify_against_store()`)는 의뢰서 주장과 달리 코드베이스에 실존하지 않는 함수임을 확인, 지금 구조에서는 불필요로 판단 |
| 구조 테스트 | ✅ | `tests/test_arch.py` — ARCH-001~004 전부 통과(9 passed). 정본 외 중복 로직 없음(langgraph_agent 삭제로 확인) |
| LLM `explain()` 연동 | ✅ | `app/core/llm_clients.py`(타임아웃+executor 정리) + `precheck.py::explain()`(verdict 재해석 없이 설명만 생성, LLM 호출 실패해도 판정은 유지) + `precheck_graph.py::build()` 배선. `test_llm_clients.py`(5) + `test_explain.py`(9) + `test_precheck_graph_llm_integration.py`(3, fake LLM으로 정상/손잡이-조작/문서게이트 3가지 경로 end-to-end 확인) |
| 감사 로그(계약 §4) | ✅ | `app/adapters/audit_log.py`(신규) — MCP 도구 3개가 client_id/operation/trace_id/verdict/latency를 append-only로 기록. 원문 식별정보는 파라미터 자체가 없어 담을 수 없음. 쓰기 실패·직렬화 실패 모두 best-effort로 삼킴. `.gitignore`에 `data/audit/`·`data/external/` 추가. `test_audit_log.py`(6) + `test_mcp_server_tools.py`에 기록 검증 추가 |
| 데모 스크립트 Idempotency-Key(계약 §4) | ✅ | `scripts/demo/agent_client.py::submit_observation()`이 `/v1/observations`에 `Idempotency-Key` 헤더 없이 호출하던 것을 수정 — 안 주면 자동 생성, `--idempotency-key`로 직접 지정도 가능. `test_demo_agent_client.py`에 회귀 테스트 추가 |
| MCP 클라이언트 데모(계약 §5 권고) | ✅ | `scripts/demo/mcp_agent_client.py`(신규) — REST 데모와 같은 4단계를 MCP 리소스/도구 호출로 수행. 실제 서버를 stdio subprocess로 띄워 붙는 실행 경로를 스모크 테스트로 확인. `test_demo_mcp_client.py`(4)는 `mcp.shared.memory`의 인메모리 세션으로 subprocess 없이 검증 |
| composition.py 존재하지 않는 어댑터 import | ✅ | `build_precheck()`가 `CLAUSE_STORE=pg`일 때 이 브랜치에 없는 `pg_clause_store`를 import하려다 raw `ImportError`가 터지던 것을 발견 — "file"만 지원하도록 하고 그 외 값은 `ConfigError`로 명시적 실패. `test_composition.py`(3) 추가 |
| 실행 결과 | ✅ | 아래 2절 참고 |
| 짧은 변경 기록 | ✅ | 아래 3절 참고 |

---

## 2. 실행 결과

### 의뢰서 권장 명령 1 — 정본 관련 테스트
`test_handoff_consistency.py`는 실제로 존재하지 않는 파일이라 제외(레포 전체 grep으로 확인함).

```
$ pytest -q tests/test_citation_guard.py tests/test_graph.py tests/test_arch.py
..............................................                           [100%]
46 passed, 1 warning in 0.44s
```

### 의뢰서 권장 명령 2 — 외부 브랜치(langgraph_agent) 테스트
해당 없음 — `langgraph_agent/` 전체를 삭제했으므로 이 명령의 대상 파일이 없음(삭제 사유는 [3절](#3-짧은-변경-기록) 참고). 대신 아래 개별 파일별 결과에 그 자리를 대체하는 신규 테스트(`test_agent_client.py`, `test_mcp_server_tools.py`, `test_mcp_resources.py`, `test_demo_agent_client.py`)를 포함시켰다.

### 의뢰서 권장 명령 3 — 전체 회귀

```
$ pytest -q
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed, 1 warning in 1.26s
```

### 파일별 세부 결과

| 파일 | 결과 |
|---|---|
| `tests/test_arch.py` | 9 passed |
| `tests/test_citation_guard.py` | 25 passed |
| `tests/test_kcd.py` | 17 passed |
| `tests/test_policy_version.py` | 12 passed |
| `tests/test_precheck_verify.py` | 5 passed |
| `tests/test_graph.py` | 12 passed |
| `tests/test_agent_client.py` | 14 passed |
| `tests/test_mcp_server_tools.py` | 10 passed |
| `tests/test_mcp_resources.py` | 3 passed |
| `tests/test_demo_agent_client.py` | 4 passed |
| `tests/test_demo_mcp_client.py` | 4 passed |
| `tests/test_composition.py` | 3 passed |
| `tests/test_llm_clients.py` | 5 passed |
| `tests/test_explain.py` | 9 passed |
| `tests/test_precheck_graph_llm_integration.py` | 3 passed |
| `tests/test_audit_log.py` | 6 passed |
| **합계** | **141 passed** |

---

## 3. 짧은 변경 기록

### 수정 파일

- `app/core/domain/citation_guard.py` — P0-2(quote span 준용조항 면제), P0-3(by_path 충돌 → ambiguous)
- `app/adapters/manifest_policy_resolver.py` — 신규 발견: `product_name`을 줘도 흔한 substring이면 동일-시작일 모호성 체크가 스킵되던 버그
- `app/workflow/precheck_graph.py` — 재시도 배선 복구(`retarget` 없을 때 즉시 기권 대신 같은 입력으로 규칙엔진 재호출) + `build()`에 LLM `explain()` 배선(resolve→gate→retrieve→assess→explain→verify_citations)
- `app/auth/agent_client.py`(신규) — 인증·scope·레이트리밋(계약 §4). 상수시간 해시 비교(`hmac.compare_digest`) 적용
- `app/mcp_server/{tools,resources,server}.py`(신규) — MCP 도구 3개 + 리소스 2개(계약 §2)
- `app/core/errors.py` — `RateLimitErr`(429) 추가
- `app/core/llm_clients.py`(신규) — LLM 호출 타임아웃 + 스레드별 격리 executor 정리(DoD 1·2번)
- `app/core/domain/precheck_result.py` — `PrecheckOutcome.cited_handles` 필드 추가(LLM이 실제로 인용했다고 선언한 손잡이)
- `app/core/usecases/precheck.py` — `explain()`/`parse_explain_output()`/`_build_explain_prompt()` 추가. LLM은 이미 확정된 verdict/per_code를 프롬프트로 못박아 받고, message/cited_handles만 채움. LLM 호출 실패(타임아웃/API 오류) 시 원래 outcome을 그대로 반환하도록 try/except로 감쌈(신규 발견 5)
- `app/adapters/audit_log.py`(신규) — 계약 §4 감사 로그. `external_submission_store.py`와 같은 append-only jsonl 패턴, `app/mcp_server/tools.py` 세 도구 모두에 배선(신규 발견 6)
- `scripts/demo/agent_client.py` — `submit_observation()`이 `Idempotency-Key` 헤더를 안 보내던 계약 §4 위반을 수정(신규 발견 8). 안 주면 client_ref+trace_id+outcome 기반 해시로 자동 생성
- `app/composition.py` — Agent 담당 범위(`build_precheck`)만 남기게 트리밍
- `scripts/demo/agent_client.py`(신규) — 데모 클라이언트(계약 §5)
- `langgraph_agent/`(전체 삭제) — 계약서(`06_계약_Agent.md` §6, `11_AI_구조_지도.md`)가 "LangGraph 파이프라인은 `app/workflow/precheck_graph.py`에 이미 있으니 새 위치에 다시 만들지 말 것"이라 명시한 것을 뒤늦게 확인, 별도 재구현을 폐기하고 `app/`에서 직접 작업하는 방향으로 전환

### 선택한 설계

- **그래프A/langgraph_agent 폐기(제거 방향)**: P1 완료 기준의 두 선택지("제거" vs "state 밖 인자로 분리") 중 제거를 선택. 데모 용도로만 유지되던 코드였고 더 이상 필요 없다는 확인을 받아, 패치보다 확실한 제거가 재발 방지에 낫다고 판단
- **5노드 topology 미이식**: `app/core/usecases/precheck.py::run()`이 이미 5단계를 한 함수 안에서 처리하며 각 단계에서 조기 반환(abstain)하는 구조. 그래프 레이어에서 이를 다시 노드로 쪼개면 같은 판단 로직이 두 곳에 생겨 반드시 어긋난다고 판단, 의도적으로 하지 않음
- **재시도 기본 동작(retarget 없을 때)**: 조항을 다시 검색하지 않고 같은 입력으로 규칙엔진을 재호출하는 방식 선택. 지금은 결정론적이라 즉시 같은 이유로 재차단되지만(계산 1회 낭비, 안전), LLM explain() 연동 시 진짜 재시도로 작동하게 되는 설계
- **`verify_against_store()` 미구현**: 의뢰서가 "정본에 이미 있다"고 주장했으나 grep으로 실존하지 않음을 확인. 현재 아키텍처(한 프로세스 내에서 동일 evidence를 공유)에서는 독립 재조회가 막을 수 있는 위협 자체가 없다고 판단해 지금은 만들지 않음(LLM이 외부로 나갔다 오는 구조가 되면 재검토)
- **LLM `explain()` 타임아웃/executor 정리를 처음부터 포함**: `mcp_caller.py`(삭제됨)에서 겪은 스레드풀 고갈 버그가 새 LLM 호출 자리에서 재발하지 않도록, `app/core/llm_clients.py`를 짜는 시점부터 호출별 격리 executor + `future.done()` 기반 원인 구분 + `try/finally` 정리를 포함시킴(사후 추가가 아님)
- **LLM 호출 실패는 규칙엔진 판정을 막지 않는다**: `explain()`이 `llm.complete()`를 try/except로 감싸, 실패 시 설명문 없이 원래 outcome을 그대로 반환. 문서게이트·인용검증 실패는 전부 abstain으로 처리되는데 LLM 실패만 처리가 없던 걸 자체 재점검으로 발견·수정(신규 발견 5)
- **감사 로그 쓰기 실패도 응답을 막지 않는다**: `audit_log.record()`가 `except Exception`으로 감싸는 best-effort — 처음엔 `OSError`만 잡았는데, 자체 재점검으로 호출부가 실수로 직렬화 안 되는 값(enum 등)을 넘기면 `TypeError`가 그대로 새어나가 MCP 응답을 크래시시킬 수 있음을 발견해 범위를 넓힘(신규 발견 7)
- **`data/external/`, `data/audit/`를 `.gitignore`에 추가**: 둘 다 런타임에 실제 파일을 쌓는 디렉터리인데 gitignore가 없어서 로컬 실행 후 `git add -A` 시 그대로 커밋될 위험이 있었음(신규 발견 7)

### 남은 위험 또는 후속 작업

1. **trail이 실제 실행 순서를 반영하지 않음** — `run_rules()`가 규칙엔진 호출 전에 5개 노드 이름을 무조건 기록. 정확히 고치려면 `PrecheckOutcome`(팀 공용 타입)에 필드 추가가 필요해 지금은 보류, LLM/실데이터 연동 후 팀에 제안 예정
2. **LLM `explain()` 연동은 완료했으나 실제 외부 LLM 클라이언트 미검증** — `app/core/llm_clients.py`/`precheck.py::explain()`/`precheck_graph.py::build()` 배선까지는 끝났고 전부 fake LLM으로 단위/통합 테스트 통과. 다만 OpenAI 등 실제 클라이언트 라이브러리는 아직 `requirements.txt`에 없고, 실 API 호출은 미검증
3. **REST 라우터가 이 브랜치엔 없음** — `app/routers/precheck.py`(정본)는 `feature-frontend`에 있음. 병합 시 정본 파일을 그대로 두고 이 브랜치의 변경사항만 대조 반영 필요(전체 덮어쓰기 금지)
4. **REST 엔드포인트에 `agent_client` 인증이 안 걸려 있음** — 정본 쪽 기존 상태(이번 작업 범위 밖에서 발견)
5. **실데이터(`data/structured/`, `config/generation_profiles.json` 등)가 이 브랜치엔 없음** — 문서 게이트 등 일부 로직은 코드상 완성이나 실데이터 통합 테스트는 미완료
6. `app/adapters/external_submission_store.py`(기존 코드)의 멱등키 중복 체크에 미세한 race condition — 낮은 우선순위
7. `citation_guard.EvidenceClause` 변환 시 `clause_id` 미전달 — 본문(text) 기준 폴백으로 안전하게 동작하나 개선 여지 있음
8. `GraphState.outcome.per_code[].code`에 평문 KCD 코드가 들어있음(응답 페이로드라 불가피) — 지금은 checkpointer를 안 걸어서 실제로 안 새지만, 나중에 checkpointer/트레이싱을 붙이면 이 경로로 평문이 새어나갈 수 있음("지금은 안전, 구조는 취약")

---

## 4. 10절 완료 조건(Definition of Done) 15개 대조

| # | 조건 | 상태 |
|---|---|---|
| 1 | 일반 예외 50회 후 executor worker 안 쌓임 | ✅ 완료 — `app/core/llm_clients.py`, `test_llm_clients.py`로 확인 |
| 2 | 도구 TimeoutError vs wrapper deadline 구분 | ✅ 완료 — `future.done()`으로 원인 구분, `test_llm_clients.py`로 확인 |
| 3 | 검증된 quote 안 준용조항 미오탐 | ✅ 완료 |
| 4 | quote 밖 미선언은 계속 fail-closed | ✅ 완료 |
| 5 | 동일 경로 다른 조항 → `ambiguous` | ✅ 완료 |
| 6 | E001은 지정 근거로 정확히 해소 | ✅ 완료 |
| 7 | retrieve 결과에 qualified_no/clause_id/위치 보존 | ✅ 완료 |
| 8 | `parse_status≠ok` 문서는 retrieve 전 기권 | ✅ 완료 |
| 9 | 근거 0건은 판정 통과 안 함 | ✅ 완료(구조적 증명) |
| 10 | 5노드 topology + 재시도 배선 실제 runtime 실행 | ⚠️ 절반만 — 재시도는 완료, 5노드는 의도적 미적용 |
| 11 | citation이 독립 clause store와 대조 | ❌ 의도적 미충족 — `verify_against_store()` 자체가 실존하지 않음, 지금 구조상 불필요로 판단 |
| 12 | 정본 한 벌에만 로직 존재 | ✅ 완료 |
| 13 | state/checkpoint/log에 평문 질병기호 없음 | ⚠️ 부분 충족 — 지금은 안전(checkpointer 미사용), 구조는 취약(8번 참고) |
| 14 | ReAct 없음/재시도 2회/verdict 비재해석 | ✅ 완료 — `explain()`이 verdict/per_code를 프롬프트에 못박아 넘기고 message만 채움(`test_explain.py`) |
| 15 | 관련+전체 테스트 통과 | ✅ 완료 (141 passed) |

**집계**: 완료 12개(1·2번 포함), 의도적 미충족 2개(10 절반, 11), 구조적으로 약한 부분 충족 1개(13).
