# 합성 에이전트 PostgreSQL 개편 및 자동 정합성 검사 결과

작성일: 2026-08-04

## 결론

합성 에이전트 제출·검증·코호트 집계를 파일에서 별도 PostgreSQL DB
`insurance_demo`로 전환했다. 기존 파일은 보존했으며 현재 `.env`는
`DEMO_STORE_BACKEND=postgres`를 선택한다. DB 장애 시 파일로 폴백하지 않는다.

기존 `auto_verify`는 판정 에이전트가 아니었고, 아무 검사 없이 합성 제출을
`simulated`로 승격했다. 이를 규칙 버전 `synthetic-consistency-v2`의 결정론적
정합성 게이트로 교체했다. 통과 등급은 `synthetic_consistency`이며 실제 지급 진위,
보험금 승인, 약관상 보장 확정을 뜻하지 않는다.

## 구현 결과

- 별도 DB/스키마: `insurance_demo.demo`
- 테이블: `demo.submission`, `demo.verification_event`
- 합성 전용 뷰: `demo.accepted_cohort_event`
- 멱등성: `(client_ref, idempotency_key)` UNIQUE + `ON CONFLICT`
- 충돌 검증: 동일 키의 payload SHA-256이 다르면 `ConflictErr(409)`
- 검증 이력: append-only, 한 제출의 accepted만 부분 UNIQUE
- 원자성: 신규 제출과 자동 정합성 이벤트를 한 트랜잭션으로 기록
- 격리: `insurance_demo`에는 `app/core/ops` 실제 사례 스키마가 없음
- readiness: `/api/health/ready`에 `demo_store.backend=postgres`, `ready=true`
- 초기화: 합성 DB의 두 테이블만 대상으로 하며 실제 트랙 경로를 참조하지 않음

## 자동 정합성 검사

검사 항목:

1. run_id 형식
2. 에이전트 식별자와 사례 순번
3. run_id·agent·case ordinal 기반 멱등성 키 일치
4. 허용 보험사
5. 실제 달력 기준 가입일
6. 단일 KCD 코드 형식(소수점 허용, 범위 불가)
7. 허용 연령대와 outcome
8. 합성 전용 라우트
9. 시뮬레이터가 사용하는 고정 KCD 참조 카탈로그 존재 여부

모든 검사 결과, 규칙 버전, 실패 사유는 검증 이벤트에 저장한다. 실패 제출도
감사를 위해 보존하지만 accepted 이벤트가 없으므로 코호트에는 들어가지 않는다.

## 이관 결과

| 항목 | 원본 파일 | PostgreSQL | 결과 |
|---|---:|---:|---|
| 합성 제출 | 72 | 72 | 일치 |
| accepted 이벤트 | 36 | 36 | 일치 |
| 스냅샷 SHA-256 | `93dfa4d1f38ecc2a868708409c4df323525cef971aa648644f37d0e7b4d5ced6` | 동일 | 일치 |
| 이관 재실행 증가 | - | 제출 0 / accepted 0 | 멱등 |

이관 후 실환경 검증용으로 합성 제출 5건을 추가했다.

- 정상 동일 seed 1차: 제출 2, 승격 2, 중복 0, 실패 0
- 정상 동일 seed 2차: 제출 2, 승격 2, 중복 0, 실패 0
- 잘못된 `C30~C39`: 제출 1, 승격 0, 검증거절 1, 실패 0
- 최종 누적: 제출 77, 승격 40, 미승격 37

## 테스트 결과

- 파일 모드·시뮬레이터·코호트 집중 회귀: 통과
- 실 PostgreSQL 통합: 통과
  - 자동 정합성 승격과 재시도 멱등성
  - 같은 키·다른 payload 충돌
  - 게이트 실패 기록 및 승격 차단
  - PostgreSQL 장애 시 파일 무폴백
  - 별도 합성 DB의 실제 스키마 부재
- 프로젝트 기본 CI 조합: 전체 통과, 조건부 1건 skip
- 재논의 후 v2 집중 회귀·실 PostgreSQL 테스트: 24건 통과
- 서버 8000·8080·8081 health: 모두 200
- 합성 PostgreSQL readiness: `ready=true`
- v2 실 API 거절 확인: `received=true`, `accepted_for_cohort=false`,
  `reason_codes=[kcd_code_in_simulator_catalog]` (확인용 레코드는 즉시 제거)

## Claude CLI 교차검토

1차 설계 리뷰에서 다음을 지적받아 반영했다.

- 검증 테이블의 PK를 submission_id로 두지 말고 append-only 이력 PK를 둘 것
- 사전 조회가 아니라 DB UNIQUE + ON CONFLICT로 멱등성을 보장할 것
- 제출과 자동 검증 기록을 단일 트랜잭션으로 처리할 것
- 상태·시각·run_id·evidence 크기를 DB 제약으로 제한할 것
- 실제 트랙과 합성 트랙을 별도 DB로 분리할 것

파일 전체를 읽는 2차 구현 리뷰는 Claude CLI가 제한 시간 내 결과를 내지 못해 종료됐다.
이후 범위를 좁힌 반박 리뷰는 완료됐다. Claude는 이미 구현된 409 충돌·검증 사유·무폴백
테스트 관련 초기 지적을 철회하고, PostgreSQL을 **보완 후 유지**하라고 권고했다. 남은
유효 지적으로 시뮬레이터 참조 카탈로그 존재 검사와 접수/승격 라벨 일관성을 반영했다.

## 남은 범위

이번 작업에서 의도적으로 하지 않은 것:

- 실제 청구 사례 저장소의 PostgreSQL 이관
- 보험사 발행처 API·원본 증빙에 의한 진위 자동확인
- LLM에게 보험금 지급 승인 권한 부여
- 합성/실제 통계 UNION

실제 사례 자동 검증은 발행처 확인 수단과 증빙 정책이 정해진 뒤 별도 단계로 설계해야 한다.
