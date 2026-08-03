# langgraph_agent

실손보험 RAG 서비스의 **LangGraph + MCP 에이전트 파트**. 사용자 질문(질병기호/증상/약관 질문 등)을 받아서 의도를 분류하고, 필요한 도구를 호출한 뒤, 결과를 종합해 응답을 생성하는 전체 흐름을 담당한다.

**아키텍처**: 싱글 에이전트 + 툴콜링 구조 (멀티에이전트 아님).

이 폴더엔 그래프가 2개 있다:
- `graph/builder.py` — 5개 기능(약관/청구통계/유사사례/질병코드/용어) 의도분류 라우터. 초기 프로토타입, `main.py`는 더 이상 이걸 부르지 않는다.
- `graph/precheck_graph.py` — 계약(`06_계약_Agent.md`) 기준 사전판정 전용 그래프. resolve_policy→gate_document→retrieve→assess→explain→verify_citations, verdict는 판정 자체를 하지 않고 그대로 전달, 질병기호는 해시로 저장. **`main.py`가 실제로 부르는 것은 이 그래프다.**

`assess`/`retrieve`는 아직 이 레포에 있는 것(자체 RAG 검색, 임시 규칙)으로 채운 자리표시이며, 실제 규칙엔진/검색 함수 연결 시 `precheck_graph.py`의 `build()` 내부만 교체하면 된다.

## 최근 수정 내역 (완료)

외부 코드리뷰 2라운드 + 자체 재점검으로 찾은 버그 22개, 전부 수정 완료. `pytest tests/ -q` 기준 **50 passed**.

- [x] `router.py`: `json.loads("null")` 크래시 방지, 분류 실패 시 위험한 기본값(`policy_rag`) 임의 확정 제거
- [x] `mcp_caller.py`/`judge_coverage.py`: 일부 intent 실패 시 `error`가 최종답변에서 조용히 사라지던 것 → 결정론적으로 경고문 덧붙임
- [x] `state.py`/`mcp_caller.py`/`graph/privacy.py`: 그래프A에 없던 질병기호 해시 보호(`disease_code_hash`) 추가, 해시 유틸 공용화
- [x] `precheck_domain.py`: `ReasonCode` 대소문자 혼재 → 전부 소문자 snake_case로 통일
- [x] `precheck_graph.py`: `normalize→rules→verify` 세 덩어리로 뭉쳐있던 토폴로지 → 5단계(resolve_policy/gate_document/retrieve/assess/explain) 독립 LangGraph 노드로 분해
- [x] `mcp_caller.py` (P2): 공유 스레드풀 고갈로 반복 타임아웃 시 서버 전체가 먹통 될 수 있던 버그 → 호출별 격리 executor로 교체
- [x] `precheck_graph.py`: 인용검증 실패 시 재시도(`verify_citations`)가 `build()`에서 배선이 안 돼 production에서 전혀 작동 안 하던 것 발견 → 세대 필터를 안 건드리는 "같은 근거로 explain 재작성" 기본 재시도 경로 추가
- [x] `requirements.txt`: 개발 환경에 프로젝트 의존성이 애초에 하나도 안 깔려있던 것 발견 → 실제로 같이 동작하는 조합으로 전부 버전 고정

미해결 항목은 아래 [팀 코디네이션이 필요한 부분](#팀-코디네이션이-필요한-부분-다른-파트-의존) 참고.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 오케스트레이션 | LangGraph (`StateGraph`) |
| LLM | OpenAI API (`gpt-4o`, `langchain-openai`) — `config.py`의 `LLM_MODEL_NAME`으로 교체 가능 |
| 임베딩 | `BAAI/bge-m3` (`langchain-huggingface`) |
| 벡터DB | Chroma (`langchain-community`), 로컬 persist |
| 청킹 | 정규식 기반 조문(제N조) 단위 청킹 (`rag/chunking.py`) |
| 도구 인터페이스 | MCP 스타일 함수 (`mcp_tools/`) — 현재는 in-process 함수 호출, `fastmcp` 실제 서버화는 미결정 |
| 테스트 | pytest (LLM/벡터DB 없이도 배선 검증 가능하도록 monkeypatch로 격리) |

## 폴더 구조

```
langgraph_agent/
├── graph/          # 그래프 설계 (노드를 어떻게 연결할지)
├── nodes/          # 각 노드의 실제 로직
├── mcp_tools/       # MCP 도구 정의 (외부 데이터/기능 호출 인터페이스)
├── rag/            # 약관 벡터DB 구축 및 검색 (mcp_tools에서 내부적으로 사용)
├── data/           # 원본 데이터 및 벡터DB 저장소
├── tests/          # 노드/도구/전체 흐름 테스트
├── config.py
├── main.py
├── .env.example
└── requirements.txt
```

---

## graph/ — 그래프 설계도

전체 작업 흐름을 어떻게 연결할지 정의하는 부분.

```
START -> router -> mcp_caller -> result_parser -> (분기)
    분기 성공 -> judge_coverage -> END
    분기 실패 -> knowledge_gap -> END
```

| 파일 | 역할 |
|---|---|
| `state.py` | 그래프 전체에서 공유되는 State 스키마(`InsuranceState`) 정의. `citations`(약관조항만, 판정근거)와 `references`(유사사례/통계/용어, 참고자료)를 분리해서 관리. `disease_code`(평문, 도구 호출용)와 `disease_code_hash`(로그/트레이스 참조용) 분리 |
| `privacy.py` | 민감정보(질병기호) 해시 공용 유틸(`hash_code`). 그래프A(`mcp_caller.py`)와 그래프B(`precheck_graph.py`)가 같이 씀 — 로직이 두 곳에 따로 있으면 한쪽만 바뀌어 어긋나기 쉬움 |
| `builder.py` | `StateGraph` 조립. `route_after_mcp`가 `needs_fallback` 플래그로 성공/폴백 분기 |
| `router.py` | 5개 기능 의도분류(LLM) + 질문 텍스트에서 연령대/가입년도(세대) 추출. `classify_intent`는 LLM이 `null`/비-리스트 JSON을 줘도 죽지 않고, 파싱 실패 시 가장 위험한 `policy_rag`로 임의 확정하지 않고 빈 리스트를 반환 |
| `extractors.py` | 정규식 기반 연령대("30대")·가입년도→세대 추출 유틸(경계 연도는 `None`) + `resolve_generation_from_date`(정확한 날짜 기반, 경계 없음) |
| `precheck_domain.py` | 사전판정 도메인 타입: `Verdict`(4단계), `ReasonCode`(7종, 전부 소문자 snake_case — storyboard.html/08_계약_프론트.md 예시와 맞춤, 1:N 되묻기용 `AMBIGUOUS_PRODUCT_LINE` 포함), `Citation`(qualified_no/clause_id 포함, citation_guard용), `ProductCandidate`, `PolicyResolution`, `PerCodeVerdict`, `PrecheckInput`/`PrecheckOutcome`(`cited_handles` 포함) |
| `citation_guard.py` | 인용 검증기(v2). LLM이 `E001` 같은 요청단위 손잡이로 인용하게 하고, 손잡이/전체경로/번호 순으로 해소. 근거에 없는 조항 인용, 후보 2개 이상(ambiguous), 인용문-원문 불일치, 본문에서 선언 없이 조항 언급(undeclared mention) — 전부 fail-closed로 잡는다 |
| `precheck_graph.py` | 사전판정 그래프. `GraphState`(질병기호 해시 저장), `PrecheckGraph`(재시도 2회 상한), `explain`이 `citation_guard`로 손잡이 붙인 근거를 주고 LLM 응답을 `(메시지, 인용손잡이)`로 파싱(`parse_explain_output`), `verify_citations_in_message`가 `citation_guard.verify()`로 대조. `kcd_codes` 여러 개 입력 시 코드별 개별 판정(`per_code[]`) 산출 후 최우선순위(가장 주의 필요한 것)로 대표 verdict 집계. `resolve_policy/gate_document/retrieve/assess/explain` 5단계가 각각 독립된 메서드이자 `build_langgraph()`에서 별도 LangGraph 노드로 존재 — 계약 다이어그램대로 단계별 분기/기권 지점이 그래프 구조에 그대로 드러남(`retrieve`가 근거를 못 찾으면 `assess`/`explain`은 아예 호출되지 않고 그 자리에서 END). 인용검증 실패 시 재시도는 기본적으로 **조항을 다시 검색하지 않고 같은(세대 필터 통과한) 근거로 `explain`만 다시 호출** — 세대가 다른 조항이 섞여 들어오는 걸 막기 위함(`retarget` 콜백을 주입하면 표적 검색으로 대체 가능하지만 `build()`는 기본적으로 안 씀) |

## nodes/ — 각 단계별 실제 작업

| 파일 | 역할 |
|---|---|
| `mcp_caller.py` | 4개 MCP 도구 호출. 타임아웃마다 새 1-worker `ThreadPoolExecutor`를 격리해서 씀(공유 풀 X — 타임아웃 나도 스레드가 안 죽는 파이썬 특성상, 공유 풀이면 반복 타임아웃 시 풀 전체가 고갈돼 이후 모든 호출이 먹통이 됨)·재시도(일시적 오류만 1회)·intent별 독립 실패 처리·무폴백 판단. `policy_rag`가 요청됐으면 다른 intent가 성공해도 약관 조항이 반드시 있어야 통과(보장판단의 유일한 근거이기 때문). 질병코드 확정 시 `disease_code`(평문)와 `disease_code_hash`(해시)를 같이 채움 |
| `result_parser.py` | 약관조항(`citations`, 판정근거)과 유사사례·통계·용어(`references`, 참고자료)를 분리해서 조립 — 섞으면 약관 근거 0건이어도 "근거 있음"처럼 보이는 문제가 있었음 |
| `judge_coverage.py` | 약관조항 + 청구통계 + 유사사례 + 용어설명을 종합해 LLM이 최종 응답 생성. 질병코드 후보가 여럿이면 확정하지 않고 "확인 필요"로 안내. 일부 intent만 실패한 경우(`state["error"]`)는 LLM 문장에 맡기지 않고 최종 답변 뒤에 경고문을 결정론적으로 덧붙임 — 조용히 누락시키지 않음. ★프로토타입 — 판정(verdict)을 LLM이 자유텍스트로 직접 씀. 규칙엔진 분리 + 인용검증까지 갖춘 버전은 `precheck_graph.py` |
| `knowledge_gap.py` | 근거를 못 찾았을 때 폴백 응답 (무폴백 원칙) |

## mcp_tools/ — MCP 도구 (외부 인터페이스)

| 파일 | 담당 기능 | 상태 |
|---|---|---|
| `policy_rag_server.py` | 기능1 (약관 RAG) | 동작함 (`rag/` 벡터DB 검색) |
| `claim_stats_server.py` | 기능2, 3 (청구승인율/유사사례) | 목업(`_mock: True`) — 실데이터 DB 연동 대기 |
| `disease_code_server.py` | 기능4 (질병코드매칭) | 스텁 — data.go.kr API 연동 대기 |
| `glossary_server.py` | 기능5 (용어설명) | 스텁 — 데이터소스 확인 대기 (RAG팀 청킹 결과물 `chunks_terms.jsonl`로 해결될 가능성 있음) |

## rag/ — 약관 벡터DB 파이프라인

| 파일 | 역할 |
|---|---|
| `chunking.py` | 약관 원문을 조문(제N조) 단위로 청킹 |
| `build_vectorstore.py` | 청킹 결과를 `BAAI/bge-m3`로 임베딩해 Chroma에 저장 (`normalize_embeddings=True`) |
| `search_policy.py` | 세대 필터링 + 유사도 검색. 결과 없으면 빈 리스트(무폴백) |

## data/ — 원본 데이터

| 경로 | 내용 |
|---|---|
| `policy_docs/` | 세대별 실손보험 표준약관 원문 텍스트 (현재 3세대 1개만 확보) |
| `chroma_db/` | 임베딩된 벡터DB 저장 경로 (`.gitignore` 대상) |

## tests/

| 파일 | 역할 |
|---|---|
| `test_chunking.py` | 청킹 로직 단위 테스트 |
| `test_mcp_tools.py` | MCP 도구 입출력 타입 테스트 |
| `test_extractors.py` | 연령대/세대 추출 로직 테스트 (경계 연도 처리 포함) |
| `test_mcp_caller.py` | mcp_caller 오케스트레이션 로직(무폴백 판단/부분실패/재시도/후보보존) |
| `test_graph_flow.py` | `graph/builder.py`(그래프A) 시나리오 테스트. `main.py`가 아니라 `build_graph()`를 직접 돌림. LLM/벡터DB monkeypatch로 **API 키 없이도 실행 가능** |
| `test_precheck_graph.py` | `precheck_graph.py` 오케스트레이션(정상흐름/각 abstain 사유코드/1:N 되묻기/per_code/재시도 성공·소진·중복방지) + `citation_guard` 기반 인용검증(할루시네이션·미선언 인용 탐지) + `parse_explain_output` |
| `test_main.py` | `main.py`가 실제로 `precheck_graph`를 부르는지, 가입일시 없으면 기권하는지 확인 |

## 최상위 파일

| 파일 | 역할 |
|---|---|
| `config.py` | 모델명, 벡터DB 경로, MCP 타임아웃 등 설정값. `.env` 자동 로드 |
| `main.py` | 그래프 실행 진입점. `graph/precheck_graph.py`를 부름(그래프A가 아님) |
| `.env.example` | `OPENAI_API_KEY` 등 필요한 환경변수 예시 |
| `requirements.txt` | 필요 패키지, 전부 버전 고정. `langgraph==0.6.11` + `langchain-core<1.0.0`인 이유: langgraph 1.x는 `langchain-core>=1.4.7`을 요구하는데, `langchain-huggingface`/`langchain-openai` 등 나머지 langchain 0.3.x 계열은 `langchain-core<1.0.0`을 요구해서 서로 호환 안 됨 — 실제로 같이 동작하는 조합으로 고정해둔 것 |

---

## 실행 방법

```powershell
.\.venv\Scripts\Activate.ps1
cd langgraph_agent
pip install -r requirements.txt

pytest tests/ -v                    # API 키 없이도 배선 검증 가능
python -m rag.build_vectorstore      # 벡터DB 구축 (최초 1회)
copy .env.example .env               # OPENAI_API_KEY 채우기
python main.py                       # 실제 질문 테스트
```

## 설계 원칙

- **무폴백**: 근거를 하나도 못 찾으면 knowledge_gap으로 라우팅. LLM 프롬프트에도 "확인 불가" 답변을 명시적으로 요구
- **확정보다 확인**: 질병코드 후보가 여럿이거나, 가입년도가 세대 경계에 걸치면 임의로 하나를 확정하지 않음
- **역할 분리**: Router는 의도분류만, 실제 도구 호출은 mcp_caller, 결과 종합은 judge_coverage — 각 노드가 한 가지 책임만 갖도록 유지

## 팀 코디네이션이 필요한 부분 (다른 파트 의존)

- 질병코드 실제 API 연동 (data.go.kr 키)
- 청구통계/유사사례 실제 DB 연동 (스키마 확정 대기)
- 용어사전 데이터소스 (RAG팀의 `chunks_terms.jsonl`로 해결 가능성 있음, 확인 필요)
- RAG팀 청크 스키마(`chunks_main.jsonl`/`chunks_terms.jsonl`) 확정되면 로더 코드 추가 필요
- `precheck_graph.py`의 `assess`(규칙엔진)/`retrieve`(약관검색) 실제 함수 연동 — AI1/AI2 인터페이스 확정 대기
- `app/` 프로젝트 구조와의 통합 방식 확정 필요 (레포/브랜치 위치, `app/core/usecases/precheck.py` 등과의 관계)
- `resolve_policy`의 1:N 상품군 후보(`ProductCandidate`) 채우기 — 상품 마스터 데이터 연동 필요 (지금은 세대만으로 단일 확정, 후보 분기 로직은 자리표시)
- 에이전트 트랙 API 표면(`docs/storyboard.html` 기준): `GET /v1/support-manifest`, 인증/scope, `Idempotency-Key`(관측 제출) — 아직 미구현
- `citation_guard.py`는 `제N조`/`N.`(번호조항) 둘 다 지원하지만, 실제 AI1 검색 결과가 `qualified_no`(예: `"보통약관/제9조"`)를 안 채워주면 `article_no`만으로 대체되어 서로 다른 특약의 같은 번호를 구분 못 할 수 있음 — 실데이터 연동 시 `qualified_no` 채우기 필요
- **알려진 한계**: 인용 손잡이(E001 등) 해소·미선언 인용은 검증하지만, **LLM이 실제로 쓴 인용문이 원문과 일치하는지는 아직 검증 안 함** — `explain()`이 답변 형식에 인용문 자체를 따로 뽑아내게 확장하고 `citation_guard.verify()`의 `quotes` 인자로 넘겨야 완성됨 (`tests/test_precheck_graph.py`의 `test_verify_citations_does_not_check_quote_content_yet`가 이 한계를 명시)