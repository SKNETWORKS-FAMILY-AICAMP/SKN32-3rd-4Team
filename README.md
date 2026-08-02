# 올바른 보험비서

진료비 내역서의 **KCD 질병기호**와 **실손보험 약관**을 대조해
**보장 여부를 미리 알려주는** 서비스. 그 판정을 API로도 제공한다.

팀 **비서단** — 송채영(팀장) · 김지혜 · 서유현 · 정재희 · 최연우

---

## 제1원칙 — 모르면 모른다고 한다

**"보장됩니다"라고 잘못 말하면 사용자가 청구했다가 거절당하거나, 받을 걸 포기한다.**
그래서 정확도보다 **정직성**이 앞선다.

- 근거 조항을 못 대면 `verdict="needs_expert"` 로 답한다. 이건 **정상 결과**다(HTTP 200)
- **면책 목록에 없다 ≠ 보장된다.** 보장은 '보상하는 사항' 조항이 정한다
- 가입 시점 약관을 못 찾았을 때 **현행 약관으로 대신하지 않는다** — 가장 위험한 폴백이다
- 추론과 사실을 구분해 저장한다(`date_confidence`, `inferred`, `verification`)
- 외부에서 받은 데이터를 약관과 같은 근거로 쓰지 않는다(`evidence_tier`)

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md).

---

## 빠른 시작

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
# 무엇을 지원하는지
curl localhost:8000/v1/support-manifest

# 보장 사전판정
curl -X POST localhost:8000/v1/prechecks -H 'Content-Type: application/json' -d '{
  "insurer": "DB손해보험",
  "enrolled_on": "20200301",
  "kcd_codes": ["F32", "E66", "S72"],
  "product_name": "프로미라이프 실손의료비"
}'
```

응답 예:

```json
{
  "verdict": "unlikely",
  "abstained": false,
  "reason_code": "excluded_by_clause",
  "applied_policy": {
    "insurer": "DB손해보험", "generation": 3, "generation_label": "3세대 (착한실손)",
    "sale_start": "20200101", "product_name": "무배당 프로미라이프 실손의료비보험2001"
  },
  "per_code": [
    {"code": "F32", "verdict": "needs_documents", "note": "면책의 예외에 해당합니다…"},
    {"code": "E66", "verdict": "unlikely",        "note": "면책 조항에 해당합니다."},
    {"code": "S72", "verdict": "needs_expert",    "note": "면책 조항에는 없습니다. 다만…"}
  ],
  "citations": [{"qualified_no": "보통약관/4.1", "page_from": 33, "page_to": 38, "quote": "…"}],
  "trace_id": "744154edbbe8a46e"
}
```

---

## 지금 있는 것

| 항목 | 값 |
|---|---:|
| 수집한 실손약관 | 1,703문서 (12개사) |
| 판정 대상 | 1,367 (격리 336 제외) |
| 조항 구조화 완료 | 1,240 (`parse_status=ok`) |
| 조항 총수 | 129,525 |
| 세대 판정 | 1~5세대 |

> ⚠ **약관 원문·파생물은 이 저장소에 없다.** 저작물이라 재배포하지 않는다.
> 매니페스트(메타데이터)만 들어 있다 — 출처 URL 이 있으므로 각자 받으면 된다.

### ★약관이 KCD 코드를 직접 쓴다

이게 이 프로젝트의 핵심 자산이다. 표본 300문서 중 **239개(80%)** 에 코드가 있다.

```
② 회사는 '한국표준질병사인분류'에 따른 다음의 의료비에 대해서는 보상하지 않습니다.
   ① 정신 및 행동장애(F04∼F99). 다만, F04∼F09, F20∼F29 …는 보상합니다.
   ⑤ 비만(E66)   ⑥ 요실금(N39.3, N39.4, R32)
```

**외부 KCD 표 없이 면책 판정이 된다.** 진료비 내역서에도 코드가 적혀 있으므로 이게 주 경로다.

---

## 구조

```
app/
  core/                                        ← ★프레임워크도 바깥도 모른다
    domain/     kcd_ranges · citation_guard · policy_naming
                precheck_result · insurance · generation
    ports/      precheck · insurance           ← 바깥에 요구하는 것
    usecases/   precheck · cohort · diagnosis  ← 판정 흐름
  adapters/     manifest_policy_resolver · file_clause_store  ← 파일 I/O
  schemas/      precheck · auth                ← HTTP DTO (pydantic)
  routers/      precheck · auth · admin · health …
                ↑ 도메인 ↔ HTTP 변환은 여기서 한다
scripts/
  crawl/        약관 수집·매니페스트·세대 판정
  extract/      PDF → 페이지 JSON → 조항 JSON
docs/
  handoff/      ★팀 인수인계 — 계약서·ERD·설계
  reports/      작업 기록·디버그
```

### 클린 아키텍처 — 테스트로 강제한다

```
ARCH-001  app/application 이 fastapi·langchain·sqlalchemy·openai 를 import 안 함
ARCH-002  app/core/{domain,ports,usecases} 가 프레임워크도 바깥 계층도 모름
          (app.adapters · app.routers · app.schemas · app.db …)
ARCH-003  경계 밖 도메인 패키지 금지 · 도메인 타입 단일 정의 · 유스케이스가 어댑터 import 금지
ARCH-004  현행 코드가 legacy/ 를 참조하지 않음
```

```bash
pytest tests/test_arch.py
```

---

## 팀원별 문서

[`docs/handoff/`](docs/handoff/) 에 있다. **각자 것을 먼저 읽으라.**

| 문서 | 대상 |
|---|---|
| [01_데이터_현황](docs/handoff/01_데이터_현황.md) | 전원 |
| [02_ERD_및_스키마](docs/handoff/02_ERD_및_스키마.md) | 백엔드 |
| [03_에이전트_데이터_축적_설계](docs/handoff/03_에이전트_데이터_축적_설계.md) | 전원 |
| [04_계약_AI1_검색](docs/handoff/04_계약_AI1_검색.md) | 서유현 |
| [05_계약_AI2_판정](docs/handoff/05_계약_AI2_판정.md) | 송채영 |
| [06_계약_Agent](docs/handoff/06_계약_Agent.md) | 정재희 |
| [07_계약_백엔드](docs/handoff/07_계약_백엔드.md) | 김지혜 |
| [08_계약_프론트](docs/handoff/08_계약_프론트.md) | 최연우 |
| [09_A2A_판단](docs/handoff/09_A2A_판단.md) | 전원 |
| `erd_briefing.html` | 브라우저로 열기 |

---

## 아직 안 된 것 (정직 기록)

| 항목 | 상태 |
|---|---|
| 임베딩 검색 | 없다. 낱말 포함 검색만 한다 |
| 준용 해소 | 참조의 **2/3이 문서 밖**을 가리키는데 아직 안 따라간다 |
| 질병명 → 코드 | 없다. 코드 입력만 받는다 |
| 표(table) 의미 | 셀만 뽑았다. **보장 한도·자기부담금이 표에 있다** |
| 조 번호 충돌 | 부까지 포함해도 겹친다. 식별키 개선 필요 |
| LLM 판정 | 없다. 지금은 규칙 기반이다. 붙일 때 `verify_explanation()` 을 반드시 통과시킨다 |
| DB 적재 | 아직 파일을 직접 읽는다 |

---

## 이 저장소의 내력

쇼핑몰 실습(`_unified_mall`)에서 출발해 보험 도메인으로 전환했다.
커머스 코드는 **삭제하지 않고** 로컬 `legacy/` 에 압축 보관한다(저장소에는 올리지 않는다).
현행 코드가 레거시를 참조하지 않도록 `ARCH-004` 가 막는다.
