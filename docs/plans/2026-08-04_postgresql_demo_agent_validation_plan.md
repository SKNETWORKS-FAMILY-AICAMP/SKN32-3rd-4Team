# 합성 에이전트 트랙 PostgreSQL 개편 계획

작성일: 2026-08-04  
대상: 합성 제출·검증 이벤트·코호트 집계·시뮬레이터  
제외: 실제 청구 사례 저장소, 보험금 지급 진위 자동판정, 기존 약관/pgvector 색인

## 1. 현재 상태와 바로잡을 표현

- 현재 `auto_verify=True`는 판정 에이전트가 아니다. 제출 직후 조건 없이
  `method=simulated`로 합성 코호트에 승격하는 데모 동작이다.
- `/v1/prechecks`의 약관 규칙 판정과 MCP 호출 자동화는 별도 기능이다. 이것이
  보험 보장 가능성을 약관 근거로 판단하며, 합성 사례의 진위를 승인하지는 않는다.
- 이번 작업은 무조건 승격을 **결정론적 합성 정합성 게이트**로 교체한다. 게이트 통과는
  진위 확인이나 보험금 승인 판정이 아니며 UI·API·감사기록에 그 한계를 표시한다.

## 2. 설계 결정

1. 합성 트랙은 기존 `mall_vec`이나 실제 사례 DB에 넣지 않고 별도 PostgreSQL DB
   `insurance_demo`의 `demo` 스키마에 저장한다.
2. 런타임은 `DEMO_STORE_BACKEND=file|postgres`로 명시적으로 선택한다. PostgreSQL을
   선택한 상태에서 연결·스키마가 준비되지 않으면 `InfraError`로 실패하며 파일로 폴백하지 않는다.
3. `demo.submission`은 멱등성 키와 payload hash를 함께 저장한다. 같은 키·같은 요청은
   기존 결과를 반환하고, 같은 키·다른 요청은 충돌로 거절한다.
4. `demo.verification_event`는 append-only 이력이다. 별도 PK를 사용하고, 한 제출의
   accepted 이벤트는 부분 유일 인덱스로 한 건만 허용한다.
5. 제출 저장과 자동 정합성 검증 이벤트 기록은 한 트랜잭션에서 처리한다.
6. 합성 집계는 `insurance_demo`만 조회한다. 실제 트랙과 UNION하지 않는다.
7. 파일 이관은 dry-run → 멱등 upsert → count/hash 대조 → 설정 전환 순서로 수행한다.

## 3. 자동 정합성 게이트

규칙 버전: `synthetic-consistency-v2`

- [x] 합성 시뮬레이터가 부여한 `run_id`가 존재한다.
- [x] 멱등성 키가 `run_id + agent + case ordinal`과 일치한다.
- [x] 보험사가 시뮬레이터 허용 목록에 있다.
- [x] 가입일이 실제 달력의 `YYYYMMDD` 형식이다.
- [x] KCD가 정확히 한 개이며 단일 코드 형식이다(범위 불가, 소수점 허용).
- [x] KCD가 시뮬레이터의 고정 참조 카탈로그에 존재한다.
- [x] 연령대와 outcome이 허용 목록에 있다.
- [x] 중복 키의 payload hash 충돌이 없다.
- [x] 모든 검사 결과·규칙 버전·사유 코드가 검증 이벤트에 남는다.

통과 등급은 `synthetic_consistency`다. `document_backed`, `verified_real`, 보험금
`approved`라는 표현을 사용하지 않는다.

## 4. 구현 체크리스트

### A. 스키마·설정

- [x] `scripts/db/demo/001_demo.sql` 작성
- [x] 상태·method·decision CHECK, FK, 부분 UNIQUE, run/client/time 인덱스 추가
- [x] evidence JSON 크기 상한 추가
- [x] 마이그레이션 적용기를 core/demo 트랙으로 분리
- [x] `DEMO_STORE_BACKEND`, `DEMO_PG_DSN` 설정과 `.env.example` 추가
- [x] PostgreSQL 선택 시 readiness 검사 추가

### B. 저장소·집계

- [x] PostgreSQL 합성 제출 store/pending/counts 구현
- [x] `INSERT ... ON CONFLICT` 후 payload hash 비교 구현
- [x] 검증 이벤트 원자 기록과 중복 accepted 차단 구현
- [x] 합성 코호트 PG 집계 구현
- [x] 실제 트랙 파일 집계와 물리적으로 분리된 조립 구현
- [x] 합성 트랙 초기화를 demo DB에만 제한

### C. 검증 게이트·표현

- [x] 순수 결정론적 gate 함수와 규칙 버전 구현
- [x] `auto_verify` 호환 입력을 gate 실행 의미로 변경
- [x] UI/CLI에서 “자동 승격”을 “자동 합성 정합성 검사”로 교체
- [x] 진위·보험금 승인 자동판정이 아니라는 안내 추가
- [x] run_id·검증 방법·규칙 버전을 상태/감사 결과에 노출
- [x] API의 접수 성공과 코호트 승격 여부를 별도 필드로 노출

### D. 이관·검증

- [x] 파일→PG dry-run/적용 스크립트 작성
- [x] 제출 수·승격 수·payload hash 대조
- [x] 같은 이관을 재실행해도 증가하지 않는지 검증
- [x] PostgreSQL 미기동·스키마 누락 시 무폴백 실패 검증
- [x] 같은 seed 두 번째 실행 신규 제출 검증
- [x] 합성 데이터가 실제 트랙에 0건 유입되는지 검증
- [x] 기존 파일 모드 회귀검사 유지

## 5. 완료 기준(DoD)

- [x] 로컬 `insurance_demo` DB에 마이그레이션이 checksum ledger와 함께 적용된다.
- [x] 기존 파일 산출물이 손실 없이 이관되고 count/hash 대조가 일치한다.
- [x] 대시보드 반복 실행에서 두 번째 실행도 신규 제출되며 동일 사례 재시도만 중복이다.
- [x] 자동 모드는 게이트 실패 건을 승격하지 않고 사유를 남긴다.
- [x] 합성 코호트 응답은 `synthetic_consistency` 등급과 합성 경고를 표시한다.
- [x] PostgreSQL 장애를 파일 결과로 위장하지 않는다.
- [x] 단위·통합·실 PostgreSQL 테스트와 기존 회귀 테스트가 통과한다.

## 6. Claude CLI 교차검토 반영

Claude는 다음 위험을 지적했고 설계에 반영했다.

- 검증 테이블에서 `submission_id`를 PK로 쓰지 말고 append-only 이력 PK를 별도로 둔다.
- 멱등성은 사전 조회가 아니라 DB UNIQUE + `ON CONFLICT`로 원자 처리한다.
- 제출과 검증 이벤트는 단일 트랜잭션으로 기록한다.
- `run_id`, 상태값, 검증 시각, evidence 크기에 DB 제약을 둔다.
- 실제 트랙 이관과 LLM 기반 진위판정은 1차 범위에서 제외한다.
- 재논의에서 형식상 유효하지만 시뮬레이터 카탈로그에 없는 KCD를 막는 참조값
  존재 검사와, API의 `received`/`accepted_for_cohort` 의미 분리를 추가했다.
