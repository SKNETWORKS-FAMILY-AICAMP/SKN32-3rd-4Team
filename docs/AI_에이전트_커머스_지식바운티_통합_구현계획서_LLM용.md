---
document_type: implementation_plan
language: ko-KR
version: "3.0"
created_at: "2026-07-18"
project_name: "AI 에이전트 커머스·지식 바운티 통합 플랫폼"
project_mode: "기존 부트캠프 프로젝트 통합 고도화"
audience:
  - implementation_llm
  - backend_team
  - ai_rag_team
  - frontend_team
  - qa_team
primary_goal: "기존 LangChain·MCP·멀티에이전트·쇼핑몰·도구 기능을 재사용하여 RAG 기반 상담, 에이전트 쇼핑, 지식 바운티, 음성·화상 상담, 관리자 기능을 단일 제품으로 통합한다."
architecture_style: "모듈러 모놀리스 + 개념적 Clean Architecture + Ports/Adapters"
model_policy:
  cloud:
    - OpenAI GPT 계열
    - Google Gemini 계열
  self_hosted:
    - Qwen3.6
    - Gemma 4
  rule: "모델 ID를 도메인 코드에 직접 기록하지 않고 ModelGateway 어댑터와 배포 설정으로 주입한다."
status: proposed
---

# 0. 문서 사용법

이 문서는 사람에게 설명하기 위한 서술형 기획서가 아니라, 구현 담당 LLM과 개발팀이 바로 작업 분해·코드 생성·검증에 사용할 수 있는 **규범적 구현 계획서**다.

- **MUST**: 구현 완료 판정을 위해 반드시 지켜야 한다.
- **SHOULD**: 특별한 사유가 없으면 지킨다.
- **MAY**: 일정과 자원에 따라 선택한다.
- 모든 구현 작업은 `REQ-*`, `UC-*`, `API-*`, `TEST-*` 식별자를 커밋·PR·테스트 이름에 연결한다.
- 기존 코드는 전면 재작성하지 않는다. 먼저 현재 기능을 테스트로 고정한 뒤 어댑터 뒤로 이동한다.

---

# 1. 최종 판단

## 1.1 진행 결론

**진행한다.** 기존 프로젝트에 LangChain, MCP, 멀티에이전트, 쇼핑몰, 도구 호출, 웹 기능이 이미 있으므로 신규 제품을 처음부터 만드는 문제가 아니다. 핵심 과제는 다음 세 가지다.

1. 오래된 프레임워크 사용법과 강결합 구조를 최신 API·보안 기준으로 교체한다.
2. 기존 기능을 공통 유스케이스와 데이터 계약으로 연결한다.
3. RAG·커머스·바운티·음성·화상·관리자 기능을 하나의 시연 가능한 닫힌 루프로 만든다.

## 1.2 프로젝트 한 문장 정의

> 사용자의 텍스트·음성·화상 요청을 이해하고, 내부·외부 문서 RAG와 상품·주문 도구를 사용해 근거 있는 답변과 상품 추천을 제공하며, 부족한 호환성·실사용 정보는 분산된 Provider 에이전트의 지식 바운티로 보강한 뒤 사용자 승인 아래 주문까지 연결하는 AI 네이티브 상담·커머스 플랫폼.

## 1.3 구현 가능 범위

### 이번 통합 버전에서 MUST 구현

- 기존 로그인·쇼핑몰·상품·장바구니·주문 기능 유지
- 내부·외부 문서 수집, 전처리, 임베딩, 벡터 검색, 출처 기반 RAG QA
- OpenAI, Gemini, Qwen3.6, Gemma 4를 동일 인터페이스로 호출하는 Model Router
- 텍스트 고객 상담 챗봇
- 음성 상담 챗봇: 음성 입력·출력, 대화 중단(barge-in), 텍스트 기록
- 화상 상담 챗봇: 카메라 화면 + 음성 대화 + 주기적 프레임 이해
- 상품 검색·비교·추천·장바구니·구매 승인 도구
- MCP 서버를 통한 읽기·쓰기 도구 노출
- 내부 Reference Buyer Agent와 Provider/Validator 멀티에이전트 시뮬레이션
- 지식 바운티 생성·응답·검증·내부 포인트 정산
- 사용자 화면과 관리자 대시보드 분리
- Passkey/WebAuthn 기반 얼굴·기기 생체인증을 2차 인증 옵션으로 제공
- 관리자 요약 보고서 생성·저장·인쇄
- 테스트 계획·결과 보고서와 시연 시나리오

### 이번 버전에서 MUST NOT 주장

- 국내 모든 쇼핑몰 실시간 주문 연동
- 사용자 카드의 완전 무인 결제
- 포인트의 현금 출금
- 실제 외부 에이전트 수천 개가 참여하는 경제망
- 얼굴 원본 이미지 또는 생체 템플릿의 서버 저장
- RAG가 환각을 완전히 제거한다는 주장

---

# 2. 기존 자료 재검토와 최신화 결론

## 2.1 기존 부트캠프 자료에서 유지할 개념

| 영역 | 유지할 내용 | 통합 프로젝트 적용 |
|---|---|---|
| RAG | 문서 검색 후 근거를 넣어 답변 | 내부 정책·상품 매뉴얼·FAQ·외부 공식 자료 검색 |
| 임베딩 | 문서를 벡터화해 의미 검색 | pgvector 기반 의미 검색 + 키워드 검색 결합 |
| LangChain | 로더·청킹·Retriever·Prompt·LLM 연결 | 인프라 어댑터와 단순 체인에 제한적으로 사용 |
| LangGraph | 상태·조건 분기·중단 후 재개·사람 승인 | 구매 승인, 바운티, 장시간 상담 워크플로 |
| MCP | 모델과 도구를 표준 방식으로 연결 | 동일 유스케이스를 REST와 MCP 양쪽에 노출 |
| ReAct/Tool Calling | 관찰 결과를 바탕으로 다음 행동 선택 | 상담·상품 조회 등 읽기 중심 작업에 사용 |

## 2.2 최신화가 필요한 부분

### MOD-01 LangChain/LangGraph

- 단순 QA를 모두 LangGraph로 만들지 않는다.
- 단순 RAG는 함수·Runnable 또는 프레임워크 독립 서비스로 구현한다.
- 상태 유지, 반복, 승인, 멀티에이전트가 필요한 흐름만 LangGraph에 둔다.
- Checkpointer를 사용해 재시작 가능한 상태를 유지한다.
- 노드 내부에서 DB·결제·포인트 정책을 직접 구현하지 않고 Application Use Case를 호출한다.
- 모델 호출·Retriever·도구는 포트로 추상화해 LangChain 버전 변경이 도메인까지 전파되지 않게 한다.

### MOD-02 MCP

- 최신 MCP 사양을 기준으로 `stdio`와 `Streamable HTTP`를 지원한다.
- 원격 MCP는 OAuth 2.1 기반 인증·scope·audience 검증을 적용한다.
- 토큰 패스스루를 금지한다.
- 모든 쓰기 도구는 사용자 확인 또는 서버 정책 승인을 요구한다.
- 도구 입력은 Pydantic/JSON Schema로 검증하고, 출력은 비신뢰 데이터로 취급한다.
- MCP는 비즈니스 로직이 아니라 **Interface Adapter**다. REST와 MCP가 동일 Application Use Case를 호출해야 한다.

### MOD-03 모델 연동

- OpenAI는 신규 에이전트 기능을 Responses API/Agents SDK 방향으로 연결하되, 도메인은 자체 `ModelGateway`에 의존한다.
- Gemini는 운영 일반 질의에는 안정 모델 ID를 고정하고, 실시간 음성·카메라에는 Live API 전용 모델 프로필을 둔다.
- Qwen3.6과 Gemma 4는 OpenAI-compatible self-hosted endpoint 또는 전용 SDK 뒤에 둔다.
- 모델별 tool-call 형식 차이는 Adapter에서 정규화한다.
- 모델 이름, context limit, 가격, 가용성은 설정 파일과 모델 레지스트리에서 관리한다.

### MOD-04 RAG

기존의 “PDF → 청킹 → 벡터 DB → top-k → LLM” 단일 경로를 다음으로 고도화한다.

```text
문서 수집
→ 원문 보존
→ 구조 파싱
→ 정제·PII 검사·버전 부여
→ 문서 유형별 청킹
→ 임베딩 + 키워드 인덱스
→ ACL/최신성/문서종류 필터
→ Hybrid Retrieval
→ Reranking
→ 근거 적합성 평가
→ 답변 생성
→ 문장별 출처
→ 지원되지 않은 주장 검사
```

### MOD-05 음성·화상

- 구식 STT → LLM → TTS 직렬 방식만 사용하지 않는다.
- 실시간 상담은 OpenAI Realtime 또는 Gemini Live 어댑터를 사용한다.
- 비용·장애 대응을 위해 STT/LLM/TTS 분리형 fallback도 유지한다.
- 화상은 “고해상도 전체 비디오를 지속 업로드”가 아니라 음성 스트림 + 저주기 프레임 샘플링을 기본으로 한다.

### MOD-06 로그인

- 서버가 얼굴 사진을 저장·비교하는 독자 얼굴인증을 만들지 않는다.
- WebAuthn/Passkey를 사용하여 기기 Face ID, Windows Hello, Android 생체인증 결과만 검증한다.
- 생체정보는 기기 밖으로 나오지 않으며 서버에는 공개키 자격 증명만 저장한다.

## 2.3 모델 최신성 검증 메모

- Qwen 공식 저장소에서 Qwen3.6-35B-A3B와 Qwen3.6-27B 공개 릴리스를 확인했다.
- Google 공식 개발자 블로그에서 Gemma 4 12B 공개 안내를 확인했다.
- **2026-07-18 당일의 별도 Gemma 4 신규 모델 릴리스는 공식 모델 카드·공식 릴리스 페이지에서 확인되지 않았다.** 따라서 “오늘 업데이트”라는 외부 주장은 운영 기준으로 사용하지 않고, 공식 model card/checksum/runtime changelog가 확인된 버전만 pin한다.
- 로컬 모델은 이름만 채택하는 것이 아니라 목표 GPU에서 `정확도·tool-call 성공률·첫 토큰 지연·토큰 속도·VRAM·OOM률`을 측정한 뒤 역할을 확정한다.

---

# 3. 요구사항 카탈로그

## 3.1 기능 요구사항

| ID | 요구사항 | 우선순위 | 완료 조건 |
|---|---|---:|---|
| REQ-RAG-01 | 내부 PDF, MD, HTML, CSV, DB 레코드를 수집한다 | MUST | 최소 4종 형식 ingest 테스트 통과 |
| REQ-RAG-02 | 외부 공식 문서 URL 또는 허용 API를 수집한다 | MUST | 출처·수집시각·버전 저장 |
| REQ-RAG-03 | 벡터 검색과 키워드 검색을 결합한다 | MUST | 하이브리드 검색 평가셋에서 단일 방식보다 개선 |
| REQ-RAG-04 | 답변에 문장 또는 주장 단위 출처를 표시한다 | MUST | 출처 없는 사실 주장 비율 기준 이하 |
| REQ-RAG-05 | 근거가 부족하면 모른다고 답하거나 추가 검색한다 | MUST | answerability 평가 통과 |
| REQ-LLM-01 | 4개 모델군을 ModelGateway로 교체 가능하게 한다 | MUST | 동일 테스트를 4개 프로필로 실행 |
| REQ-LLM-02 | 작업별 모델 라우팅과 fallback을 제공한다 | MUST | 장애·timeout 시 fallback 테스트 통과 |
| REQ-COM-01 | 자연어를 구매 의도 JSON으로 변환한다 | MUST | 스키마 유효성 100% |
| REQ-COM-02 | 상품 검색·필터·비교·근거 설명을 제공한다 | MUST | 테스트 질의 top-k 품질 기준 통과 |
| REQ-COM-03 | 사용자 승인 뒤에만 주문을 생성한다 | MUST | 승인 없는 주문 생성 0건 |
| REQ-BNT-01 | 근거 부족 시 바운티를 생성한다 | MUST | 후보 상품과 필요 증거 연결 |
| REQ-BNT-02 | Provider별 데이터 접근 범위를 격리한다 | MUST | 권한 밖 문서 조회 0건 |
| REQ-BNT-03 | Validator가 **근거성·재현성·중복성**을 평가한다(사실성은 판정하지 않음 — 교정) | MUST | 각 검사 통과/반려 케이스 + 사실성 판정 코드 부재 확인 |
| REQ-BNT-05~08 | 등급화·escrow/이의제기·제한적 slash·만족도 정산 제외 (신설) | MUST | `docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md` §6 |
| REQ-BNT-04 | 비현금 내부 포인트 원장을 제공한다 | MUST | 이중 지급·음수 잔액 방지 |
| REQ-MCP-01 | 읽기/쓰기 도구를 MCP로 제공한다 | MUST | Inspector와 외부 클라이언트 smoke test |
| REQ-VOICE-01 | 실시간 음성 상담을 제공한다 | MUST | 음성 입력·응답·중단·기록 시연 |
| REQ-VIDEO-01 | 카메라 프레임을 이용한 화상 상담을 제공한다 | MUST | 사용자 동의 후 프레임 분석·즉시 중지 |
| REQ-AUTH-01 | 로그인과 역할 권한을 제공한다 | MUST | USER/ADMIN/PROVIDER/VALIDATOR 권한 테스트 |
| REQ-AUTH-02 | Passkey 기반 2차 인증을 제공한다 | MUST | 등록·인증·복구 흐름 테스트 |
| REQ-ADMIN-01 | 관리자 대시보드를 제공한다 | MUST | 사용자·대화·문서·주문·바운티·비용 조회 |
| REQ-ADMIN-02 | 요약 보고서를 생성·저장·인쇄한다 | MUST | HTML/PDF 또는 print stylesheet 출력 |
| REQ-QA-01 | 테스트 계획과 결과를 자동 수집한다 | MUST | CI 결과와 보고서 연결 |
| REQ-DEMO-01 | 통합 시연영상을 제작한다 | MUST | 정해진 시나리오 완주 영상 |

## 3.2 비기능 요구사항

| ID | 요구사항 | 목표 |
|---|---|---|
| NFR-SEC-01 | 쓰기 도구 승인 | 결제·주문·포인트·문서 삭제는 명시 승인 |
| NFR-SEC-02 | 프롬프트 인젝션 방어 | 외부 콘텐츠와 시스템 지시 분리, allow-list |
| NFR-OBS-01 | 추적성 | request/trace/model/tool/retrieval/order ID 연결 |
| NFR-REL-01 | 멱등성 | 주문·결제·포인트 지급에 idempotency key |
| NFR-PERF-01 | 텍스트 응답 | 캐시 miss 기준 첫 응답 목표치 정의·측정 |
| NFR-PERF-02 | 음성 응답 | turn latency와 끊김률 측정 |
| NFR-PRIV-01 | 데이터 최소화 | 원본 음성·프레임 기본 비저장 |
| NFR-TEST-01 | 테스트 격리 | 외부 LLM 없이 핵심 유스케이스 단위 테스트 가능 |
| NFR-MAINT-01 | 교체 가능성 | 모델·Vector DB·PG 변경이 도메인 수정 없이 가능 |

---

# 4. 최종 시스템 범위

## 4.1 사용자 채널

1. **텍스트 상담**: 정책·상품·주문·기술 질의
2. **음성 상담**: 실시간 양방향 음성, transcript 제공
3. **화상 상담**: 카메라 공유, 제품·화면·문서 이미지 이해
4. **AI 쇼핑**: 자연어 구매 조건, 상품 비교, 장바구니, 승인 주문
5. **지식 바운티**: 부족한 정보 요청, 답변·검증·포인트
6. **관리자**: 데이터, 사용자, 상담, 주문, 에이전트, 비용, 평가, 보고서

## 4.2 핵심 사용자 시나리오

### UC-01 내부 정책 질의

```text
사용자: "단순 변심 반품 배송비와 기한을 알려줘."
→ 질문 분류
→ 사용자 권한 필터
→ 내부 정책 Hybrid Retrieval
→ Rerank
→ 근거 적합성 평가
→ 답변 + 문장별 출처
→ 대화 로그·평가 저장
```

### UC-02 상품 추천과 주문

```text
사용자: "RTX 4070 SUPER PC에 맞는 64GB RAM을 25만원 아래로 찾아줘."
→ 구매 의도 JSON
→ 상품 DB/판매자 API 검색
→ 가격·재고·규격 결정론적 필터
→ 호환성 근거 검색
→ 근거 부족 감지
→ 필요 시 지식 바운티
→ 후보 재랭킹
→ 사용자 비교 화면
→ 사용자 승인
→ 주문 생성
```

### UC-03 지식 바운티

```text
Requester Agent가 질문·필요 증거·보상 포인트 등록
→ Router가 capability와 평판으로 Provider 선택
→ Provider가 허용된 로컬 데이터만 검색
→ 답변 + 출처 + 증거 해시 제출
→ Validator가 사실성·정합성·중복·재현성 평가   ⚠️ 교정됨: "사실성" 평가는 불가(오라클 문제).
                                              → docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md
→ 이의 제기 기간
→ Settlement Service가 포인트 원장 반영
→ 검증 결과를 상품 지식층에 연결
```

### UC-04 음성·화상 상담

```text
브라우저 마이크/카메라 권한 동의
→ Realtime Session 발급
→ 음성 스트림
→ 필요 시 0.2~1 FPS 프레임 샘플링
→ RAG/상품 Tool 호출
→ 음성 응답 + 화면 카드
→ 사용자가 말하면 응답 중단
→ transcript와 구조화 결과 저장
```

### UC-05 관리자 보고서

```text
기간·채널·모델·카테고리 선택
→ 상담/주문/RAG/바운티/비용 집계
→ 결정론적 통계 생성
→ LLM이 서술 요약 초안 생성
→ 관리자 검토
→ 버전 저장
→ 인쇄용 HTML/PDF 출력
```

---

# 5. 아키텍처 결정

## ADR-001: 모듈러 모놀리스로 시작한다

### 결정

단일 FastAPI 배포 단위를 유지하되 도메인 모듈과 포트를 분리한다.

### 이유

- 기존 프로젝트 통합 속도가 빠르다.
- 팀 규모에서 마이크로서비스 운영 부담을 피한다.
- 향후 AI worker, realtime gateway, ingestion worker만 독립 프로세스로 분리 가능하다.

## ADR-002: 개념적 Clean Architecture를 적용한다

### 적용 강도

완전한 DDD나 모든 객체의 추상화가 아니라 다음 경계만 강제한다.

```text
Domain
  순수 엔티티·값 객체·정책
Application
  유스케이스·포트·트랜잭션 경계
Adapters
  DB·Vector DB·LLM·MCP·PG·외부 API
Interfaces
  FastAPI·WebSocket·MCP·Worker·CLI
```

### 의존성 규칙

- Domain은 LangChain, FastAPI, SQLAlchemy, OpenAI SDK를 import하지 않는다.
- Application은 구체 모델·DB 구현을 import하지 않는다.
- Adapter가 Application Port를 구현한다.
- Interface는 Application Use Case만 호출한다.

## ADR-003: REST Application API가 기준 계약이다

- FastAPI의 OpenAPI를 내부·외부 기준 계약으로 사용한다.
- MCP 도구는 같은 유스케이스를 호출하는 별도 어댑터다.
- UI, 내부 Reference Agent, 외부 Agent가 동일 계약을 사용한다.

## ADR-004: LangGraph는 장시간 상태 워크플로에만 사용한다

LangGraph 적용:

- 상담 라우팅 중 복수 검색과 재질문
- 주문 사용자 승인 interrupt
- 바운티 생성 → 제출 → 검증 → 이의 → 정산
- 음성 상담의 장시간 세션 상태

LangGraph 미적용:

- 상품 가격 계산
- 권한 검사
- 검색 SQL
- 포인트 계산
- 보고서 통계 집계
- 단일 문서 요약

## ADR-005: LLM은 결정권자가 아니라 제안자다

LLM이 할 수 있는 일:

- 자연어 의도 구조화
- 검색 질의 확장
- 답변 초안
- 비교 설명
- 정성적 분류
- 증거 요약

LLM이 직접 해서는 안 되는 일:

- 가격·재고 생성
- 주문·결제 승인
- 권한 결정
- 포인트 잔액 변경
- 사용자 인증 판정
- 데이터 삭제

---

# 6. Clean Architecture 적용 버전

## 6.1 계층별 책임

### Domain Layer

```text
domain/
├─ commerce/
│  ├─ product.py
│  ├─ offer.py
│  ├─ cart.py
│  ├─ order.py
│  └─ purchase_policy.py
├─ knowledge/
│  ├─ document.py
│  ├─ evidence.py
│  ├─ citation.py
│  └─ claim.py
├─ bounty/
│  ├─ bounty.py
│  ├─ submission.py
│  ├─ validation.py
│  └─ point_transaction.py
├─ conversation/
│  ├─ session.py
│  └─ message.py
└─ identity/
   ├─ user.py
   └─ role.py
```

Domain은 프레임워크 없는 Python으로 유지한다.

### Application Layer

```text
application/
├─ ports/
│  ├─ model_gateway.py
│  ├─ embedding_gateway.py
│  ├─ retriever.py
│  ├─ product_repository.py
│  ├─ order_repository.py
│  ├─ payment_gateway.py
│  ├─ realtime_gateway.py
│  ├─ report_renderer.py
│  └─ unit_of_work.py
├─ use_cases/
│  ├─ answer_question.py
│  ├─ ingest_documents.py
│  ├─ search_products.py
│  ├─ recommend_products.py
│  ├─ create_cart.py
│  ├─ approve_order.py
│  ├─ create_bounty.py
│  ├─ submit_evidence.py
│  ├─ validate_submission.py
│  ├─ settle_bounty.py
│  └─ generate_admin_report.py
└─ dto/
```

### Adapter Layer

```text
adapters/
├─ llm/
│  ├─ openai_gateway.py
│  ├─ gemini_gateway.py
│  ├─ qwen_local_gateway.py
│  ├─ gemma_local_gateway.py
│  └─ model_router.py
├─ retrieval/
│  ├─ langchain_loader_adapter.py
│  ├─ pgvector_retriever.py
│  ├─ keyword_retriever.py
│  ├─ hybrid_retriever.py
│  └─ reranker.py
├─ persistence/
│  ├─ sqlalchemy_models.py
│  └─ repositories/
├─ commerce/
│  ├─ cafe24_connector.py
│  └─ sandbox_payment_gateway.py
├─ auth/
│  └─ webauthn_adapter.py
├─ realtime/
│  ├─ openai_realtime_adapter.py
│  └─ gemini_live_adapter.py
└─ reporting/
   ├─ html_report_renderer.py
   └─ print_renderer.py
```

### Interface Layer

```text
interfaces/
├─ api/
│  ├─ chat_router.py
│  ├─ rag_router.py
│  ├─ commerce_router.py
│  ├─ bounty_router.py
│  ├─ admin_router.py
│  └─ auth_router.py
├─ realtime/
│  └─ websocket_router.py
├─ mcp/
│  ├─ server.py
│  ├─ read_tools.py
│  └─ write_tools.py
├─ workers/
│  ├─ ingestion_worker.py
│  └─ agent_worker.py
└─ cli/
```

## 6.2 팀 작업 차이

| 팀 작업 요소 | Clean Architecture 적용 | 효과 |
|---|---|---|
| 작업 분담 | 유스케이스와 어댑터 단위 | AI팀·백엔드팀 병렬 작업 가능 |
| 모델 교체 | ModelGateway 어댑터만 수정 | GPT/Gemini/Qwen/Gemma 실험 충돌 감소 |
| DB 교체 | Repository 구현만 수정 | pgvector/Qdrant 비교 가능 |
| 테스트 | 포트 mock으로 외부 서비스 없이 실행 | CI가 빠르고 비용 없음 |
| merge conflict | 파일 책임이 분리됨 | 공용 `agent.py` 충돌 감소 |
| 보안 | 주문 승인·권한 정책이 유스케이스 경계에 모임 | 우회 경로 감소 |
| 장애 분석 | trace가 use case와 adapter를 구분 | 원인 추적 용이 |
| 프레임워크 업데이트 | Adapter 범위에서 흡수 | LangChain/MCP 변경 영향 제한 |

## 6.3 팀 역할 권장

| 역할 | 주 소유 모듈 | 병렬 작업 계약 |
|---|---|---|
| Backend/Commerce | Domain, commerce use cases, order, auth | ProductRepository, PaymentGateway |
| AI/RAG | ModelGateway, Retriever, Prompt, evaluation | AnswerQuestion DTO, Evidence DTO |
| Agent/MCP | LangGraph workflows, MCP adapters, bounty | Use Case 인터페이스만 호출 |
| Frontend | 사용자·관리자·음성·화상 UI | OpenAPI DTO와 이벤트 스키마 |
| QA/Infra | CI, observability, test datasets, deployment | 테스트 ID와 trace schema |

---

# 7. Clean Architecture 미적용 버전

## 7.1 예상 구조

```text
app/
├─ main.py
├─ chat.py
├─ shop.py
├─ agent.py
├─ rag.py
├─ mcp_server.py
├─ models.py
└─ database.py
```

### 흔한 호출 방식

```text
FastAPI Router
→ LangGraph Node
→ LangChain Retriever
→ OpenAI/Gemini SDK
→ SQLAlchemy Session
→ 주문 UPDATE
→ 포인트 UPDATE
→ 응답
```

## 7.2 세분화된 문제

### 개발 초기

- 파일 수가 적어 데모 속도는 빠르다.
- 한 명이 전체 구조를 알고 있으면 기능을 붙이기 쉽다.
- 인터페이스 설계 시간이 적다.

### 팀원이 동시에 작업할 때

- 모두 `agent.py`, `rag.py`, `shop.py`를 수정한다.
- prompt 변경이 주문 코드에 영향을 준다.
- 모델 SDK 객체가 전역으로 공유되어 테스트가 불안정하다.
- 상품 조회 Tool과 MCP Tool이 같은 로직을 복사한다.
- 프론트가 기대하는 JSON과 에이전트 출력 형식이 자주 깨진다.
- merge conflict를 피하려고 순차 작업하게 된다.

### 테스트할 때

- 단위 테스트인데도 실제 LLM·Vector DB·DB가 필요하다.
- LLM 응답 변동 때문에 주문 테스트가 실패한다.
- 결제·포인트 변경을 mock하기 어렵다.
- 실패가 검색 때문인지 모델 때문인지 비즈니스 로직 때문인지 구분하기 어렵다.

### 기능이 늘어난 뒤

- 모델 변경이 전체 라우터와 프롬프트에 퍼진다.
- 관리자 통계와 사용자 상담이 같은 DB 쿼리를 복사한다.
- 권한 검사가 엔드포인트마다 달라진다.
- 음성·화상 채널이 텍스트 챗봇 코드를 복제한다.
- 쓰기 도구가 사용자 승인 없이 호출될 위험이 커진다.

## 7.3 미적용 버전을 선택해도 되는 조건

다음 조건을 모두 충족하면 단기 데모 브랜치로 허용할 수 있다.

- 개발자가 1명이다.
- 수명이 2주 이하다.
- 실제 주문·인증·포인트 변경이 없다.
- 모델이 1개다.
- 배포 후 유지보수하지 않는다.

현재 프로젝트는 위 조건에 해당하지 않으므로 미적용 버전을 최종 구조로 선택하지 않는다.

## 7.4 두 버전의 일정 차이

| 시점 | 미적용 | 개념적 Clean 적용 |
|---|---|---|
| 첫 1~2주 | 화면이 빨리 나옴 | 경계·DTO·포트 정의로 느려 보임 |
| 3~4주 | 중복과 충돌 시작 | 팀 병렬 개발 속도 증가 |
| 모델 4개 통합 | 조건문·SDK 분산 | Adapter 추가 |
| 음성·화상 추가 | 챗 로직 복사 | 같은 Use Case 재사용 |
| 실제 주문 연결 | 권한·트랜잭션 재설계 필요 | 기존 Port 구현 교체 |
| 버전 업데이트 | 연쇄 수정 | Adapter 회귀 테스트 |
| 최종 발표 직전 | 예상 밖 회귀 위험 큼 | 통합 테스트 범위 명확 |

---

# 8. 모델 전략

## 8.1 공통 인터페이스

```python
class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
    async def generate_structured(self, request: StructuredRequest[T]) -> T: ...
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]: ...
    async def call_tools(self, request: ToolRequest) -> ToolCallResult: ...
```

## 8.2 역할별 라우팅

| 작업 | 1차 모델 | 대체 모델 | 이유 |
|---|---|---|---|
| 고난도 최종 답변·복잡한 Tool 계획 | OpenAI GPT | Gemini | 안정적 구조 출력과 도구 사용 |
| 긴 문서·멀티모달 분석 | Gemini | GPT | 멀티모달·긴 입력 활용 |
| 실시간 음성·카메라 | Gemini Live 또는 OpenAI Realtime | 분리 STT/LLM/TTS | 실시간 세션과 barge-in |
| 사내 민감 문서 RAG | Qwen3.6 | Gemma 4 | self-hosted 처리 |
| 로컬 멀티모달·프레임 이해 | Gemma 4 | Gemini | 공개 가중치 멀티모달 |
| Provider Agent 대량 응답 | Qwen3.6 | Gemma 4 | API 비용 감소, 데이터 로컬 유지 |
| Validator high-risk pass | GPT 또는 Gemini | 상호 교차검증 | 단일 모델 편향 완화 |
| 개발·CI mock | Deterministic Fake Model | 없음 | 재현 가능한 테스트 |

## 8.3 Model Router 규칙

```yaml
routing:
  confidential_internal:
    preferred: qwen36_local
    fallback: gemma4_local
    cloud_allowed: false
  realtime_video:
    preferred: gemini_live
    fallback: openai_realtime
  checkout_explanation:
    preferred: gpt
    fallback: gemini
  provider_bulk:
    preferred: qwen36_local
    fallback: gemma4_local
```

## 8.4 운영 원칙

- 정확한 모델 ID는 `.env`가 아니라 버전 관리되는 `model_registry.yaml`에 기록한다.
- 운영에는 `latest` alias를 사용하지 않는다.
- 모델별 prompt adapter를 분리한다.
- tool-call parser를 모델별로 테스트한다.
- self-hosted 모델은 vLLM/llama.cpp/Ollama 등 OpenAI-compatible endpoint 뒤에 둘 수 있으나, 배포 엔진은 벤치마크 후 선택한다.
- Qwen3.6-27B와 35B-A3B는 목표 GPU에서 각각 측정한다. 활성 파라미터가 작아도 전체 가중치 메모리 요구가 사라지는 것은 아니다.
- Gemma 4 12B는 오디오·비디오 포함 멀티모달 테스트를 수행하되, 실제 프레임 처리량은 하드웨어별로 측정한다.

---

# 9. RAG 설계

## 9.1 데이터 소스

### 내부

- 환불·교환·배송 정책
- 고객 상담 FAQ
- 상품 상세·옵션·호환성 문서
- 주문·회원·판매자 데이터베이스
- 운영 매뉴얼
- 관리자 공지
- 테스트 로그·벤치마크

### 외부

- 제조사 공식 사양·매뉴얼
- 판매자 승인형 상품 API/Feed
- Cafe24 연동 데이터
- 오픈 라이선스 데이터
- 허용된 공식 사이트 문서

## 9.2 저장 모델

```json
{
  "document_id": "doc_...",
  "chunk_id": "chunk_...",
  "content": "...",
  "source": {
    "type": "internal_pdf",
    "uri": "...",
    "title": "...",
    "page": 7
  },
  "version": "2026-07-18",
  "observed_at": "2026-07-18T10:00:00+09:00",
  "valid_from": "2026-07-01",
  "valid_until": null,
  "acl": ["USER", "ADMIN"],
  "checksum": "sha256:...",
  "synthetic": false
}
```

## 9.3 Ingestion Pipeline

```text
Source Connector
→ Raw Object Store
→ Parser
→ Normalizer
→ PII/Secret Scanner
→ Version Resolver
→ Semantic Chunker
→ Metadata Enricher
→ Embedding Gateway
→ PostgreSQL + pgvector
→ Keyword Index
→ Ingestion Report
```

## 9.4 Query Pipeline

```text
Question
→ Intent/ACL
→ Query Rewrite
→ Structured DB Lookup branch
→ Hybrid Retriever branch
→ Merge/RRF
→ Reranker
→ Evidence Sufficiency Gate
→ Answer Generator
→ Citation Binder
→ Unsupported Claim Checker
→ Final Response
```

### 규칙

- 가격·재고·주문 상태는 RAG가 아니라 SQL/API로 조회한다.
- 정책·매뉴얼·설명은 RAG로 조회한다.
- 두 결과를 하나의 Evidence Bundle로 조합한다.
- 문서에 없는 답은 생성하지 않는다.
- 이전 버전 문서가 최신 문서를 덮지 못하도록 `valid_from/version` 필터를 적용한다.

## 9.5 Prompt Template

```text
SYSTEM:
너는 근거 기반 고객 상담 도우미다.
제공된 EVIDENCE 밖의 사실을 단정하지 않는다.
근거가 부족하면 부족한 필드와 필요한 추가 자료를 말한다.
주문·결제·권한 변경은 Tool 결과와 사용자 승인 없이는 수행하지 않는다.

FEW-SHOT:
Q: 환불 기한은?
EVIDENCE: [정책 v2026-07 p.3: 수령 후 7일]
A: 상품 수령 후 7일 이내입니다. [정책 v2026-07 p.3]

Q: 특정 예외 상품도 7일인가?
EVIDENCE: 예외 조건 없음
A: 제공된 문서만으로 예외 적용 여부를 확인할 수 없습니다.
```

---

# 10. 멀티에이전트·지식 바운티 설계

## 10.1 에이전트 역할

| Agent | 책임 | 사용 도구 | 쓰기 권한 |
|---|---|---|---|
| Buyer/Requester | 사용자 의도·필요 증거 정의 | 상품 검색, 바운티 생성 | 장바구니 초안만 |
| Router | Provider 선택 | capability registry | 없음 |
| Provider | 로컬 자료 검색·답변 | 허용 Retriever | submission 생성 |
| Validator | 근거·정합성·중복 검사 | evidence read, test runner | validation 생성 |
| Challenger | 오류·반례 탐색 | read-only tools | challenge 생성 |
| Settlement | 점수 계산·원장 반영 | deterministic service | 제한된 원장 쓰기 |
| Supervisor | 상태 전이와 timeout | workflow state | 직접 비즈니스 쓰기 없음 |

## 10.2 Provider 시뮬레이션

```text
agent_data/
├─ provider_hardware/
│  ├─ benchmark.csv
│  └─ execution_logs/
├─ provider_compatibility/
│  ├─ motherboard_matrix.json
│  └─ install_cases.md
├─ provider_policy/
│  └─ seller_policies.pdf
└─ ground_truth/
   └─ hidden_answer_set.json
```

- Provider는 자신의 디렉터리·인덱스만 접근한다.
- `ground_truth`는 평가 시스템만 접근한다.
- 합성 데이터는 `synthetic=true`로 표시한다.

## 10.3 바운티 상태

```text
DRAFT
→ OPEN
→ ROUTED
→ COLLECTING
→ VALIDATING
→ CHALLENGE_WINDOW
→ SETTLED
또는 EXPIRED / REJECTED / CANCELLED
```

## 10.4 점수 계산

```text
final_score =
  0.30 * evidence_support
+ 0.20 * factual_consistency
+ 0.15 * freshness
+ 0.15 * requirement_coverage
+ 0.10 * reproducibility
+ 0.10 * uniqueness
- penalties
```

점수 계산은 Python 코드로 수행하며 LLM은 각 하위 평가에 대한 제안과 설명만 제공한다.

---

# 11. MCP와 Tool 설계

## 11.1 Tool 분류

### Read Tools

- `search_documents`
- `get_document_evidence`
- `search_products`
- `compare_products`
- `get_stock`
- `get_order_status`
- `list_open_bounties`
- `get_bounty_result`
- `get_point_balance`

### Write Tools

- `create_cart`
- `create_bounty`
- `submit_bounty_answer`
- `validate_bounty_answer`
- `approve_order`
- `cancel_order`
- `save_admin_report`

## 11.2 Tool 보안 정책

```yaml
tool_policy:
  search_products:
    scopes: [commerce.read]
    confirmation: false
  create_cart:
    scopes: [commerce.write]
    confirmation: false
  approve_order:
    scopes: [commerce.checkout]
    confirmation: always
    idempotency_required: true
  settle_bounty:
    scopes: [bounty.settle]
    role: SYSTEM
    confirmation: policy
```

## 11.3 MCP 구현 규칙

- Tool 함수가 DB session을 직접 열지 않는다.
- Tool은 Application DTO를 생성하고 Use Case를 호출한다.
- Tool description에 부작용, 비용, 승인 필요 여부를 명시한다.
- 외부 문서 내용은 Tool instruction으로 해석하지 않는다.
- 요청·응답 크기, timeout, rate limit를 둔다.
- Inspector 기반 contract test를 CI에 넣는다.

---

# 12. 텍스트·음성·화상 상담

## 12.1 공통 대화 코어

모든 채널은 동일한 `ConversationUseCase`를 사용한다.

```text
Channel Adapter
→ Session/Auth Context
→ Conversation Orchestrator
→ RAG / Commerce / Bounty Tools
→ Response DTO
→ Channel Renderer
```

## 12.2 텍스트

- SSE 또는 WebSocket streaming
- 출처 카드
- Tool 실행 상태
- 구매 승인 컴포넌트
- 만족도·오류 신고

## 12.3 음성

### Primary

- OpenAI Realtime 또는 Gemini Live
- 서버가 ephemeral session token을 발급
- 브라우저는 WebRTC 또는 WebSocket으로 연결
- Function/Tool call은 서버 정책을 통과

### Fallback

```text
Audio
→ STT
→ Conversation Core
→ TTS
→ Audio
```

### 저장 정책

- transcript 저장은 사용자 고지 후 선택
- 원본 음성은 기본 비저장
- 품질 평가용 샘플은 별도 동의

## 12.4 화상

- `getUserMedia`로 카메라 획득
- 로컬 미리보기 제공
- 명시적 시작/중지 버튼
- 음성 스트림과 별개로 프레임 샘플링
- 제품·문서·화면 이해에 필요한 순간만 프레임 전송
- 얼굴 인식·감정 판정은 범위에서 제외

---

# 13. 사용자·관리자 화면

## 13.1 사용자 화면

```text
/home
/chat
/voice
/video
/shop
/products/:id
/cart
/orders
/bounties
/profile/security
```

필수 UI:

- 모델·도구 내부 추론은 숨기되, 사용한 출처와 수행한 행동은 표시
- 상품 비교표와 추천 이유
- 가격·재고 관측 시각
- 주문 전 최종 확인
- 카메라·마이크 사용 표시
- 데이터 삭제·동의 관리

## 13.2 관리자 대시보드

```text
/admin/overview
/admin/users
/admin/documents
/admin/ingestion
/admin/conversations
/admin/orders
/admin/bounties
/admin/agents
/admin/models
/admin/evaluations
/admin/reports
/admin/audit
```

KPI:

- 질문 수·채널별 사용량
- 답변 근거 충족률
- 검색 hit/recall
- 모델별 지연·비용·오류
- 상품 추천 클릭·장바구니·주문 전환
- 바운티 응답률·검증 통과율
- 승인 없는 쓰기 시도
- 문서 버전·실패 ingest

## 13.3 보고서

- 통계 계산은 SQL/Python으로 수행
- LLM은 서술 요약만 생성
- 보고서에는 생성 시각, 필터, 데이터 버전, 모델 ID를 기록
- 저장 버전은 수정 이력을 유지
- 인쇄 전용 CSS와 PDF 변환 옵션 제공

---

# 14. 인증·권한·보안

## 14.1 인증

- 1차: 비밀번호 또는 OAuth 로그인
- 2차: Passkey/WebAuthn 권장
- 복구: recovery code 또는 관리자 승인 절차
- 얼굴 생체정보는 운영체제/기기 인증기에 남고 서버는 공개키 challenge 결과만 검증

## 14.2 역할

```text
USER
ADMIN
SELLER
PROVIDER
VALIDATOR
AUDITOR
SYSTEM
```

## 14.3 보안 필수 항목

- Tool별 최소 scope
- 사용자 승인 경계
- SQL/Vector ACL 필터
- 프롬프트 인젝션 테스트
- 파일 업로드 MIME·크기·악성 검사
- 비밀정보 탐지·마스킹
- audit log immutable append
- 주문·포인트 트랜잭션
- SSRF·경로 이동·원격 URL 수집 제한
- 외부 모델로 전송되는 데이터 분류
- 관리자 보고서 PII 마스킹

---

# 15. 데이터베이스 개요

```text
users
credentials
roles
passkeys
conversation_sessions
messages
documents
document_versions
chunks
embeddings
retrieval_logs
products
offers
inventory_snapshots
carts
cart_items
orders
order_events
agents
agent_capabilities
agent_data_sources
bounties
bounty_submissions
validations
challenges
point_ledger
model_registry
model_runs
tool_runs
reports
audit_logs
```

핵심 제약:

- `point_ledger`는 append-only
- `order_events`는 상태 이력 보존
- `offers`는 `observed_at` 필수
- `document_versions`는 checksum 유일성
- `model_runs`와 `tool_runs`는 trace_id 연결

---

# 16. API 계약 예시

## API-COM-01 구매 의도

```json
POST /api/v1/commerce/intents
{
  "query": "RTX 4070 SUPER PC에 맞는 64GB RAM을 25만원 아래로 찾아줘",
  "user_context": {
    "owned_components": ["RTX 4070 SUPER"]
  }
}
```

```json
{
  "intent_id": "int_123",
  "category": "desktop_memory",
  "constraints": {
    "capacity_gb": 64,
    "budget_max_krw": 250000
  },
  "missing_fields": ["motherboard_model"],
  "requires_clarification": true
}
```

## API-RAG-01 질의

```json
POST /api/v1/qa
{
  "question": "환불 기간과 배송비 부담 주체는?",
  "scope": ["policy"],
  "channel": "text"
}
```

## API-BNT-01 바운티

```json
POST /api/v1/bounties
{
  "question": "후보 RAM의 보드 호환성 근거를 제출하라",
  "required_evidence": ["official_spec", "installation_case"],
  "reward_points": 1000,
  "expires_at": "2026-07-20T18:00:00+09:00"
}
```

---

# 17. 테스트 전략

## 17.1 테스트 피라미드

1. Domain unit tests
2. Application use case tests with fake ports
3. Adapter contract tests
4. API/MCP integration tests
5. LangGraph workflow tests
6. RAG evaluation
7. Model matrix tests
8. Browser E2E
9. Security/adversarial tests
10. Demo rehearsal

## 17.2 RAG 평가셋

```json
{
  "question": "단순 변심 반품 기한은?",
  "expected_answer_contains": ["7일"],
  "expected_source": "return_policy_v2026_07",
  "answerable": true,
  "forbidden_claims": ["무료 반품"]
}
```

평가 지표:

- Retrieval Recall@K
- MRR/NDCG
- Citation Precision
- Citation Completeness
- Faithfulness/Supported Claim Rate
- Answer Correctness
- Abstention Accuracy
- ACL Leakage Rate

## 17.3 모델 매트릭스

| Test | GPT | Gemini | Qwen3.6 | Gemma 4 |
|---|---:|---:|---:|---:|
| 구조화 의도 추출 | ✓ | ✓ | ✓ | ✓ |
| 한국어 RAG QA | ✓ | ✓ | ✓ | ✓ |
| Tool call schema | ✓ | ✓ | ✓ | ✓ |
| 장문 문서 | ✓ | ✓ | 측정 | 측정 |
| 이미지/프레임 | 모델별 | ✓ | 모델별 | ✓ |
| 로컬 민감 데이터 | 금지/옵션 | 금지/옵션 | ✓ | ✓ |
| 지연·비용 | 측정 | 측정 | 측정 | 측정 |

## 17.4 보안 테스트

- 문서 안의 “시스템 지시 무시” 문구
- 악성 상품 설명의 결제 Tool 유도
- 다른 사용자 주문 조회
- Provider의 다른 디렉터리 접근
- 중복 idempotency key
- 위조 evidence hash
- report prompt injection
- WebAuthn replay
- MCP token audience mismatch

## 17.5 통과 기준 예시

- 승인 없는 주문 생성: 0
- 권한 밖 문서 노출: 0
- 구조화 출력 schema 실패: 1% 미만, 재시도 후 0
- 핵심 RAG 평가셋 supported claim rate: 95% 이상
- 핵심 질문 abstention accuracy: 90% 이상
- 주문/원장 중복 처리: 0
- MCP write tool confirmation bypass: 0

---

# 18. 통합 개발 로드맵

기존 기능이 있으므로 전면 신규 개발이 아니라 **8주 통합 릴리스**를 기준으로 한다. 1인 개발이면 각 단계를 늘릴 수 있으나 하나의 최종 통합 버전으로 완료한다.

| 주차 | 단계 | 핵심 작업 | Gate |
|---:|---|---|---|
| 0 | 현행 감사 | 실행, 의존성, API, DB, 테스트, 보안 목록화 | 모든 기존 기능 smoke test |
| 1 | 경계 정리 | Domain/Application/Adapter skeleton, DTO, model registry | 기존 UI가 새 use case 호출 |
| 2 | RAG 고도화 | ingestion, metadata, hybrid retrieval, citation | 평가셋 baseline |
| 3 | 모델 라우터 | GPT/Gemini/Qwen3.6/Gemma4 adapters, fallback | 공통 contract test |
| 4 | 커머스 통합 | 의도·검색·비교·장바구니·승인 주문 | 승인 없는 주문 0 |
| 5 | 바운티 | Provider/Validator, 상태 머신, 포인트 원장 | ground truth 평가 |
| 6 | 음성·화상·인증 | Realtime, camera frames, Passkey | 브라우저 E2E |
| 7 | 관리자·보고서 | KPI, 모델 비용, RAG 평가, 저장·인쇄 | 보고서 재현 가능 |
| 8 | 안정화·제출 | 보안, 회귀, 발표자료, 시연영상 | 제출물 체크리스트 100% |

## 18.1 병렬 팀 작업

- Track A Backend: Domain, Repository, Order, Auth
- Track B AI/RAG: Ingestion, Retrieval, Prompt, Model adapters
- Track C Agent/MCP: Graph, tools, bounty workflow
- Track D Frontend: chat, shop, voice/video, admin
- Track E QA/Infra: CI, observability, deployment, reports

주차 1의 DTO·포트 계약이 확정되면 Track A~E를 병렬로 진행한다.

---

# 19. 제출물 매핑

| 요구 제출물 | 프로젝트 산출물 | 파일/폴더 예시 |
|---|---|---|
| 수집 데이터·전처리 문서 | 데이터 카탈로그, 라이선스, 파서, 청킹, 품질 결과 | `docs/data/`, `data_manifest.json` |
| 시스템 아키텍처 보고서 | Clean Architecture, RAG, 모델, MCP, 보안, 다이어그램 | 본 HTML + `docs/architecture/` |
| 개발 소프트웨어 | FastAPI, RAG, Vector DB, Agent, MCP, UI | `src/`, `frontend/`, `tests/` |
| 테스트 계획·결과 발표 보고서 | 평가셋, 자동 테스트, 결과 그래프, 리스크 | `docs/test-report/` |
| 시연영상 | 통합 시나리오 녹화 | `demo/demo-script.md`, 영상 링크 |
| 추가 서비스 1 | 텍스트 고객 상담 | `/chat` |
| 추가 서비스 2 | 음성 상담 | `/voice` |
| 추가 서비스 3 | 화상 상담 | `/video` |
| 추가 서비스 4 | 사용자/관리자 분리 | `/`, `/admin` |
| 추가 서비스 5 | 로그인 + 얼굴 기반 2차 인증 | WebAuthn/Passkey |
| 추가 서비스 6 | 관리자 보고서 저장·인쇄 | `/admin/reports` |

---

# 20. 최종 시연 시나리오

1. 관리자가 환불정책 PDF와 제품 매뉴얼을 업로드한다.
2. Ingestion 화면에서 파싱·청킹·임베딩·버전·오류를 확인한다.
3. 사용자가 Passkey로 2차 인증한다.
4. 텍스트로 환불정책을 질문하고 출처를 확인한다.
5. 음성 상담으로 상품 조건을 말한다.
6. 카메라로 현재 부품 라벨을 보여주고 모델명을 인식한다.
7. Buyer Agent가 구매 의도를 구조화하고 상품을 검색한다.
8. 호환성 근거가 부족한 상품에 지식 바운티가 생성된다.
9. 서로 다른 로컬 데이터를 가진 Qwen3.6/Gemma 4 Provider가 답한다.
10. Validator가 근거를 검증하고 추천 순위를 갱신한다.
11. 사용자가 상품을 선택하고 주문 미리보기를 승인한다.
12. 샌드박스 주문이 생성되고 주문 이력이 표시된다.
13. 관리자가 대화·RAG·모델·주문·바운티 KPI 보고서를 생성해 저장·인쇄한다.
14. 동일한 상품 검색과 바운티 결과를 MCP Inspector 또는 외부 클라이언트에서 호출한다.

---

# 21. Definition of Done

통합 버전은 다음을 모두 충족해야 완료다.

- [ ] 기존 기능 회귀 테스트 통과
- [ ] 4개 모델군 공통 contract test 통과
- [ ] RAG 문장별 출처와 abstention 구현
- [ ] 상품 가격·재고·주문은 결정론적 데이터 사용
- [ ] 구매 승인 interrupt 구현
- [ ] Provider 데이터 격리
- [ ] Validator + hidden ground truth 평가
- [ ] 내부 포인트 원장 멱등성
- [ ] MCP read/write scope와 confirmation
- [ ] 텍스트·음성·화상 시연
- [ ] Passkey 2차 인증
- [ ] 사용자·관리자 화면 분리
- [ ] 관리자 보고서 저장·인쇄
- [ ] 보안·프롬프트 인젝션 테스트
- [ ] 테스트 결과 보고서
- [ ] 시연영상

---

# 22. 구현 LLM에게 전달할 최초 작업 지시

```text
1. 저장소를 변경하기 전에 전체 디렉터리, 의존성, 실행법, DB schema, API, MCP tools, LangGraph, frontend routes를 조사한다.
2. 기존 기능별 smoke test를 작성하고 현재 결과를 baseline으로 저장한다.
3. 전면 재작성하지 말고 ModelGateway, RetrieverPort, Repository, PaymentPort, UseCase 경계를 먼저 추가한다.
4. 기존 코드를 adapters/legacy 아래에서 포트를 구현하도록 감싼다.
5. 각 PR은 하나의 REQ ID만 중심으로 하고, API schema와 테스트를 함께 수정한다.
6. LLM 출력은 Pydantic schema 검증 후만 사용한다.
7. 상품·주문·권한·포인트 변경은 LLM 출력이 아니라 Application Service가 수행한다.
8. 외부 모델·DB 없이 테스트 가능한 Fake Adapter를 먼저 만든다.
9. 모델 버전과 prompt 버전을 모든 model_run에 기록한다.
10. 구현 후 문서의 Definition of Done 체크리스트를 자동 테스트 결과와 연결한다.
```

---

# 23. 조사·검증 출처

공식 문서 우선. 조회 기준일: 2026-07-18.

1. OpenAI Models — https://platform.openai.com/docs/models
2. OpenAI Responses API migration — https://platform.openai.com/docs/guides/migrate-to-responses
3. OpenAI Realtime API — https://platform.openai.com/docs/guides/realtime
4. Google Gemini models — https://ai.google.dev/gemini-api/docs/models
5. Google Gemini Live API — https://ai.google.dev/gemini-api/docs/live
6. Google Gemini Function Calling — https://ai.google.dev/gemini-api/docs/function-calling
7. Qwen3.6 official repository — https://github.com/QwenLM/Qwen3.6
8. Gemma 4 12B Developer Guide — https://developers.googleblog.com/gemma-4-12b-the-developer-guide/
9. LangGraph overview — https://docs.langchain.com/oss/python/langgraph/overview
10. LangChain agents — https://docs.langchain.com/oss/python/langchain/agents
11. MCP specification 2025-11-25 — https://modelcontextprotocol.io/specification/2025-11-25
12. MCP security best practices — https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices
13. MCP authorization — https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
14. A2A Protocol — https://a2a-protocol.org/latest/
15. Cafe24 Developers — https://developers.cafe24.com/
16. WebAuthn Level 3 — https://www.w3.org/TR/webauthn-3/
17. FIDO Passkeys — https://fidoalliance.org/passkeys/
18. pgvector — https://github.com/pgvector/pgvector
19. OpenTelemetry — https://opentelemetry.io/docs/
20. OWASP Top 10 for LLM Applications — https://owasp.org/www-project-top-10-for-large-language-model-applications/

## 검토한 기존 교육 자료

- `4_RAG_아키텍쳐.pdf`
- `5_MCP이해_서버구축.pdf`
- `6_LangGraph_멀티에이전트1.pdf`
- `7_LangGraph_멀티에이전트2.pdf`
- `3_ReAct_에이전트구현.pdf`
- 기존 `AI_네이티브_커머스_지식바운티_MVP_계획서.docx`
