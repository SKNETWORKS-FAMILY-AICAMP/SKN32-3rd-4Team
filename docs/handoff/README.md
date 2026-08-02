# 인수인계 문서 (handoff)

팀 **비서단** — 올바른 보험비서. 각자 작업에 필요한 확정 사항을 모아 둔다.

> 여기 있는 것은 **합의된 계약**이다. 바꾸려면 팀에 알리고 버전을 올린다.
> 리포트(`docs/reports/`)는 "무슨 일이 있었나"의 기록이고, 여기는 "무엇을 지킬 것인가"다.

---

## 문서 목록

| 문서 | 대상 | 내용 |
|---|---|---|
| [01_데이터_현황.md](01_데이터_현황.md) | 전원 | 지금 무엇이 있고 무엇을 믿을 수 있나 |
| [02_ERD_및_스키마.md](02_ERD_및_스키마.md) | 백엔드 | 엔티티·관계·DDL — ★**2026-08-02 전면 개정** |
| [03_에이전트_데이터_축적_설계.md](03_에이전트_데이터_축적_설계.md) | 전원 | 외부 에이전트 데이터를 어떻게 받고 쌓고 쓰나 |
| [04_계약_AI1_검색.md](04_계약_AI1_검색.md) | 서유현 | 검색 담당 인터페이스 |
| [05_계약_AI2_판정.md](05_계약_AI2_판정.md) | 송채영 | 판정·설명 담당 인터페이스 |
| [06_계약_Agent.md](06_계약_Agent.md) | 정재희 | LangGraph·MCP 담당 인터페이스 |
| [07_계약_백엔드.md](07_계약_백엔드.md) | 김지혜 | DB·API·감사 담당 인터페이스 |
| [08_계약_프론트.md](08_계약_프론트.md) | 최연우 | 화면 상태표 |
| [09_A2A_판단.md](09_A2A_판단.md) | 전원 | 에이전트 간 위임을 할 것인가 |
| [10_계약_모델_평가.md](10_계약_모델_평가.md) | 서유현·송채영 | **모델 평가 지표·평가셋·색인 입력 계약** |
| [11_AI_구조_지도.md](11_AI_구조_지도.md) | 전원 | ★**RAG는 몇 개인가 · 무엇이 무엇을 근거로 쓰나 · 역할 구분** — 반복 질문 한 장 정리 |
| [12_모델팀_개선사항.md](12_모델팀_개선사항.md) | 서유현·송채영 | ★**`feature-ai1` 점검 결과 — 재색인 전 고칠 것** (P0 1건 · P1 7건 · P2 2건) |
| [erd_briefing.html](erd_briefing.html) | 전원 | ERD·스키마 브리핑 — **왜 이렇게 설계했나**(브라우저로 열기) |
| [erd_tables.html](erd_tables.html) | 백엔드·전원 | ★**테이블·컬럼 사전** — 27테이블+뷰1의 전 컬럼·타입·제약·enum(브라우저로 열기) |
| [system_diagrams.html](system_diagrams.html) | 전원 | ★**시스템 시각화 6장** — 아키텍처·오프라인/온라인·기권 게이트·실패 전파·검증 확장·12GB 예산(브라우저로 열기) |
| [preprocess_viz.html](preprocess_viz.html) | 모델팀·전원 | ★**전처리 v5 산출물 시각화** — 그림 7장 + DB 적재 정합성 + Tad 행 단위 캡처 5장(브라우저로 열기) |
| [storyboard.html](storyboard.html) | 전원 | **데모 흐름 스토리보드(브라우저로 열기)** |

---

## 지금 바로 쓸 수 있는 것

```bash
# 서버 띄우기
uvicorn app.main:app --reload

# 무엇을 지원하는지
curl localhost:8000/v1/support-manifest

# 판정 요청
curl -X POST localhost:8000/v1/prechecks -H 'Content-Type: application/json' -d '{
  "insurer": "DB손해보험",
  "enrolled_on": "20200301",
  "kcd_codes": ["F32", "E66", "S72"],
  "product_name": "프로미라이프 실손의료비"
}'
```

---

## 전처리 산출물을 직접 뒤져 보려면

집계는 [preprocess_viz.html](preprocess_viz.html) 로, **행 단위 탐색은 Parquet + Tad** 로 나눴다.
수십만 행을 단일 HTML 에 넣으면 파일 크기와 브라우저 메모리가 문제가 된다.

**Tad** — 무료(MIT) · DuckDB 기반 · Parquet 를 그냥 더블클릭해서 정렬·필터·피벗한다.
[tadviewer.com](https://www.tadviewer.com/) 에서 Windows 설치파일을 받는다.

| 파일 | 내용 |
|---|---|
| `data/exports/s5_clauses.parquet` | **211,131행 · 22컬럼.** 조항 본문 + `reuse_docs`(재사용 문서 수) · `para_ambiguous` · `statute` |
| `data/exports/s5_documents.parquet` | 1,367행. 문서별 쪽수·조항수·항수·suspect·모호·미해결 |
| `data/exports/views/v1~v5.parquet` | ★**행 단위로만 보이는 것 5개.** HTML §H 의 캡처와 같은 화면이 그대로 열린다 |

```
v1_clause_boundary  조항 경계 붕괴 (30,000자 초과 133행)
v2_page_fallback    페이지 덩어리 438행 — 조항이 아니다
v3_reuse            170문서에 실린 같은 조항 2,843행
v4_para_marker      항 표지 충돌 2,795행
v5_pua              못 읽은 보조 PUA 515행 — 문맥 스니펫 포함
```

`s5_clauses.parquet` 에서 `reuse_docs` 내림차순 정렬 → 중복 조항,
`para_ambiguous=true` 필터 → 인용 못 대는 조항 9,838건이 바로 나온다.

---

## 이 프로젝트의 제1원칙

**모르면 모른다고 한다.**

"보장됩니다"라고 잘못 말하면 사용자가 청구했다가 거절당하거나, 받을 걸 포기한다.
그래서 정확도보다 **정직성**이 앞선다.

- 근거 조항을 못 대면 `verdict="needs_expert"` · `abstained=true` 로 답한다. 이건 **정상 결과**다(HTTP 200).
- **면책 목록에 없다 ≠ 보장된다.** 보장은 '보상하는 사항' 조항이 정한다.
- 추론과 사실을 구분해 저장한다(`date_confidence`, `inferred`, `verification`).
- 외부에서 받은 데이터를 약관과 같은 근거로 쓰지 않는다(`evidence_tier`).

자세한 것은 저장소 루트 [CLAUDE.md](../../CLAUDE.md) 를 보라.
