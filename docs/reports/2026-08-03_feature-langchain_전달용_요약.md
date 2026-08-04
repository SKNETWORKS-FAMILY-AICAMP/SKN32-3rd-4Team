# `feature-langchain` 리뷰 — 정재희님께

2026-08-03 · 전체 근거: [`브랜치 검토 리포트`](2026-08-03_feature-langchain_브랜치_검토.md)

---

## 먼저

**계약서가 틀린 상태에서 구현하셨습니다. 그 부분은 제 잘못입니다.**

`06_계약_Agent.md` 가 산출물 위치를 `app/insurance/graph.py` 라고 적어놨는데 **그런 경로는 없습니다.**
"이미 `app/workflow/precheck_graph.py` 에 있으니 새로 만들지 말 것"으로 **2026-08-02 에야 고쳤습니다.**
`verdict` enum 도 계약서 4값이 코드에 없는 값이었고 어제 정정했습니다.

아래 지적 중 **"정본을 재사용하라"는 항목은 이 문제 때문**이니 감안해서 봐주세요.

---

## 잘 된 것

- **그래프 B(`precheck_graph.py`)는 계약을 충실히 구현했습니다.** `abstained=True` 와 함께
  `citations=()` 로 비우는 처리, 질병기호 해시, 재시도 1회 제한, 자율 ReAct 미사용 — 방향이 맞습니다
- **질병코드 후보를 임의로 안 고릅니다.** `disease_candidates` 를 따로 두고 프롬프트에도 넣으신 것,
  `팀MVP6 §2-4` 그대로입니다
- **목업 통계를 근거에서 뺍니다**(`stats.get("_mock")`)
- **`knowledge_gap` 이 LLM 을 안 부릅니다** — 고정 응답만
- **테스트 456줄을 함께 올리셨습니다**

---

## ★핵심 문제 하나 — 안전장치가 있는 쪽으로 질문이 안 갑니다

```
그래프 A (main.py 가 부름)   router → mcp_caller → result_parser → judge_coverage
                              · 자유 텍스트 LLM 답변, 인용 검증 없음
그래프 B (계약 충실)          normalize → rules → verify_citations
                              · abstained · 해시 · 재시도 제한  ← 여기 다 있음
```

**"우울증 보장되나요?" 는 A 로 갑니다.** router 의 `policy_rag` intent 정의가
*"약관 조항, 보장 내용, 면책 사항에 대한 질문"* 이라서요.

B 를 잘 만드셨는데 **보장 질문이 B 를 안 거칩니다.** 아래 P0 는 전부 이 한 줄기입니다.

---

## P0 — 4건

### 1. `found_any_result` 가 `or` 로 누적됩니다 ★가장 급함

`nodes/mcp_caller.py`

```python
found_any_result = found_any_result or bool(clauses)      # policy_rag
found_any_result = found_any_result or bool(candidates)   # disease_lookup
```

**한 intent 만 성공해도 통과합니다.**

```
"우울증 보장되나요?"  →  intent = [disease_lookup, policy_rag]
   disease_lookup : F32·F33 찾음   → True
   policy_rag     : 약관 조항 0건
→ needs_fallback = False → judge_coverage 진행
→ LLM 은 "관련 약관 조항: 없음" 을 받고 보장 질문에 답하게 됩니다
```

막는 건 프롬프트 한 줄(*"추측하지 말고 확인 불가라고"*)뿐입니다.

**고칠 방향**: intent 별 **필수 결과**를 따로 검사. 보장 질문은
`약관 버전 확정 + 조항 ≥ 1` 이 없으면 `knowledge_gap` 으로.

### 2. 약관 조항과 통계·사례·용어가 같은 `citations` 에 들어갑니다

`nodes/result_parser.py`

```python
citations.append(f"{clause...}")                      # 약관 조항
citations.append(f"유사청구사례(...): {result}")        # 외부 사례
citations.append(f"청구승인통계: 33/40건 승인")          # 집계
citations.append(f"용어사전: {term}")                   # 용어
```

`03_에이전트_데이터_축적_설계.md` §1 의 `EvidenceTier` 가 **약관만 판정 근거**로 못박은 부분입니다.
지금 구조에선 **약관이 0건이어도 `citations` 가 안 비어서 "근거 있음"으로 보입니다.**
화면에서도 "제9조"와 "유사청구사례"가 같은 목록에 나란히 붙습니다.

**고칠 방향**: 판정 근거(`citations`)와 참고(`references`)를 **분리**. 약관만 전자에.

### 3. `judge_coverage` 가 판정을 만듭니다

LLM 이 자유 텍스트로 답을 씁니다. 계약(`05_계약_AI2_판정.md`)은
**판정은 규칙엔진이 소유하고 LLM 은 설명만** 쓰도록 돼 있습니다.

**고칠 방향**: verdict 는 규칙이 정하고, LLM 은 그 verdict 를 설명만.
설명이 인용 검증을 통과 못 하면 **설명을 버리고 verdict 는 유지**합니다.
검증기는 이미 있습니다 — `app/core/domain/citation_guard.py` 의 `verify()`.

### 4. `citations` 가 문자열이라 원문을 못 찾아갑니다

`clause_id` · 문서 sha · 페이지가 없습니다. **같은 조항번호가 여러 특약에 있으면 특정 불가**입니다
(실측: 문서내 조항번호 중복 **31,085건**).

**고칠 방향**: 구조화 타입으로. `08_계약_프론트.md` 의 필수 3요소 —
적용 약관 · **조항번호와 쪽수** · 인용문.

---

## P1 — 7건 (요약)

| | 내용 | 위치 |
|---|---|---|
| 1 | `json.loads("null")` 은 예외가 아니라 `None` 을 줍니다 → 리스트 컴프리헨션이 `try` 밖이라 `TypeError` | `router.py:70-78` |
| 2 | 분류 실패 기본값이 하필 `policy_rag` — 가장 위험한 경로입니다 | `router.py:77` |
| 3 | `except Exception` 후 다른 intent 가 성공하면 진행. `error` 가 프롬프트·최종답변에 안 들어갑니다 | `mcp_caller.py:140` |
| 4 | 그래프 A 상태에 `user_query`·`disease_code` 원문 그대로. B 의 `_hash_code()` 가 A 엔 없습니다 | `state.py:32-37` |
| 5 | `ReasonCode` 대소문자 혼재 (`NOT_RESOLVED` vs `no_version_at_date`). 정본은 전부 소문자 | `precheck_domain.py:24` |
| 6 | 정본과 갈라진 `Verdict`·`ReasonCode`·`Citation` 재정의 → **위 "먼저" 참조** | `precheck_domain.py` |
| 7 | B 토폴로지가 `normalize → rules → verify` 로 압축돼 계약의 단계별 분기·감사 지점이 사라짐 | `precheck_graph.py:60` |

**P2**: `_call_with_timeout()` 이 타임아웃 후 future 를 취소하지 않아 스레드 4개가 잠기면 이후 호출도 막힙니다.

---

## 제안하는 순서

1. **`found_any_result` 를 intent 별 필수 결과 검사로** ← 한 곳 고치면 §1 이 사라집니다
2. **`citations` 분리** (판정 근거 / 참고)
3. **보장 질문을 B 경로로** 라우팅
4. `judge_coverage` 를 설명 전용으로 + `citation_guard.verify()` 연결
5. P1 은 그다음

**1·2 는 각각 한 파일이고 반나절 안 걸릴 겁니다.** 3·4 가 구조 변경이라 상의가 필요합니다.

---

## 회귀 테스트로 넣어주시면 좋을 것

```
질병조회 성공 + 약관 0건        → knowledge_gap 이어야 한다
약관 오류 + 용어 성공           → 실패 사실이 사용자에게 보여야 한다
세대 미확정                     → 되묻거나 기권
무관한 top-k                    → 근거로 세지 않는다
가짜 조항번호                   → 인용 검증에서 폐기
router 가 null / 1 을 반환      → TypeError 로 죽지 않는다
상태에 원문 KCD 가 없다
```

---

## 한계

- **테스트를 실행하지 않았습니다.** 456줄이 무엇을 덮는지는 파일명·구조로만 봤습니다
- 36파일 중 **11개만 정독**했습니다(핵심 경로 위주). `extractors` · `chunking` ·
  MCP 서버 5개 · 테스트 5개는 훑기만 했습니다
- 브랜치를 clone 하지 않고 GitHub API·raw 로 읽었습니다
- 검토 기준은 **우리 계약 문서**인데, 그 계약이 최근까지 코드와 갈라져 있었습니다(위 "먼저")
