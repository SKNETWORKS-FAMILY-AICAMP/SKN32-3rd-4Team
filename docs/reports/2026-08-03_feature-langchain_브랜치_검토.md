# `feature-langchain` 브랜치 검토 — 그래프가 두 개다

작성 2026-08-03 · 코덱스 교차검증 · **검토만 수행. 해당 저장소는 건드리지 않았다**

대상: `SKNETWORKS-FAMILY-AICAMP/SKN32-3rd-4Team` 브랜치 `feature-langchain`, 경로 `langgraph_agent/`
작성자: 정재희(Agent 담당) · 커밋 `6cb60a6` "LangGraph 에이전트 파트 구현: 5개 기능 라우터 + 계약 기준 사전판정 그래프"

---

## 1. 무엇이 올라왔나

`main` 대비 **ahead 3 커밋 · 36파일 · +2,361줄 · 삭제 0** — 전부 신규다.

| 묶음 | 파일 | 줄 |
|---|---|---:|
| **그래프 B — 계약 기준 사전판정** | `graph/precheck_graph.py` · `precheck_domain.py` | 496 |
| **그래프 A — 5기능 라우터 챗** | `graph/builder.py` · `router.py` · `state.py` · `extractors.py` | 320 |
| 노드 | `nodes/mcp_caller.py` · `judge_coverage.py` · `result_parser.py` · `knowledge_gap.py` | 335 |
| MCP 도구 | `mcp_tools/` 5개 서버 | 169 |
| RAG | `rag/chunking.py` · `search_policy.py` · `build_vectorstore.py` | 189 |
| 테스트 | `tests/` 5개 | 456 |
| 기타 | `README.md` · `config.py` · `main.py` · `requirements.txt` · 샘플 약관 1건 | 316 |

**테스트를 456줄 함께 올린 것**은 이 팀 기준으로 드문 일이고, 좋다.

---

## 2. ★핵심 발견 — 그래프가 두 개이고, 위험한 쪽이 기본 경로다

```
그래프 A  (graph/builder.py — main.py 가 부르는 것)
   START → router → mcp_caller → result_parser → ⟨분기⟩ → judge_coverage → END
                                                        └→ knowledge_gap → END
   · judge_coverage = 자유 텍스트 LLM 답변. ★인용 검증 없음
   · router 의 policy_rag intent = "약관 조항, 보장 내용, 면책 사항에 대한 질문"

그래프 B  (graph/precheck_graph.py — 계약 충실 구현)
   normalize → rules → verify_citations(★재시도) → END
   · Verdict/ReasonCode · abstained=True · citations=() · 질병기호 해시 · 표적 재검색 1회
```

**B 는 잘 만들었다. 그런데 사용자가 "우울증 보장되나요?"라고 물으면 A 로 간다.**
보장 판단의 안전장치는 B 에 있고, 보장 질문은 A 가 받는다. 이게 이 브랜치의 구조적 문제다.

---

## 3. P0 결함 — 코드로 확인한 것

### 3-1. ★한 intent 라도 결과가 있으면 근거 없이 보장 답변을 만든다

`nodes/mcp_caller.py`:

```python
found_any_result = found_any_result or bool(clauses)      # policy_rag
found_any_result = found_any_result or bool(candidates)   # disease_lookup
...
if not found_any_result:
    updated_state["needs_fallback"] = True
```

**`or` 로 누적한다.** 실패 시나리오가 즉시 나온다:

```
"우울증 보장되나요?"  → intent = [disease_lookup, policy_rag]
   disease_lookup : F32·F33 후보 찾음   → found_any_result = True
   policy_rag     : 약관 조항 0건
→ needs_fallback = False → judge_coverage 로 진행
→ LLM 은 "관련 약관 조항: 없음" 을 받고 보장 질문에 답하게 된다
```

막는 것은 프롬프트 한 줄(*"추측하지 말고 확인 불가라고 답하세요"*)뿐이다.
`docs/reports/2026-08-01_판정_정직성_인용검증_설계.md` §2가 지적한 상태 그대로다 —
**프롬프트는 지켜지길 바라는 것이지 강제되는 것이 아니다.**

### 3-2. ★약관 조항과 통계·사례·용어가 같은 `citations` 에 들어간다

`nodes/result_parser.py`:

```python
citations.append(f"{clause.get('generation')} {clause.get('article_no')}(...)")   # 약관
citations.append(f"유사청구사례({case...}): {case.get('result')}")                  # 외부 사례
citations.append(f"청구승인통계: {stats.get('approved')}/{stats.get('total')}건 승인")  # 집계
citations.append(f"용어사전: {term.get('term')}")                                   # 용어
```

`03_에이전트_데이터_축적_설계.md` §1이 **코드로 강제하라고 한 것**을 정면으로 어긴다:

```python
POLICY_CLAUSE   = "policy_clause"     # 약관 원문 — 유일하게 판정 근거가 된다
EXTERNAL_REPORT = "external_report"   # 외부 보고 — 참고만
STATISTICS      = "statistics"        # 집계 — 참고만
```

★**결과**: 약관 조항이 0건이어도 `citations` 가 비어 있지 않으므로 "근거가 있다"로 보인다.
사용자 화면에서도 "제9조"와 "유사청구사례"가 **같은 출처 목록에 나란히** 붙는다.
스토리보드 ⑤가 `tier="policy_clause"` 인 것만 판정 근거라고 못박은 지점이다.

### 3-3. `citations` 가 문자열이라 원문을 찾아갈 수 없다

`state.py` — `citations: list[str]`. `clause_id` · 문서 sha · 페이지가 없다.
`08_계약_프론트.md` 의 필수 3요소(적용 약관 · 조항번호와 쪽수 · 인용문) 중 쪽수가 빠지고,
**같은 조항번호가 여러 특약에 존재할 때 어느 것인지 특정할 수 없다**
(우리 실측: `qualified_no` 문서내 중복 31,085건).

---

## 4. P1 결함

| # | 내용 | 근거 |
|---|---|---|
| 4-1 | **라우터 파싱이 `TypeError` 로 죽는다** — `json.loads("null")` 은 예외를 안 내고 `None` 을 준다. 그런데 리스트 컴프리헨션이 `try` 밖에 있어 순회에서 터진다 | `router.py:70-78` |
| 4-2 | **분류 실패 기본값이 `policy_rag`** — 하필 가장 위험한 경로가 기본값이다. 주석은 "라우팅 기본값이지 답변을 지어내는 것이 아니다"라고 하지만, §3-1 때문에 실제로는 답변까지 간다 | `router.py:77-78` |
| 4-3 | **일부 도구 실패가 조용히 사라진다** — `except Exception` 으로 잡아 `errors` 에만 넣고, 다른 intent 가 성공하면 진행한다. `error` 는 `judge_coverage` 프롬프트에도 최종 답변에도 안 들어간다 | `mcp_caller.py:140-141` |
| 4-4 | **그래프 A 상태에 원문 민감정보가 그대로 남는다** — `user_query` · `disease_code` · `disease_name`. B 의 `_hash_code()` 가 A 에는 없다. 계약 `06` §1 "상태에 원문 개인정보 저장 금지" 위반 | `state.py:32-37` |
| 4-5 | **`ReasonCode` 대소문자가 섞였다** — `NOT_RESOLVED`·`DOCUMENT_NOT_RELIABLE` 은 대문자, `no_version_at_date`·`insurer_not_supported` 는 소문자. 우리 정본(`app/schemas/precheck.py`)은 전부 소문자다 | `precheck_domain.py:24-31` |
| 4-6 | **정본과 갈라진 중복 구현** — `06_계약_Agent.md` 가 *"`app/workflow/precheck_graph.py` — 이미 존재한다. 새 위치에 다시 만들지 말 것"* 이라 했는데 별도 `Verdict`·`ReasonCode`·`Citation`·`PrecheckOutcome` 을 새로 정의했다. **"REST 가 정본, MCP 는 같은 유스케이스를 부른다"는 계약이 깨진다** | `precheck_domain.py` 전체 |
| 4-7 | **B 의 토폴로지가 계약 노드를 감췄다** — 계약은 `resolve_policy → gate_document → retrieve → assess → explain → verify_citations` 인데 구현은 `normalize → rules → verify_citations`. `rules` 안에서 순차 호출하더라도 **단계별 분기·감사 지점이 사라진다** | `precheck_graph.py:60,164` |

**P2**: `_call_with_timeout()` 이 타임아웃 후 future 를 취소하지 않아 `ThreadPoolExecutor(max_workers=4)` 스레드를 계속 점유한다. 4회면 이후 정상 호출도 막힌다.

---

## 5. 잘한 점

- **그래프 B 는 계약을 충실히 구현했다** — `abstained=True` 와 함께 `citations=()` 로 비우는 태도,
  질병기호 해시, 재시도 1회 제한, 자율 ReAct 미사용. 방향이 맞다
- **질병코드 후보가 여러 개면 임의로 고르지 않는다** — `disease_candidates` 를 따로 두고
  프롬프트에도 "하나를 임의로 골라 확정 짓지 말라"를 넣었다. 계약 `팀MVP6 §2-4` 그대로다
- **목업 통계를 근거로 세지 않는다** — `stats.get("_mock")` 이면 `citations` 에서 뺀다
- **`knowledge_gap` 이 고정 응답만 낸다** — LLM 을 부르지 않는다
- **테스트 456줄을 함께 올렸다**

★그런데 **이 안전장치들이 A 의 보장 답변 경로에는 이어지지 않았다.**

---

## 6. 조치 — 우선순위

| | 조치 | 왜 |
|---|---|---|
| **P0** | A 의 `policy_rag` 가 **보장·면책 결론을 만들지 못하게** 막고, 보장 질문은 사전판정 경로로 강제 라우팅 | 지금은 근거 0건에도 답이 나간다 |
| **P0** | `found_any_result` 폐기 → **intent 별 필수 결과 검사.** 보장 질문은 "약관 버전 확정 + 검증된 조항 + 규칙 판정"이 **모두** 있어야 진행 | §3-1 |
| **P0** | `judge_coverage` 에서 **판정 생성을 제거.** LLM 은 규칙엔진이 정한 verdict 를 **설명만** 하고, 설명이 인용 검증을 통과 못 하면 폐기 | 계약 `05` §3 |
| **P0** | `citations` 에서 통계·사례·용어를 **분리.** 약관 조항만 판정 근거 타입으로 허용 | §3-2 |
| **P1** | 새 도메인 DTO 대신 **정본(`app/core/domain`·`app/schemas/precheck.py`) 재사용**, `app/workflow/precheck_graph.py` 에 연결 | §4-6 |
| **P1** | 라우터 파싱 실패·부분 도구 실패를 **명시적 기권**으로. `policy_rag` 기본값 폐기 | §4-1·4-2·4-3 |
| **P1** | A 상태에서 원문 질문·질병기호 제거 또는 비식별화 | §4-4 |
| **P1** | `citations` 를 문자열에서 **구조화 타입**으로(`clause_id`·sha·페이지) | §3-3 |
| **P2** | 타임아웃 작업 격리 + 요청 단위 재시도 예산 | |

**병합 조건으로 둘 회귀 테스트** (코덱스 제안, 채택):
`질병조회 성공 + 약관 0건` · `약관 오류 + 용어 성공` · `세대 미확정` · `무관한 top-k` ·
`가짜 조항번호` · `router 가 null/1 반환` · `상태에 원문 KCD 없음`

---

## 7. 한계 (정직 기록)

- **테스트를 실행하지 않았다.** 456줄이 무엇을 덮는지는 파일명·구조로만 판단했다
- 36파일 중 **11개 소스만 정독**했다(핵심 경로 위주). `extractors.py` · `chunking.py` ·
  `build_vectorstore.py` · MCP 서버 5개 · 테스트 5개는 훑기만 했다
- 이 검토는 **우리 저장소의 계약 문서를 기준**으로 한 것이다. 그 계약 자체가 최근까지
  코드와 갈라져 있었으므로(오늘 정정), **작성자가 옛 계약을 보고 구현했을 수 있다** —
  특히 §4-6(정본 재사용)은 `06_계약_Agent.md` 의 해당 문장이 **2026-08-02 에 추가**됐다
- 브랜치를 로컬에 clone 하지 않고 GitHub API·raw 로만 읽었다

---

## 참조

- 브랜치: `https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN32-3rd-4Team/tree/feature-langchain/langgraph_agent`
- `docs/handoff/06_계약_Agent.md` — LangGraph 파이프라인 계약
- `docs/handoff/05_계약_AI2_판정.md` — 판정·인용 검증
- `docs/handoff/03_에이전트_데이터_축적_설계.md` §1 — `EvidenceTier`
- `docs/reports/2026-08-01_판정_정직성_인용검증_설계.md` — 프롬프트를 방어선으로 삼지 않는다
