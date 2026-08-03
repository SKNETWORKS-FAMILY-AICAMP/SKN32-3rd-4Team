# 올바른 보험비서 — KCD 질병기호 × 실손보험 약관 사전판정

팀 **비서단**. 커머스 실습(`_unified_mall`)에서 출발해 보험 도메인으로 옮기는 중이다.

RAG 기반 문서 질의응답을 코어로, 커머스 승인 루프·AI 에이전트(ReAct+CoT)·MCP·A2A·RBAC 관리자와
음성/화상 상담·얼굴 로그인 2차 인증까지 통합한 **로컬 우선(API 키 없이 기본 동작)** 플랫폼이다.

설계 원칙은 **개념적 Clean Architecture + 무폴백**: 오류를 그럴듯한 가짜 결과로 대체하지 않고
정의된 타입(`ConfigError`/`InfraError`/`LLMOutputError`/`ValidationErr`)으로 명시적으로 실패시킨다.

> 📐 **시스템 아키텍처 설계 보고서**(다이어그램 포함): [`docs/architecture.md`](docs/architecture.md)
> 📸 화면 갤러리: [`docs/index.html`](docs/index.html) · 📁 계획·이력·리포트: [`docs/`](docs/)

---

## 1. 빠른 시작

```bash
pip install -r requirements.txt
python -m scripts.manage migrate      # 테이블 생성(기동 시 자동 생성하지 않음)
python -m scripts.manage seed         # 상품·재고 시드
python -m scripts.manage ingest       # 문서 임베딩 → FAISS 인덱스
```

준비 상태는 `GET /api/health/ready`로 확인한다(미준비면 명시적으로 알린다 — 자동 폴백 없음).

---

## 2. 배정된 사이트 — 주소와 사용법

고객 사이트와 운영 도구는 **서로 다른 프로세스·포트**로 물리 분리돼 있다. 실무에서 관리자
대시보드를 VPN·사내망 뒤에 두는 패턴의 축소판이다.

| 사이트 | 실행 | 주소 | 무엇이 있나 |
|---|---|---|---|
| **고객 웹** | `python -m scripts.run_customer_server` | http://127.0.0.1:8080 | 스토어·AI 상담·화상 상담·마이페이지 |
| **운영/관리자** | `python -m scripts.run_admin_server` | http://127.0.0.1:8081 | 관리자 대시보드 + 운영 도구 전체 |
| 개발 전체(편의) | `python scripts/run_dev_server.py` | http://127.0.0.1:8080 | 위 둘을 합친 앱(테스트·개발용) |

> ⚠️ 고객 웹과 개발 전체 앱은 **같은 8080 포트**를 쓴다. 둘을 동시에 띄우지 말 것.

### 2-1. 고객 웹 (8080) — 일반 사용자용

| 페이지 | 주소 | 사용법 |
|---|---|---|
| 스토어(랜딩) | `/` 또는 `/static/shop.html` | 상품 목록 → 장바구니 담기 → **주문 미리보기** → 승인하면 주문 확정 |
| AI 상담 | `/static/index.html` | 질문 입력 → ReAct 에이전트가 도구를 호출하며 단계(Thought/Action/Observation) 표시 |
| 화상 상담 | `/static/video.html` | 카메라 켜고 말하면 STT→상담→TTS 음성 답변. 카메라 없이 텍스트로도 진행 가능 |
| 마이페이지 | `/static/mypage.html` | 얼굴 등록/해제(로그인 2차 인증용) |

이 포트에서는 관리자 API와 운영 페이지가 **물리적으로 없다**(404). 라우터 자체를 싣지 않는다.

### 2-2. 운영/관리자 (8081) — 내부용

| 페이지 | 주소 | 사용법 |
|---|---|---|
| 관리자 대시보드(랜딩) | `/` 또는 `/static/admin.html` | 주문·이벤트·인덱스·지식갭 조회, **요약 보고서 PDF** 생성/저장/인쇄 |
| 얼굴인식 벤치마크 | `/static/facebench.html` | 3개 백엔드(AdaFace/LVFace/insightface) 코사인·지연 실측 비교 (관리자 전용) |

> ★**2026-08-03 정리.** 이 표에 `RAG 실험실`·`MCP 도구`·`주문 관리` 세 줄이 더 있었는데
> **`mcp.html`·`orders.html` 은 파일이 애초에 없었다.** 문서가 없는 화면을 현행처럼 적고 있었다.
> `rag.html`·`rag.js` 는 커머스 RAG 화면이라 `legacy/_unified_mall/app/static/` 으로 격리했다.
> 재발 방지로 `tests/test_static_ui.py` 에 **링크 실재 검사**를 넣었다(죽은 링크 12개를 잡았다).

**관리자 계정**: 관리자 승격은 **CLI 전용**이다(권한상승 사고 방지 — UI 버튼 없음).

```bash
python -m scripts.manage promote <username>    # USER → ADMIN
python -m scripts.manage demote <username>     # ADMIN → USER (마지막 관리자는 거부)
```

### 2-3. 함께 쓰는 외부 서비스

| 서비스 | 기본 주소 | 실행 | 필요한 때 |
|---|---|---|---|
| 로컬 LLM(Gemma, OpenAI 호환) | http://127.0.0.1:8000/v1 | `python scripts/local_model_server.py` | 에이전트·RAG 답변 생성 |
| PostgreSQL + pgvector | 127.0.0.1:5433 (`mall_vec`) | `python -m scripts.pg` | hybrid·graph RAG 백엔드 |
| MCP 서버(stdio) | 표준입출력 | `python -m app.mcp.server` | MCP 클라이언트 연동 |

OpenAI/Gemini 키를 쓰려면 `.env`에 설정한다(`.env.example` 참고). **기본값은 로컬이라 키가 없어도 동작한다.**

---

## 3. 테스트

```bash
pytest -m "not llm and not ml and not mcp and not pg"   # CI 기본(외부 의존 없음)
pytest -m "ml"                                          # 무거운 로컬 모델(얼굴·음성·감성)
pytest -m "mcp"                                         # MCP stdio 왕복
pytest -m "pg"                                          # 실 PostgreSQL 필요
```

마커별로 외부 의존을 분리해 뒀다. CI(GitHub Actions)는 첫 번째 조합만 돌린다.

---

## 4. 주요 기능

- **RAG**: FAISS · pgvector(Hybrid RRF) · GraphRAG(PG 재귀 CTE) · LLM 리랭커 — 모두 같은 `RetrieverPort` 뒤에서 교체
- **커머스**: 읽기전용 미리보기 → 명시 승인, `Idempotency-Key` 필수, 조건부 원자 재고 차감
- **에이전트**: 수동 ReAct 루프 + LangChain 자동 에이전트 + CoT 자기검증(미지지 초안 차단)
- **MCP**: FastMCP stdio 10개 도구, REST와 유스케이스·프리젠터 공유(parity)
- **A2A**: 전문 에이전트 카드 발견 + 위임(order/catalog/knowledge/recommend)
- **보안**: role은 JWT에 넣지 않고 매 요청 DB 조회(강등 즉시 반영), 관리자 라우터 fail-closed,
  얼굴 2차 인증(pre2fa 챌린지 일회성 소비), 업로드 크기 상한
- **부가**: 음성 상담(STT/TTS), 화상 상담, 관리자 요약 보고서 PDF

한계는 숨기지 않고 [`docs/architecture.md` §9](docs/architecture.md)에 기록한다.

---

## 5. 저장소 구조

| 경로 | 용도 |
|---|---|
| `app/` | 애플리케이션(계층: application / adapters / routers / ml / mcp / a2a) |
| `tests/` | 테스트 + 요구사항↔테스트 매트릭스 |
| `scripts/` | 실행·운영 스크립트(서버 기동, DB 관리, 데모, 캡처) |
| `docs/` | **모든 문서** — 아키텍처·계획(`plans/`)·이력(`history/`)·리포트(`reports/`)·화면 갤러리 |
| `data/` | 시드 데이터·문서 코퍼스·평가셋 |
| `legacy/` | 대체·폐기된 코드 보존 |
