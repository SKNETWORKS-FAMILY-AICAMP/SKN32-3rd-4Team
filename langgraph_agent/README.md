# langgraph_agent

실손보험 RAG 서비스의 **LangGraph + MCP 에이전트 파트**. 사용자 질문(질병기호/증상/약관 질문 등)을 받아서 의도를 분류하고, 필요한 도구를 호출한 뒤, 결과를 종합해 응답을 생성하는 전체 흐름을 담당한다.

**아키텍처**: 싱글 에이전트 + 툴콜링 구조 (멀티에이전트 아님).

이 폴더엔 그래프가 2개 있다:
- `graph/builder.py` — 5개 기능(약관/청구통계/유사사례/질병코드/용어) 의도분류 라우터. 초기 프로토타입.
- `graph/precheck_graph.py` — 계약(`06_계약_Agent.md`) 기준 사전판정 전용 그래프. resolve_policy→gate_document→retrieve→assess→explain→verify_citations, verdict는 판정 자체를 하지 않고 그대로 전달, 질병기호는 해시로 저장.

`assess`/`retrieve`는 아직 이 레포에 있는 것(자체 RAG 검색, 임시 규칙)으로 채운 자리표시이며, 실제 규칙엔진/검색 함수 연결 시 `precheck_graph.py`의 `build()` 내부만 교체하면 된다.

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
| `state.py` | 그래프 전체에서 공유되는 State 스키마(`InsuranceState`) 정의 |
| `builder.py` | `StateGraph` 조립. `route_after_mcp`가 `needs_fallback` 플래그로 성공/폴백 분기 |
| `router.py` | 5개 기능 의도분류(LLM) + 질문 텍스트에서 연령대/가입년도(세대) 추출 |
| `extractors.py` | 정규식 기반 연령대("30대")·가입년도→세대 추출 유틸(경계 연도는 `None`) + `resolve_generation_from_date`(정확한 날짜 기반, 경계 없음) |
| `precheck_domain.py` | 사전판정 도메인 타입: `Verdict`(4단계), `ReasonCode`(7종, 1:N 되묻기용 `AMBIGUOUS_PRODUCT_LINE` 포함), `Citation`, `ProductCandidate`, `PolicyResolution`, `PerCodeVerdict`, `PrecheckInput`/`PrecheckOutcome` |
| `precheck_graph.py` | 사전판정 그래프. `GraphState`(질병기호 해시 저장), `PrecheckGraph`(재시도 2회 상한), `verify_citations_in_message`(할루시네이션 인용 탐지). `kcd_codes` 여러 개 입력 시 코드별 개별 판정(`per_code[]`) 산출 후 최우선순위(가장 주의 필요한 것)로 대표 verdict 집계 |

## nodes/ — 각 단계별 실제 작업

| 파일 | 역할 |
|---|---|
| `mcp_caller.py` | 4개 MCP 도구 호출. 타임아웃(`ThreadPoolExecutor`)·재시도(일시적 오류만 1회)·intent별 독립 실패 처리·무폴백 판단(근거 하나도 없으면 `needs_fallback=True`) |
| `result_parser.py` | 4개 기능 전체의 출처(citations) 조립 |
| `judge_coverage.py` | 약관조항 + 청구통계 + 유사사례 + 용어설명을 종합해 LLM이 최종 응답 생성. 질병코드 후보가 여럿이면 확정하지 않고 "확인 필요"로 안내 |
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
| `test_graph_flow.py` | 전체 그래프 시나리오 테스트. LLM/벡터DB를 monkeypatch로 대체해서 **API 키 없이도 실행 가능** |
| `test_precheck_graph.py` | `precheck_graph.py` 오케스트레이션(정상흐름/각 abstain 사유코드/재시도 성공·소진·중복방지/인용 검증) |

## 최상위 파일

| 파일 | 역할 |
|---|---|
| `config.py` | 모델명, 벡터DB 경로, MCP 타임아웃 등 설정값. `.env` 자동 로드 |
| `main.py` | 그래프 실행 진입점 |
| `.env.example` | `OPENAI_API_KEY` 등 필요한 환경변수 예시 |
| `requirements.txt` | 필요 패키지 (langchain, langgraph, chromadb, sentence-transformers, pytest, python-dotenv 등) |

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
- `verify_citations_in_message`의 조항번호 정규식(`제N조`)은 우리 자체 청킹 형식 기준. 실제 AI1 검색 결과의 `article_no` 형식이 다르면(예: 스토리보드 예시의 `"보통약관/4.1"`) 이 정규식도 같이 교체 필요 — 안 그러면 진짜 인용도 검증 실패로 잘못 걸러짐