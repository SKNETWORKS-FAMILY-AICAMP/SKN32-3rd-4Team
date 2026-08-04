# 🏠 올바른 보험비서

> SK네트웍스 Family AI 캠프 32기 3차 프로젝트 4팀

---

## 1. 팀 소개

### 팀명

> 💼비서단

### 팀원

| 이름  | 파트                                                |
|-----|---------------------------------------------------|
| 송채영 | 👑팀장 │ 기획, 데이터 수집, 발표 준비, AI 파이프라인 개발             |
| 김지혜 | 💠팀원 │ 기획, 데이터 수집, 백엔드/DB 설계, 발표 준비               |
| 서유현 | 💠팀원 │ 기획, 데이터 수집, 데이터 전처리, AI 파이프라인 개발           |
| 정재희 | 💠팀원 │ 기획, 데이터 수집, AI 파이프라인 개발                    |
| 최연우 | 💠팀원 │ 기획, 데이터 전처리, 시스템 설계, 프론트엔드 개발, AI 파이프라인 개발 |

---

## 2. 프로젝트 개요
**KCD 질병기호와 실손보험 약관을 근거로 가입 전 보장 가능성을 확인하는 RAG 기반 보험 상담 플랫폼**
`올바른 보험비서`는 보험 약관에서 관련 조항을 검색하고, 가입자의 질병기호·보험사·상품 세대를 함께 대조해 판단 근거와 확인이 필요한 항목을 제공하는 팀 프로젝트입니다. 근거가 없거나 데이터 상태가 불완전하면 그럴듯한 답을 만들지 않고 명시적으로 중단하는 **무폴백(fail-closed)** 원칙을 적용합니다.

### 프로젝트 소개
- 약관 문서(비정형) + 질병코드(정형 데이터) 를 RAG로 연결해, 사용자가 자신의 보험으로 청구가 가능한지 사전에 확인할 수 있는 서비스입니다.
- 복잡하고 방대한 보험 약관 및 질병 코드를 AI 기반 RAG(검색증강생성) 기술로 정확히 탐색합니다.
- 일반 소비자, 실무자의 눈높이에 맞춰 맞춤형 안내를 제공하는 스마트 조회 솔루션입니다.

> ⚠️ 본 서비스는 보험 약관에 기반한 정보 안내 서비스이며, 개인이 가진 보험 증권의 특약 사항에 따라 보장은 달라질 수 있습니다.

### 프로젝트 배경 및 필요성

#### 기획 배경
- 보험약관의 중요성과 독해의 한계: 보험약관은 계약 체결과 보장 여부를 판단하는 핵심 근거 문서이나, 방대한 분량과 복잡한 전문용어로 인해 가입자가 내용을 꼼꼼히 확인하기 어렵습니다.
- 실손보험의 복잡성 및 정보 불균형: 특히 실손보험 약관은 세대(1~5세대)와 보험사에 따라 보장 범위와 문서 양식이 크게 달라, 일반 소비자가 본인 진료가 실제로 보장되는지 판단하기 매우 어렵습니다.
- 보장 여부 확인의 어려움: 진료비 내역서에 질병기호(KCD)가 표기되더라도, 이 코드가 실제 약관상 보장 대상인지 직접 연결하여 확인해 주는 서비스가 마땅치 않습니다.
- 발생 문제: 이로 인해 약관의 조건부 보장이나 면책 조항 등을 인지하지 못하고 추후 보험금 청구 시 예상치 못한 보장 거절이나 불이익을 겪는 사례가 빈번하게 발생합니다.


#### 기존 보험 관련 AI 서비스
질병분류정보센터 AI 서비스
- **KOICD 질병분류정보센터 - 보험담보 확인하기**
  - 특징: 주소 입력 시 집주인 신용 및 주택 위험도 24종 데이터 기반 보고서 즉시 발급
  - 한계: 근거 자료 통계적 학습 데이터 (특정 약관 미근거, 할루시네이션 우려), 정확한 조항 확인 불가, 일반적 답변 제공
  - 링크: https://www.koicd.kr/ins/claimableList.do

> **명확한 문서를 근거로 질의응답할 수 있는 서비스는 현재 존재하지 않음!**

---

### 프로젝트 목표

💡**서비스 포지셔닝**:
우리 서비스는 사람 고객 뿐만 아니라 API로 접근하는 AI 에이전트도 고객 범주에 포함하였습니다. 
그 이유는 현재 웹상에서 AI 에이전트 및 자동화된 봇의 이용량(트래픽 비중)이 인간 유저의 비중보다 훨씬 많기 때문입니다. 
이에 대한 근거는 글로벌 보안 및 인프라 기업들의 공식 데이터와 보고서를 통해 입증되고 있습니다.

근거자료:
- 글로벌 웹 트래픽의 상당 부분을 처리하는 인프라 기업 클라우드플레어(Cloudflare)의 네트워크 데이터에 따르면, 인터넷 역사상 최초로 봇과 AI 에이전트가 생성하는 트래픽이 인간의 트래픽을 추월했습니다.   
웹사이트에 들어오는 전체 요청 중 봇과 AI 에이전트가 차지하는 비중은 57.4%를 기록한 반면, 인간 유저는 42.6%에 그쳤습니다.

- 사이버 보안 기업 휴먼 보안이 발행한 보고서에 따르면, 전체 자동화 트래픽 중에서도 단순 데이터 수집용 크롤러를 넘어 실시간으로 웹과 상호작용하는 'AI 에이전트 및 에이전틱 브라우저' 트래픽이 전년 대비 수천 퍼센트 이상 급증했습니다.
인간 소비자가 상품을 구매하거나 정보를 찾을 때 평균 5개 정도의 웹사이트를 방문하는 반면, AI 에이전트는 동일한 작업을 수행하기 위해 수천 개(최대 수천 배 이상)의 웹페이지를 자율적으로 방문하여 방대한 데이터를 비교·탐색합니다.
  
  
### 서비스 확장 가능성
- **상품군 확장:** 실손보험에서 출발하여 **암보험, 종신보험, 어린이보험, 최근 수요가 급증하는 펫보험(반려동물 보험)** 등으로 데이터 및 도메인 확장.
- **기능 확장:** 가입 중인 실제 보험 증권(이미지/마이데이터)과 연동하여 "내가 가입한 상품 기준으로 보장받을 수 있는지" 개인화된 진단 서비스로 발전.


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

## 향후 계획 (확장 방향)
- [ ] OCR 진료비 내역서 인식 기능 도입으로 편의성 향상
- [ ] 자기부담금 계산기, 분쟁 사례 비교 기능 구체화


## 데이터 출처

- 네이버 의약품 사전
- 질병 분류 기호 검색 — [kcdcode.kr](https://kcdcode.kr)
- 공공데이터포털 실손보험정보 API
- 보험협회 통합 약관 공시 — [pub.insure.or.kr](https://pub.insure.or.kr)
- 참고 유사 서비스 — [koicd.kr](https://koicd.kr)
