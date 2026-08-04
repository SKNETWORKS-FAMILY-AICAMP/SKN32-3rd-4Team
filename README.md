# 올바른 보험비서

> KCD 질병기호와 실손보험 약관을 근거로 가입 전 보장 가능성을 확인하는 RAG 기반 보험 상담 플랫폼

`올바른 보험비서`는 보험 약관에서 관련 조항을 검색하고, 가입자의 질병기호·보험사·상품 세대를 함께 대조해 판단 근거와 확인이 필요한 항목을 제공하는 팀 프로젝트입니다. 근거가 없거나 데이터 상태가 불완전하면 그럴듯한 답을 만들지 않고 명시적으로 중단하는 **무폴백(fail-closed)** 원칙을 적용합니다.

## 현재 릴리스

| 항목 | 적용 상태 |
|---|---|
| 활성 릴리스 | `r2026-08-04-clause-s7.1-arctic-ko-ocr-approved` |
| 임베딩 | `dragonkue/snowflake-arctic-embed-l-v2.0-ko` · 1,024차원 |
| 리랭커 | `Qwen/Qwen3-Reranker-4B` |
| 승인 OCR 표 facts | 850 occurrences · 75 chunks · 179 documents |
| 검색 인덱스 | PostgreSQL + pgvector HNSW |
| 검증 | 사람 승인 패턴만 검색·인용에 포함, 미승인 후보 격리 |

상세 승인 정보와 해시는 [`config/accepted_s7_1_facts.json`](config/accepted_s7_1_facts.json)에서 확인할 수 있습니다.

## 주요 기능

- **약관 사전판정**: KCD 코드, 보험사, 가입 시점과 약관 세대를 조합해 관련 보장·면책 조항 검색
- **근거 중심 RAG**: 조각으로 검색하고 부모 조항 전체를 복원해 예외 문구 누락 방지
- **Hybrid Retrieval**: pgvector 의미 검색과 `pg_trgm` 어휘 검색을 RRF로 결합
- **리랭킹**: Qwen3-Reranker-4B로 검색 후보를 재정렬
- **OCR 표 복원**: 일반 텍스트 추출이 놓친 자기부담금 등 표 정보를 후보로 복구하고 사람 승인 후 반영
- **운영 안전성**: release·임베딩 모델·인덱스 세대 불일치 시 요청 차단
- **상담 채널**: 텍스트, 음성·화상 상담, 얼굴 로그인 2차 인증
- **관리자 도구**: 인덱스 상태, 지식 갭, 이벤트, 검증 큐와 PDF 운영 보고서

## 화면

프론트엔드는 별도 Node 빌드 없이 FastAPI가 제공하는 정적 웹으로 구성되어 있습니다.

| 화면 | 파일 | 용도 |
|---|---|---|
| 보험 사전판정 | [`app/static/insurance.html`](app/static/insurance.html) | 보험사·상품·질병기호 입력과 판정 결과 확인 |
| 관리자 대시보드 | [`app/static/admin.html`](app/static/admin.html) | 인덱스·검증·운영 현황 관리 |
| 얼굴인식 벤치마크 | [`app/static/facebench.html`](app/static/facebench.html) | 얼굴 모델 정확도·지연 비교 |
| 마이페이지 | [`app/static/mypage.html`](app/static/mypage.html) | 사용자 정보와 얼굴 인증 관리 |

### 실행 주소

| 사이트 | 실행 명령 | 주소 |
|---|---|---|
| 고객 웹 | `python -m scripts.run_customer_server` | <http://127.0.0.1:8080> |
| 관리자 웹 | `python -m scripts.run_admin_server` | <http://127.0.0.1:8081> |
| 통합 개발 서버 | `python scripts/run_dev_server.py` | <http://127.0.0.1:8080> |
| API 직접 실행 | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | <http://127.0.0.1:8000> |

고객 웹과 통합 개발 서버는 같은 8080 포트를 사용하므로 동시에 실행하지 않습니다.

## 빠른 시작

### 1. 설치

```bash
git clone -b develop https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN32-3rd-4Team.git
cd SKN32-3rd-4Team
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 설정

```bash
cp .env.example .env
```

기본 구성은 로컬 우선입니다. OpenAI 또는 Gemini를 사용할 때만 `.env`에 해당 API 키를 설정합니다.

### 3. 데이터 준비

```bash
python -m scripts.manage migrate
python -m scripts.manage seed
python -m scripts.manage ingest
```

PostgreSQL + pgvector 인덱스 A를 사용할 경우:

```bash
python -m scripts.pg
python -m scripts.index.build_clause_index
```

### 4. 서버 실행과 준비 상태 확인

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
curl http://127.0.0.1:8000/api/health/ready
```

`ready=true`, `clause_index.ready=true`가 확인되어야 검색·판정 요청을 처리합니다.

## AI 파이프라인

```text
보험사·상품·가입시점·KCD 입력
            ↓
약관 판본 및 세대 확정
            ↓
Arctic-ko dense 검색 + pg_trgm lexical 검색
            ↓
RRF 후보 결합 → Qwen3-Reranker-4B 재정렬
            ↓
부모 조항 복원 + 인용 가능성·신선도 검증
            ↓
판정 근거 / 확인 필요 / 판정 불가 상태 반환
```

OCR 및 표 추출 결과는 즉시 답변에 섞지 않습니다. 원본 위치와 축·금액 관계를 보존한 candidate fact로 저장하고, 사람 승인과 회귀 검증을 통과한 facts만 임베딩·검색·인용 대상으로 승격합니다.

## 테스트

외부 모델·DB 없이 실행하는 기본 테스트:

```bash
pytest -m "not llm and not ml and not mcp and not pg"
```

기능별 테스트:

```bash
pytest -m ml    # 얼굴·음성·감성 모델
pytest -m mcp   # MCP stdio 왕복
pytest -m pg    # 실제 PostgreSQL/pgvector
```

현재 요구사항과 테스트 연결은 [`tests/requirements_matrix.yaml`](tests/requirements_matrix.yaml), 팀 간 데이터·API 계약은 [`docs/handoff/README.md`](docs/handoff/README.md)에서 확인합니다.

## 저장소 구조

```text
app/
├─ application/     유스케이스와 포트
├─ adapters/        pgvector·파일·LLM·리랭커 어댑터
├─ core/            도메인 규칙, release, eligibility
├─ routers/         FastAPI REST API
├─ static/          고객·관리자 프론트엔드
├─ mcp/             MCP 서버
└─ ml/              음성·얼굴·의도 모델
config/             승인 release와 모델·추출 설정
data/               평가셋, 카탈로그, manifest
docs/handoff/       팀 간 계약과 운영 인수인계
scripts/            실행, DB, 인덱스, 추출·평가 도구
tests/              회귀·보안·계약 테스트
```

## 설계 원칙

1. **근거 없이는 판정하지 않는다.**
2. **문서 판본과 보험 세대를 자동으로 바꿔치기하지 않는다.**
3. **미승인 OCR·표 후보는 serving과 citation에서 차단한다.**
4. **모델·인덱스·release가 다르면 readiness를 실패시킨다.**
5. **평가 결과와 사람 승인 계보를 재현 가능한 해시로 보존한다.**

모델 후보와 활성 프로필은 [`model_registry.yaml`](model_registry.yaml), 활성 추출 릴리스는 [`config/accepted_extraction.json`](config/accepted_extraction.json)을 기준으로 합니다.
