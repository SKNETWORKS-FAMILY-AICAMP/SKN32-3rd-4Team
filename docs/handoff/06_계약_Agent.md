# 인터페이스 계약 — Agent (LangGraph · MCP · 외부 에이전트)

담당 **정재희** · 버전 v1 · 2026-08-02

---

## 0. 당신이 만드는 것

판정의 **흐름**과, 외부 에이전트가 우리를 부르는 **입구**.

도메인 판단은 하지 않는다. 노드를 잇고, 분기하고, 재시도를 통제한다.

---

## 1. LangGraph 파이프라인

```
입력(PrecheckRequest)
   │
   ├─ resolve_policy       가입일 → 적용 약관 확정
   │     └─ NotResolved → abstain(reason_code 그대로)
   │
   ├─ gate_document        parse_status == "ok" 인가
   │     └─ 아니면 → abstain(DOCUMENT_NOT_RELIABLE)
   │
   ├─ retrieve             AI 1 의 retrieve()
   │     └─ 0건 → abstain(NO_EVIDENCE)
   │
   ├─ assess               AI 2 의 assess()  — 규칙 기반
   │
   ├─ explain              AI 2 의 explain() — LLM
   │
   ├─ verify_citations     ★여기가 재시도 지점
   │     ├─ 통과 → 완료
   │     ├─ 조항번호 오류 → 허용 목록으로 **설명문만 1회 수정**
   │     ├─ 근거 부족    → 표적 검색 **1회**
   │     └─ 재시도 초과   → 초안 폐기, abstain(CITATION_UNVERIFIED)
   │
   └─ 출력(PrecheckResult)
```

### 왜 LangGraph 인가

흐름이 **분기하고 되돌아온다.** LangChain 체인은 직선이라 이걸 표현하면 금방 읽기 어려워진다.

### 지켜야 할 경계

| 하면 안 되는 것 | 왜 |
|---|---|
| **자율 ReAct 루프** | 언제 끝날지 모르고 감사가 안 된다 |
| 재시도 2회 초과 | 비용·지연이 늘고, 그때까지 안 되면 근거가 없는 것이다 |
| 도메인 상태 재해석 | `verdict` 를 그래프에서 바꾸지 않는다. AI 2 가 정한 것을 그대로 나른다 |
| 상태에 원문 개인정보 저장 | 질병기호는 민감정보다. 해시로 다룬다 |

---

## 2. MCP — REST를 정본으로, MCP는 어댑터

**같은 유스케이스를 부른다.** 로직을 두 벌 만들지 않는다.

```
외부 에이전트
   ├─ REST  POST /v1/prechecks   ← 정본
   └─ MCP   insurance_precheck   ← 어댑터
              ↓
        precheck.run()  (동일한 application service)
```

### 노출할 도구 — **3개면 충분하다**

| 도구 | 대응 REST | scope |
|---|---|---|
| `insurance_precheck` | `POST /v1/prechecks` | `precheck:read` |
| `policy_clause_search` | `POST /v1/terms/search` | `terms:read` |
| `submit_case_observation` | `POST /v1/observations` | `observations:write` |

### 리소스

```
insurance://support-manifest      무엇을 지원하는지
insurance://schemas/precheck-v1   응답 스키마
```

**약관 원문 전체를 MCP 리소스로 공개하지 않는다.** 저작물이다.

### 기존 코드 주의

`app/routers/mcp.py` 는 MCP 서버가 아니라 **클라이언트 시연용 프록시**다.
공개 서버는 `/mcp` 의 Streamable HTTP 로 따로 세워야 한다.

---

## 3. A2A — **필수가 아니다. 넣는다면 timebox**

자세한 판단 근거는 [09_A2A_판단.md](09_A2A_판단.md).

요약하면:
- **핵심은 API 키 + 클라이언트 레지스트리 + 데모 에이전트**다. 이건 A2A 없이도 된다
- `app/routers/a2a.py` 는 **이름만 A2A인 커머스 잔재**다. 재사용 기반이 못 된다
- 넣는다면 **`coverage-precheck` skill 하나만**, Task 없이 direct Message, 3~5일 timebox

---

## 4. 클라이언트 관리 (이게 먼저다)

| 항목 | 내용 |
|---|---|
| 등록 | `agent_client` 테이블. 이름·API 키 해시·scope·레이트리밋 |
| 인증 | `Authorization: Bearer <key>`. 키는 **해시로 저장** |
| scope | `precheck:read` `terms:read` `observations:write` `cohort:read` |
| 멱등성 | 쓰기 요청에 `Idempotency-Key` **필수** |
| 레이트리밋 | `client_id + subject_hash + operation` 기준 |
| 감사 | 요청마다 client, trace_id, verdict, latency 기록. **원문 대신 해시** |

---

## 5. 데모용 에이전트

시연에 필요하다. **A2A 와는 별개다.**

```
scripts/demo/agent_client.py
  1. GET  /v1/support-manifest      무엇을 지원하는지 확인
  2. POST /v1/prechecks             판정 요청
  3. 결과의 trace_id 를 들고
  4. POST /v1/observations          나중에 실제 결과 보고
```

MCP 클라이언트 버전도 같이 두면 "에이전트가 도구로 쓴다"를 보여줄 수 있다.

---

## 6. 산출물

| 산출물 | 형태 |
|---|---|
| `app/workflow/precheck_graph.py` | LangGraph 파이프라인 — ★**이미 존재한다.** `app/insurance/` 에 다시 만들지 않는다(`11_AI_구조_지도.md`) |
| `app/mcp_server/` | MCP 서버(도구 3개 + 리소스 2개) |
| `app/auth/agent_client.py` | 키·scope·레이트리밋 |
| `scripts/demo/agent_client.py` | 데모 에이전트 |
| `tests/test_graph.py` | 재시도·기권 경로 테스트 |
