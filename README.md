# 보험 RAG 서비스

실손보험 RAG 프로토타입. LangChain/LangGraph 의존 없는 순수 함수로 구현, LangGraph Agent의 Tool로 호출될 예정.

- **`main_rag_service.py`** — Index A(보험 약관). 약관 판정 + 용어 설명.
- **`claim_rag_service.py`** — Index B(청구사례). 유사사례 통계 조회.

**Index A/B는 데이터·인덱스·함수 절대 공유 안 함** (판정 근거 등급이 다름 - A는 인용 가능, B는 통계 참고용).

## 전체 구조

```
                        사용자 질문
                            │
                            ▼
                    LangGraph Agent   ← 다른 팀원 담당 (이 저장소 밖)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
        보험 약관 RAG                  청구사례 RAG
        (Index A)                     (Index B)
              │                           │
      ┌───────┴───────┐                   ▼
      ▼               ▼         사례검색 → 집계(결정론) → LLM안내
   판정 UseCase     용어설명 UseCase      (answer_claim_question)
      │               │
  검색(top-N)      검색(top-N)
      │               │
  assess()        explain_term()
      │
  explain()
```

- `assess()`: kcd_codes 있으면 `kcd_ranges.py`(팀 저장소 원본, 그대로 복사)로 KCD 코드 범위 기준 면책/예외 판단. 없으면 조항 종류(면책/한도) 키워드 규칙으로 대체. 원단위 자기부담금·대기기간·세대차등화는 미구현(이유: PDF 표 추출 컬럼 뒤섞임 — docstring 참고)
- 검색은 top-1 아니라 top-N(`EVIDENCE_TOP_N`) 반환 — 관련 조항이 순위 밀려도 놓치지 않기 위함
- `explain()`/`explain_term()`: LLM에 JSON 강제 응답 시키고 `citation_guard.py`(팀 저장소 원본, 그대로 복사)의 `verify()`로 인용 검증. 실패하면 답변 폐기(`warnings`에 기록), **verdict는 안 바뀜**
- `citation_guard.py`/`kcd_ranges.py`는 **팀 저장소 파일을 그대로 복사한 것 - 수정 금지**. 둘 다 표준 라이브러리만 쓰는 순수 함수라 어댑터(`_to_evidence_clauses()`)만 거치면 팀 전용 타입 없이도 바로 동작함 (나중에 합칠 때 이 두 파일은 그대로 두고 어댑터만 교체하면 됨)

## 폴더 구조

```
insurance_rag/
├── file_config.py         # 공통 설정 (모델명/경로/토큰 등)
├── main_rag_service.py     # Index A
├── claim_rag_service.py    # Index B
├── citation_guard.py       # [팀 저장소 원본 그대로 복사, 수정 금지] 인용 검증
├── kcd_ranges.py           # [팀 저장소 원본 그대로 복사, 수정 금지] KCD 코드 면책 판단
├── requirements.txt / .env.example / .gitignore
├── main_rag_data/           # Index A 데이터 (*.pdf, *_chunks.json)
├── claim_rag_data/          # Index B 데이터 (claim_samples.json)
└── data_preprocessing/     # [보관용, 실행 안 됨] PDF→청크 변환 스크립트
```

## 실행

```bash
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # OPENAI_API_KEY 채우기

python main_rag_service.py    # Index A - 터미널 REPL로 질문 입력 테스트
python claim_rag_service.py   # Index B
```

## 네이밍 계약 (다른 팀원 연동용 — 반드시 이 이름 그대로 쓸 것)

**Index A 청크 스키마** (AI1 ↔ AI2 공유 계약, 가장 중요):

| 필드 | 의미 |
|---|---|
| `chunk_id` | 청크 고유 id |
| `title` / `body` | 조항 제목·본문 (실제 필드명은 `CHUNK_TITLE_FIELD`/`CHUNK_BODY_FIELD`로 설정) |
| `insurer`, `product_code`, `product_type` | 보험사, 상품코드, 상품유형(일반/노후/유병력자 등) |
| `source_file` | 원본 PDF 파일명 |

**Index B 청구사례 스키마**:

| 필드 | 의미 |
|---|---|
| `claim_id`, `insurer`, `generation`, `product_name` | 청구 식별·가입 정보 |
| `disease_code`, `disease_name` | KCD 코드·질병명 |
| `admission_type` | "입원" \| "통원" |
| `enrollment_date`, `claim_date` | 가입일·청구일 (YYYY-MM-DD) |
| `claim_amount`, `paid_amount` | 청구·지급 금액(원) |
| `result` | "승인" \| "부분승인" \| "거절" — `aggregate_cohort()` 집계 기준 |
| `denial_reason` | 거절/부분승인 사유 (승인이면 None) |

**`file_config.py` 변수**:

| 변수 | 의미 |
|---|---|
| `DATA_DIR`, `CHUNKS_SUFFIX` | Index A 경로 규칙 |
| `CHUNK_TITLE_FIELD`, `CHUNK_BODY_FIELD` | 청크 필드명 (전처리 필드명 바뀌면 여기만 수정) |
| `EMBEDDING_MODEL_NAME` | 임베딩 모델 — **임시값**, AI1 확정 시 교체 |
| `SEARCH_CANDIDATE_K` / `EVIDENCE_TOP_N` | 검색 후보수 / LLM에 넘길 evidence 개수 |
| `LLM_MODEL_NAME`, `LLM_MAX_TOKENS` | LLM 모델·응답 토큰 상한 |
| `MAX_CHUNK_CHARS_FOR_PROMPT` | 프롬프트용 조항 본문 길이 상한(입력 토큰 비용 통제) |

**함수 진입점**: `answer_question(request, chunks, index)` / `answer_term_question(...)` (Index A), `answer_claim_question(request, cases, index)` (Index B) — 전부 `(dict, list[dict], index) -> dict`. `answer_question()`의 `request`에 `kcd_codes`(예: `["F32"]`)를 넣으면 `assess()`가 `kcd_ranges.py`로 더 정확하게 판단함(선택 필드)

**verdict 4종**: `likely_covered`(보장가능) / `needs_documents`(조건부확인) / `unlikely`(면책가능성) / `needs_expert`(전문가확인, 기권) — 지금 `likely_covered`는 미사용(근거 부족한 긍정판정 금지)

**공통 출력 형식** (Index A):
```python
{"verdict": str|None, "verdict_label": str|None, "abstained": bool, "answer": str,
 "matched_chunks": [...], "warnings": [...], "error": str|None}
```

## 알려진 한계

- 임베딩 모델 미확정 (임시값, AI1 결과 대기)
- `assess()` 일부만 구현 (자기부담금·대기기간·세대차등화 미구현)
- 세대(1~5세대) 필터링 불가 (청크에 필드 없음)
- 현대해상 3개 상품만 검증됨
- top-N도 관련 조항이 그 안에 안 들면 놓침 (인용검증(`citation_guard`)은 팀 저장소 원본이라 견고하지만, 애초에 관련 조항이 검색에 안 잡히면 소용없음)
- Index B는 가상 샘플 50건뿐, 표본 부족
- `claim_samples.json` 자체에 내부 모순 있음 (감사 결과: 82%가 세대↔가입일 불일치, "승인" 건 전부 지급액이 청구액과 안 맞음) — 코드 문제 아니라 샘플 데이터 자체 결함, 재생성 필요
