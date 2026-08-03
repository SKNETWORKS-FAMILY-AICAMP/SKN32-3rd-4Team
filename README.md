# SKN32-3rd-4Team — Agent 파트 (`feature-agent`)

실손보험 사전판정(precheck) 서비스의 **Agent 담당(정재희) 부분**. 계약(`06_계약_Agent.md`) 기준 산출물만 담는다.

**이 브랜치의 위치**: `app/`는 팀 전체 통합 코드베이스(clean architecture)의 구조를 따른다(`feature-frontend`가 원본). 이 브랜치(`feature-agent`)에는 Agent 담당 범위(사전판정 그래프·MCP 서버·클라이언트 인증)에 필요한 파일만 들어있고, 다른 역할(RAG 검색·백엔드 DB·프론트 라우터·얼굴인식 등)은 없다 — **삭제한 게 아니라 애초에 이 브랜치 역사에 없는 것**이다. 나중에 `main`으로 각자 병합할 때 합쳐진다.

## 최근 작업 내역

- **그래프A(langgraph_agent, 5개 기능 라우터 프로토타입) 폐기** — 계약서(`06_계약_Agent.md` §6, `11_AI_구조_지도.md`)가 "LangGraph 파이프라인은 `app/workflow/precheck_graph.py`에 이미 있으니 새 위치에 다시 만들지 말 것"이라고 명시한 걸 뒤늦게 확인. 별도 재구현(`langgraph_agent/`)을 정리하고, 그 과정에서 찾은 버그를 `app/`에 직접 반영하는 방향으로 전환
- **`app/core/domain/citation_guard.py`**: 인용검증기 버그 2건 수정
  - `by_path`(전체경로) 색인이 dict라 같은 `qualified_no`를 가진 서로 다른 근거가 들어오면 나중 것이 앞 것을 덮고 `exact`로 통과하던 버그 → list 색인 + clause_id/본문 기준 충돌 감지로 교체(실측: 1,367문서 중 1,198문서가 같은 qualified_no를 둘 이상 가짐)
  - 검증된 인용문(quote) 안에서 다른 조항을 준용하는 문장을 미선언 인용으로 오탐하던 문제 → quote가 answer_text 안에서 실제로 나타나는 위치(span)를 찾아 그 범위 안의 준용조항만 면제(실측: 204,098개 조항 중 90,428개(44.3%)가 자기 번호 아닌 제N조를 본문에 포함)
- **`app/adapters/manifest_policy_resolver.py`**: `product_name`을 줘도 흔한 substring(예: "실손의료비")이 여러 상품에 걸리면 같은 시작일 모호성 체크가 스킵되던 버그 → 항상 체크하도록 수정
- **`app/auth/agent_client.py`(신규)**: 외부 에이전트 인증·scope·레이트리밋(계약 §4)
- **`app/mcp_server/`(신규)**: MCP 도구 3개(`insurance_precheck`/`policy_clause_search`/`submit_case_observation`) + 리소스 2개(계약 §2)
- **`scripts/demo/agent_client.py`(신규)**: 데모 에이전트 클라이언트(계약 §5) — support-manifest 확인 → 판정 요청 → trace_id 확보 → 사례 보고
- **LLM `explain()` 연동**: `app/core/llm_clients.py`(신규) — LLM 호출 타임아웃 + 호출별 격리 executor 정리(`mcp_caller.py`에서 겪은 스레드풀 고갈 버그 재발 방지, 처음부터 포함). `precheck.py::explain()`(신규) — 규칙엔진이 이미 확정한 verdict/per_code를 프롬프트에 못박아 넘기고 LLM은 설명 문장과 인용 손잡이만 생성, `citation_guard.verify()`로 재검증해 손잡이를 지어내면 재시도 후 기권. LLM 호출 자체가 실패해도(타임아웃/API 오류) try/except로 감싸 원래 규칙엔진 판정을 그대로 반환 — 판정이 LLM 가용성에 발목 잡히지 않게 함. `precheck_graph.py::build()`가 resolve→gate→retrieve→assess→explain(LLM)→verify_citations 전체를 실제로 배선
- **감사 로그(계약 §4)**: `app/adapters/audit_log.py`(신규) — MCP 도구 3개가 요청마다 `client_id`/`operation`/`trace_id`/`verdict`/`latency_ms`를 append-only로 기록. 계약이 요구했지만 REST 라우터가 이 브랜치엔 없어서 MCP 경로엔 감사 흔적이 전혀 없던 걸 구조 재점검으로 발견해 추가. `client_ref`/질병코드 등 원문 식별정보는 `record()`에 파라미터 자체가 없어 담을 수 없음. 쓰기·직렬화 실패는 모두 best-effort로 삼켜 실제 응답을 막지 않음
- **데모 스크립트 Idempotency-Key(계약 §4)**: `scripts/demo/agent_client.py::submit_observation()`이 `/v1/observations` 호출 시 `Idempotency-Key`를 아예 안 보내던 걸 발견해 수정 — 안 주면 자동 생성, `--idempotency-key`로 직접 지정 가능
- **MCP 클라이언트 데모(신규)**: `scripts/demo/mcp_agent_client.py` — 계약 §5가 권고한 "MCP 클라이언트 버전". REST 데모와 같은 4단계를 REST 대신 MCP 리소스/도구 호출로 수행. 실제 MCP 서버를 stdio subprocess로 띄워 붙는 진짜 실행 경로를 스모크 테스트로 확인했고, `test_demo_mcp_client.py`는 `mcp.shared.memory`의 인메모리 세션으로 subprocess 없이 4단계 흐름을 검증
- **`composition.py`의 존재하지 않는 어댑터 import 수정**: `build_precheck()`가 `CLAUSE_STORE=pg`일 때 이 브랜치에 없는 `pg_clause_store`를 import하려다 raw `ImportError`가 그대로 터지던 걸 전체 파일 재점검으로 발견 — "file"만 지원하도록 하고 그 외 값은 `ConfigError`로 명시적 실패

`pytest tests/ -q` 기준 **141 passed**.

## 폴더 구조

```
SKN32-3rd-4Team/
├── app/
│   ├── core/
│   │   ├── domain/       # citation_guard, precheck_result, insurance, kcd_ranges, policy_naming, generation
│   │   ├── ports/        # precheck.py (PolicyVersionSourcePort, ClauseSourcePort)
│   │   ├── usecases/     # precheck.py (규칙엔진 run(), explain(), verify_explanation())
│   │   ├── llm_clients.py  # LLM 호출 타임아웃 + executor 정리
│   │   └── errors.py     # 예외 taxonomy
│   ├── adapters/         # manifest_policy_resolver, file_clause_store, external_submission_store, audit_log
│   ├── auth/
│   │   └── agent_client.py  # 외부 에이전트 인증·scope·레이트리밋
│   ├── mcp_server/       # MCP 도구 3개 + 리소스 2개
│   └── composition.py    # 조립 지점 (build_precheck) -- Agent 범위만 남긴 버전
├── config/
│   └── agent_clients.example.json  # 실제 파일(agent_clients.json)은 gitignore 대상
├── scripts/demo/
│   ├── agent_client.py       # REST 데모 클라이언트
│   └── mcp_agent_client.py   # MCP 데모 클라이언트(같은 4단계, MCP 도구로)
├── tests/
└── requirements.txt       # Agent 범위 의존성만 (원본 대비 대폭 축소)
```

## app/core/ — 도메인·유스케이스 (프레임워크 무관)

| 파일 | 역할 |
|---|---|
| `domain/precheck_result.py` | `Verdict`(4단), `ReasonCode`(전부 소문자), `EvidenceTier`, `PrecheckInput`/`PrecheckOutcome`(`cited_handles` 포함 — LLM이 실제로 인용했다고 선언한 손잡이), `CitationRef`, `AppliedPolicyInfo`, `CodeVerdict` |
| `domain/citation_guard.py` | 인용 검증기(v2). 손잡이(`E001`)/전체경로/번호 순으로 해소, 근거 없는 인용·모호한 인용·인용문 불일치·미선언 인용 전부 fail-closed. quote span 안의 준용조항은 면제 |
| `domain/insurance.py` | `Verdict`, `IdentificationStatus`, `PolicyVersion`, `KcdCode`, `CohortStats`(Wilson 신뢰구간) |
| `domain/kcd_ranges.py` | 약관 본문에서 KCD 코드 범위를 파싱하고 면책/예외/언급 성격을 판정 |
| `domain/policy_naming.py` | 특약 여부 판별(`looks_like_rider`), 상품명 정규화 |
| `domain/generation.py` | 세대 규칙셋(`GenerationRuleSet`) — 날짜를 코드에 하드코딩하지 않고 `config/generation_profiles.json`에서 읽음(정본에만 있음, 이 브랜치엔 설정파일 없이 타입만 있음) |
| `ports/precheck.py` | `PolicyVersionSourcePort`, `ClauseSourcePort`, `PolicyVersionRow`, `ClauseRow`, `NotResolved`, `REQUIRE_CONFIRMED` 게이트 |
| `usecases/precheck.py` | 규칙엔진. `run()`(resolve→gate→retrieve→assess), `explain()`(확정된 verdict/per_code를 프롬프트에 못박아 LLM에 설명 문장만 맡기고, `citation_guard.verify()`로 인용 손잡이 재검증 — LLM은 판정을 재해석하지 않음), `parse_explain_output()`, `verify_explanation()` |
| `llm_clients.py` | `LlmClient`, `call_with_timeout()` — 호출별 격리 `ThreadPoolExecutor`, `future.done()`으로 "wrapper 타임아웃"과 "도구 자체 예외" 구분, `try/finally`로 모든 종료 경로에서 executor 정리 |
| `errors.py` | `AppError` 계열(`ValidationErr` 422, `InfraError` 503, `AuthErr` 401, `ForbiddenErr` 403, `RateLimitErr` 429 등) |

## app/adapters/ — 저장소 어댑터

| 파일 | 역할 |
|---|---|
| `manifest_policy_resolver.py` | 가입일 → 적용 약관 버전 확정. 현행 약관 폴백 없음, 상품군 모호하면 되물음 |
| `file_clause_store.py` | 확정된 약관 버전의 조항 조회/검색(단어 매칭). 판정 근거로 못 쓰는 청크는 걸러냄 |
| `external_submission_store.py` | 외부 에이전트 사례 보고 저장(append-only, 멱등키 지원, `verification` 항상 `unverified`) |
| `audit_log.py` | MCP 요청 감사 로그(계약 §4). `client_id`/`operation`/`trace_id`/`verdict`/`latency_ms`를 append-only로 기록(`data/audit/{날짜}.jsonl`, gitignore 대상). 원문 식별정보는 담지 않음, 쓰기·직렬화 실패는 모두 best-effort |

## app/auth/ — 클라이언트 인증

| 파일 | 역할 |
|---|---|
| `agent_client.py` | `Authorization: Bearer <key>` 인증(해시 대조), scope 검사(`precheck:read`/`terms:read`/`observations:write`/`cohort:read`), `client_id+subject_hash+operation` 기준 레이트리밋. 레지스트리는 `config/agent_clients.json`(파일 기반, DB 적재 전) |

## app/mcp_server/ — MCP 서버

| 파일 | 역할 |
|---|---|
| `tools.py` | 도구 3개의 실제 로직(FastMCP 비의존, 단위 테스트 가능). REST와 **같은** 그래프·어댑터를 호출 |
| `resources.py` | `insurance://support-manifest`, `insurance://schemas/precheck-v1` |
| `server.py` | FastMCP 등록부. 인증은 `api_key` 인자로 받아 `agent_client.authenticate()` 호출(FastMCP 내장 OAuth는 issuer_url 필수라 우리 모델과 안 맞아서 안 씀) |

## tests/

| 파일 | 역할 |
|---|---|
| `test_arch.py` | 클린아키텍처 경계 검사(ARCH-001~004: 프레임워크 무-import, 안쪽/바깥 의존 방향, 도메인 타입 중복 정의 금지) |
| `test_citation_guard.py` | 인용검증기 — 손잡이/전체경로/번호 해소, by_path 충돌, quote span 안팎 |
| `test_kcd.py` | KCD 코드 범위 파싱·면책/예외 판정 |
| `test_policy_version.py` | 가입일 → 약관 버전 확정, 상품 모호성 |
| `test_precheck_verify.py` | `verify_explanation()` |
| `test_graph.py` | `PrecheckGraph`(재시도·기권 경로) |
| `test_agent_client.py` | 인증·scope·레이트리밋 |
| `test_mcp_server_tools.py` | MCP 도구 3개 — scope/레이트리밋/유스케이스 호출 |
| `test_mcp_resources.py` | support-manifest, precheck-v1 스키마 |
| `test_demo_agent_client.py` | REST 데모 스크립트 4단계 흐름(`httpx.MockTransport`), Idempotency-Key 헤더 자동생성/직접지정 |
| `test_demo_mcp_client.py` | MCP 데모 스크립트 4단계 흐름(`mcp.shared.memory` 인메모리 세션), 잘못된 api_key 시 예외 |
| `test_composition.py` | `build_precheck()`가 지원 안 하는 `CLAUSE_STORE` 값에 `ConfigError`로 명시적 실패하는지 |
| `test_llm_clients.py` | LLM 호출 타임아웃/executor 정리(성공·일반 예외 50회·wrapper 타임아웃·도구 자체 TimeoutError 구분) |
| `test_explain.py` | `explain()`이 verdict를 안 바꾸고 설명·인용 손잡이만 채우는지, 기권/근거없음 시 LLM을 안 부르는지 |
| `test_precheck_graph_llm_integration.py` | `build()` 전체 배선 end-to-end(fake LLM) — 정상 종료, 손잡이 조작 시 재시도 후 기권, 문서게이트 실패 시 LLM 미호출 |
| `test_audit_log.py` | 감사 로그 append-only 기록/조회, 원문 미포함, 쓰기 실패해도 안 죽음 |

## 실행 방법

```powershell
pip install -r requirements.txt
pytest tests/ -q

# MCP 서버 실행 (config/agent_clients.json 필요 -- .example 참고)
python -m app.mcp_server.server

# 데모 클라이언트 (REST 서버가 별도로 떠 있어야 함 -- 이 브랜치엔 아직 라우터 없음)
python -m scripts.demo.agent_client --insurer 삼성화재 --enrolled-on 20200301 --kcd F32

# MCP 데모 클라이언트 (서버를 subprocess로 직접 띄워 stdio로 붙으므로 별도 실행 불필요.
# config/agent_clients.json 필요 -- .example 참고)
python -m scripts.demo.mcp_agent_client --api-key <키> --insurer 삼성화재 --enrolled-on 20200301 --kcd F32
```

## 알려진 한계 / 남은 작업

- **LLM `explain()`은 연동됐지만 실제 외부 LLM 클라이언트는 미검증**: `app/core/llm_clients.py`/`precheck.py::explain()`/`precheck_graph.py::build()` 배선까지 끝났고 fake LLM으로 단위·통합 테스트(`test_llm_clients.py`, `test_explain.py`, `test_precheck_graph_llm_integration.py`) 전부 통과. 다만 OpenAI 등 실제 클라이언트 라이브러리는 아직 `requirements.txt`에 없고, 실 API 호출은 안 해봤음
- **`trail`이 실제 실행 순서를 반영하지 않음**: `precheck_graph.py::run_rules()`가 규칙엔진 호출 전에 5개 노드 이름을 무조건 기록. `PrecheckOutcome`(팀 공용 타입)에 "어디까지 실행됐는지" 필드 추가가 필요해 지금은 보류
- **REST 라우터가 이 브랜치엔 없음**: `app/routers/precheck.py`(REST 정본)는 `feature-frontend`에 있고, 이 브랜치는 MCP 도구가 같은 유스케이스를 직접 호출하는 부분만 가져왔다. REST와 합칠 때 정본 파일을 그대로 두고 이 브랜치의 변경사항만 대조해서 반영해야 한다(전체 덮어쓰기 금지)
- **REST 엔드포인트에 `agent_client` 인증이 안 걸려 있음**(정본 쪽 발견 사항, 이 브랜치가 만든 문제 아님) — `/v1/prechecks`·`/v1/observations`는 지금 인증 없이 호출 가능. MCP 도구만 인증이 걸려 있어 REST/MCP 간 보호 수준이 다르다. 감사 로그도 같은 이유로 지금은 MCP 경로만 남는다 — REST 라우터가 이 브랜치엔 없어서, 병합 시 REST 쪽에도 같은 감사 로그(`app/adapters/audit_log.py`) 호출을 추가해야 두 경로가 동등해진다
- **`data/raw/manifests`, `data/structured/`, `config/generation_profiles.json`, `config/accepted_extraction.json` 등 실데이터/설정 파일이 이 브랜치엔 없음** — `manifest_policy_resolver`/`file_clause_store`를 실제로 돌리려면 정본 쪽 데이터가 필요. 지금 테스트는 전부 페이크 데이터로 어댑터 인터페이스만 검증한 것
- **`app/core/domain/generation.py`(GenerationRuleSet)는 현재 요청 경로에서 안 쓰임** — 실제로는 `scripts/identify/build_document_manifest.py`(오프라인 스크립트, 이 브랜치엔 없음)가 매니페스트 생성 시점에 미리 계산해 굽는다. 5세대(2026-05-06~) 컷오프는 정본 `config/generation_profiles.json`에 이미 반영돼 있음을 확인함
