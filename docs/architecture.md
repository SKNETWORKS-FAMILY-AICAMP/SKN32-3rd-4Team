# 바로봄 AI 커머스·지식 상담 플랫폼 — 시스템 아키텍처 설계 보고서

> 제출물 요구사항 "시스템 아키텍처 설계 보고서(다이어그램 반드시 포함)" 대응 문서.
> 다이어그램은 Mermaid로 작성돼 GitHub/GitLab·호환 뷰어에서 바로 렌더된다.

## 1. 개요

RAG 기반 문서 질의응답을 코어로, 커머스 승인 루프·AI 에이전트(ReAct+CoT)·MCP·RBAC 관리자와
음성/화상 상담·얼굴 로그인 2차 인증까지 통합한 로컬 우선(무API키 기본) 플랫폼이다. 설계 원칙은
**개념적 Clean Architecture + 무폴백(RULE.md)**: 오류를 그럴듯한 가짜 결과로 대체하지 않고
정의된 타입(ConfigError/InfraError/LLMOutputError/ValidationErr…)으로 명시적으로 실패시킨다.

## 2. 계층형 아키텍처 (Clean Architecture)

```mermaid
flowchart TB
  subgraph IF["Interface 계층 · FastAPI 라우터"]
    R1["agent / rag / orders / products / payments"]
    R2["auth / admin / face / voice / nlp / lab / mcp / a2a / workflow"]
    UI["정적 UI(static): shop · index · video · mypage · facebench · admin"]
  end
  subgraph APP["Application 계층 · 프레임워크 무의존 (TEST-ARCH-001)"]
    UC1["AnswerQuestion(RAG)"]
    UC2["Preview/PlaceOrder(커머스)"]
    UC3["SelfVerify(CoT) · ChatCommerce"]
    P["Ports: RetrieverPort · ModelGateway · RerankerPort · CatalogPort · OrderRepositoryPort"]
  end
  subgraph AD["Adapter 계층"]
    A1["FAISS / pgvector / Hybrid(RRF) / GraphRAG / Reranker 리트리버"]
    A2["llm_gateway(모델 레지스트리) · sql_catalog · sql_order_repo · react_agent_adapter"]
  end
  subgraph INFRA["Infra / 외부"]
    D1["SQLite(SQLAlchemy)"]
    D2["PostgreSQL + pgvector + pg_trgm(그래프/렉시컬)"]
    D3["FAISS 인덱스"]
    D4["로컬 Gemma(llama-cpp, OpenAI 호환)"]
    D5["onnxruntime-directml(얼굴 인식 가속)"]
  end
  subgraph ML["ML/부가"]
    M1["voice: faster-whisper(STT) · pyttsx3(TTS)"]
    M2["face: insightface·AdaFace·LVFace + Silent-Face(라이브니스)"]
    M3["sentiment(KoELECTRA) · intent · recommend"]
  end
  MCP["MCP 서버(FastMCP, stdio) · 10 tools · REST parity"]
  A2A["A2A: 전문 에이전트 카드 발견 + 위임<br/>order · catalog · knowledge · recommend"]

  UI --> IF
  IF --> APP
  APP --> P
  P --> AD
  AD --> INFRA
  IF --> ML
  IF --> MCP
  IF --> A2A
  MCP -.같은 유스케이스/프리젠터 공유.-> APP
  A2A -.기존 커머스/RAG/추천 서비스 재사용(중복 없음).-> AD
```

핵심: **Application 계층은 FastAPI·SQLAlchemy·LangChain·openai를 import하지 않는다**(정적 스캔
테스트 TEST-ARCH-001로 강제). 유스케이스는 포트(인터페이스)에만 의존하고, 구체 기술(FAISS vs
pgvector vs 그래프)은 어댑터가 갈아끼운다 — 그래서 같은 `AnswerQuestion`이 4가지 리트리버를 모두
재사용한다.

## 3. RAG 질의응답 파이프라인

```mermaid
flowchart LR
  Q["질문"] --> RT{"RetrieverPort<br/>(backend 선택)"}
  RT -->|faiss| F["FAISS 벡터검색"]
  RT -->|hybrid| H["pgvector(dense) + pg_trgm(lexical)<br/>RRF 결합 → LLM Reranker"]
  RT -->|graph| G["PostgreSQL 네이티브 그래프<br/>(노드/엣지 + 재귀 CTE)"]
  F --> EV["근거(Evidence) + 출처"]
  H --> EV
  G --> EV
  EV -->|근거 있음| GEN["ModelGateway(Gemma)<br/>근거만 사용해 생성"]
  EV -->|근거 없음| AB["abstention(생성 안 함)"]
  GEN --> ANS["답변 + 출처 인용"]
  AB --> KG["지식갭 큐 적재<br/>(PII 마스킹 후, 관리자 확인용)"]
```

무폴백 포인트: 근거가 없으면 **생성하지 않고 abstention**(환각 억제)하고, 답 못한 질문은
PII를 마스킹해 지식갭 큐에 남겨 운영자가 보강한다.

## 4. 커머스 승인 루프 (Preview → Approve, 멱등)

```mermaid
sequenceDiagram
  participant C as 고객(shop.html)
  participant O as /api/orders
  participant UC as PlaceOrder(Application)
  participant DB as DB(재고·주문·멱등키)
  C->>O: POST /preview (읽기전용)
  O-->>C: 재고·소계·합계·feasible
  C->>O: POST / (Idempotency-Key 필수)
  O->>UC: place(user, lines, key)
  UC->>DB: 같은 키+같은 지문? → 기존 주문 재생(재고차감 0)
  UC->>DB: 새 요청 → 조건부 원자 차감(UPDATE WHERE stock≥qty)
  DB-->>UC: 성공/409(키 충돌)/422(재고부족·키없음)
  UC-->>C: 주문번호·상태
```

`Idempotency-Key`는 필수(서버 UUID 폴백 금지) — 무폴백을 위해 계약을 의도적으로 강화했다.

## 5. 얼굴 로그인 2차 인증 (opt-in)

```mermaid
sequenceDiagram
  participant U as 사용자
  participant A as /auth/login
  participant F as /auth/login/face
  participant ML as face.py 파이프라인
  U->>A: 아이디/비밀번호
  A-->>U: 얼굴 미등록? → 최종 토큰 / 등록? → pre2fa 챌린지 토큰
  U->>F: 챌린지 + 얼굴 이미지
  F->>ML: 단일(앞) 얼굴 → 품질 게이팅 → 라이브니스(Silent-Face) → 임베딩(AdaFace/DirectML)
  ML-->>F: 라이브니스·매칭(코사인≥임계)?
  F-->>U: 통과 → 최종 토큰 / 실패 → 401(일반 메시지·감사 로그·시도 제한)
```

게이트 순서와 무폴백: 어느 단계든 실패하면 토큰을 발급하지 않으며, 얼굴 실패 시 비밀번호만으로
폴백하지 않는다. `stage`(full/pre2fa) 클레임으로 2차 인증 미완료 토큰은 보호 리소스 접근을 막는다.

## 6. 기술 스택

| 영역 | 선택 | 근거 |
|---|---|---|
| API | FastAPI | 라우터 단위 fail-closed 의존성(예: 관리자 require_admin) |
| RAG | FAISS + pgvector(RRF Hybrid) + GraphRAG + LLM Reranker | 학습 트랙 넓게, 포트로 교체식 |
| LLM | 로컬 Gemma(llama-cpp, OpenAI 호환) · 모델 레지스트리 | 무API키 기본, 모델ID 하드코딩 금지 |
| DB | SQLite(코어) + PostgreSQL/pgvector/pg_trgm(학습 트랙) | 무료 PG 한 곳에 벡터·그래프·렉시컬 통합 |
| 에이전트 | ReAct 루프 + CoT SelfVerify | 미지지 초안 차단, 인젝션 경계 방어 |
| MCP | FastMCP(stdio) 10 tools | REST와 유스케이스/프리젠터 공유(parity) |
| A2A | 에이전트 카드 발견 + 전문 에이전트 위임(order/catalog/knowledge/recommend) | 능력의 공개 발견 + 위임 프로토콜, 기존 서비스 재사용(중복 없음), 미등록/빈입력 무폴백 |
| 음성 | faster-whisper(STT, CPU int8) · pyttsx3(TTS, SAPI5) | 로컬·무API키 |
| 얼굴 | insightface(검출/정렬) + AdaFace(인식, 기본) + Silent-Face(라이브니스) | 저품질 특화 AdaFace, DirectML 7× 가속(Iris Xe) |
| 보고서 | reportlab(PDF, 한글 폰트 임베딩) | 관리자 요약 보고서 생성/저장/인쇄 |

## 7. 고객 웹 ↔ 운영 도구 분리 (실제 프로덕션 패턴)

실무에서는 고객 사이트와 관리자 대시보드를 **별도 서비스/포트/서브도메인**으로 나누고, 관리자
쪽은 VPN·사내망·IP 화이트리스트 뒤에 둬 공개 인터넷에 노출하지 않는다. 이 프로젝트는 그 패턴을
**두 개의 ASGI 앱 + 두 포트**로 축소 재현한다.

```mermaid
flowchart LR
  subgraph PUB["공개 (인터넷)"]
    C["고객<br/>브라우저"]
  end
  subgraph INT["내부 (VPN/사내망 가정)"]
    O["운영자"]
  end
  C -->|":8080"| CA["customer_app<br/>관리자 라우터 미포함<br/>운영 정적페이지 차단"]
  O -->|":8081"| AA["admin_app<br/>관리자 대시보드 + 운영 도구 전체"]
  CA --> DB[("공유 DB/모델")]
  AA --> DB
```

- `customer_app`(8080): `/api/admin/*`뿐 아니라 **운영/내부 API 라우터(rag·nlp·lab·mcp·a2a·workflow)도
  물리적으로 404**(라우터를 싣지 않음) — 고객 웹이 호출하지 않는 분석·프로토콜·개발 엔드포인트를
  공개 포트에서 제거해 무인증 노출·모델연산 DoS 표면을 줄인다. 공개되는 건 상품·주문·결제·에이전트·
  음성·얼굴뿐. 운영 정적 페이지(admin/facebench/mcp/rag/orders)도 404. 실측: 8080에서
  `/api/admin/orders`→404, `/api/rag/search`→404, `/static/admin.html`→404, `/static/shop.html`→200.
- `admin_app`(8081): 관리자 대시보드 + 운영 도구 전체. 실측: `/api/admin/orders`→401(인증필요),
  `/static/admin.html`→200.
- 실행: `python -m scripts.run_customer_server` / `python -m scripts.run_admin_server`.
  (`run_dev_server.py`의 전체 앱은 테스트·개발 편의용.)

## 8. 관측성·보안·거버넌스

- **관측성**: 요청별 trace_id(X-Trace-ID) + run_events(요약만, 원문·PII 금지).
- **RBAC**: role을 JWT에 넣지 않고 매 요청 DB 조회(강등 즉시 반영). 관리자 라우터 전역
  `require_admin` fail-closed. 관리자 승격은 **CLI 전용**(UI 버튼 없음, 권한상승 사고 방지).
- **2차인증 토큰 위생**: pre2fa 챌린지에 고유 jti를 부여해 **성공 시 일회성으로 소비**(리플레이
  차단), 미완료(pre2fa) 토큰은 보호 리소스 접근 불가. 업로드 엔드포인트(얼굴·음성)는 config
  상한(`FACE_MAX_UPLOAD_BYTES`/`VOICE_MAX_UPLOAD_BYTES`)으로 크기를 제한하고, 3모델을 모두 도는
  얼굴 벤치마크는 **관리자 전용**으로 무인증 모델연산 DoS 표면을 줄인다.
- **PII**: 지식갭·이벤트는 마스킹 후 저장, 출력 시 마스킹이 값을 바꾸면 조용히 덮지 않고 감사
  이벤트를 남긴다(무폴백).
- **거버넌스**: docs/plans·history·reports append-only, 각 Phase마다 Codex 교차검증.
- **지식 검증의 범위(중요)**: 이 시스템은 **사실성을 판정하지 않는다.** RAG 답변이든 향후
  지식 바운티든, 기계적으로 확인하는 것은 **근거성**(제시된 근거가 주장을 지지하는가 —
  SupportCheck) · **재현성**(출처를 다시 열어 확인 가능한가) · **중복성**뿐이다. 근거 자체가
  거짓·조작·낡은 경우는 통과한다. 따라서 "검증된 지식"이라는 무한정 표현을 쓰지 않고
  "제시된 근거로 재현 확인된 답변"이라고만 말한다. 상세: [지식 바운티 검증모델 재설계](plans/2026-07-22_2100_지식바운티_검증모델_재설계.md).

## 9. 한계 (정직 기록)

- 얼굴 라이브니스는 단일 모델(앙상블 아님)·헤드리스 환경에서 실 웹캠 라이브 정확도 미검증.
- 시도 제한·일회성 챌린지 소비는 **인메모리**(프로세스 재시작 시 초기화·멀티프로세스 미공유) —
  데모 한계. 챌린지 소비는 단일 프로세스 asyncio 내에선 원자적(동시요청 1개만 통과)이나,
  멀티프로세스·재시작 무결성은 공유 저장소(Redis 등 atomic SETNX)가 필요하다.
- 업로드 크기 상한은 우리가 처리에 올리는 바이트를 제한하는 것으로, ASGI가 multipart를 파싱한
  뒤 동작한다 — HTTP 요청 자체의 크기 상한(리버스 프록시/`--limit-*`)은 배포 레이어의 몫이다.
- 얼굴 매칭 임계값은 실 genuine/impostor 분포(FAR/FRR)로 튜닝되지 않은 시작값.
- DirectML은 Windows 전용(비Windows는 plain onnxruntime로 CPU).
- MCP stdio 임베딩 도구 지연은 우회책(근본원인 미특정).
- A2A는 **인프로세스 함수 위임 façade**다(참조 구현과 동급) — 카드 발견 + 명시적 위임은 실제로
  하지만, 원격 HTTP 에이전트 통신·작업 수명주기·표준 Agent Card(`/.well-known`) 상호운용까지
  갖춘 완전한 A2A 프로토콜은 아니다. 운영 API(a2a/mcp/rag 등)는 고객 포트에서 404이며, 운영
  포트는 VPN·사내망 뒤(내부)를 가정해 별도 인증을 두지 않는다(분리 모델).
- **지식의 사실성은 보장하지 않는다**(원리적 한계). 근거가 거짓이면 근거성 검사를 통과한다.
  지식 바운티는 이 한계를 인정하고 "진실 판정" 대신 근거성 검증 + 경제적 억제(escrow·
  제한적 slash·표본감사)로 설계를 교정했다(위 재설계 문서). 현재 **바운티는 미구현**이다.
- 시연영상은 별도(본 문서 범위 밖).

---
- 실행/재현: `python -m scripts.manage migrate|seed|ingest` → `python scripts/run_dev_server.py`
- 화면 캡처: `docs/index.html`(갤러리), `docs/screenshots/`
