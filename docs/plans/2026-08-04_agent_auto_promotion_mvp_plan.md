# S7 candidate fact 자동승격 중간계층 MVP 계획

작성일: 2026-08-04  
예상 기간: 2주  
목표: 낮은 위험의 candidate fact만 자동승격하고 나머지는 사람검수·격리로 명확히 분리

## 설계 원칙

- 에이전트는 승인 권한이 아니라 판정안 생성 권한만 갖는다.
- 자동승격은 버전 관리되는 PolicyGate만 수행한다.
- 라벨이 부족한 동안 통계적 보증을 주장하지 않는다.
- 실제 지급 승인과 약관 fact 승격을 분리한다.
- 모든 자동승격은 원문 근거와 재현 가능한 감사 이력을 가진다.

## Week 1 — 근거와 결정론적 게이트

### 1. 스키마

- [ ] `fact_candidate`에 `spans[]`, row/column header, evidence text 추가
- [ ] parser/extractor/document/policy 버전 필드 추가
- [ ] append-only `fact_decision_event` 추가
- [ ] `decision_proposal`과 `policy_evaluation` 분리

### 2. verifier

- [ ] evidence 정규화 substring grounding 구현
- [ ] KCD·금액·비율·단위 불변식 구현
- [ ] 판본·값 충돌 검사 구현
- [ ] cross-page·multi-axis·면책/예외 auto 차단 구현

### 3. PolicyGate v0

- [ ] 자동승격 fact type 1~2개 선정
- [ ] `auto_promoted / needs_review / quarantined` 라우팅 구현
- [ ] 에이전트가 상태를 직접 변경하지 못하는 권한 테스트
- [ ] 정책 버전·reason code·근거 감사 이벤트 기록

## Week 2 — 검수와 측정

### 4. 사람 검수

- [ ] 검수 큐에 원문 이미지·bbox·헤더·값·검사 사유 표시
- [ ] 승인·거절·수정 결정을 라벨로 저장
- [ ] parser 불일치·고영향 fact를 우선순위로 정렬
- [ ] auto-promoted 고정 비율 감사 표본 생성

### 5. 중복 전파

- [ ] 조항/표 content hash의 동일성 기준 확정
- [ ] 사람이 승인한 동일 hash fact 전파 구현
- [ ] 문서·판본 occurrence별 출처는 각각 유지
- [ ] 전파 원본·대상·정책 버전 감사 이벤트 기록

### 6. 지표와 회귀

- [ ] fact type별 precision/coverage/review/quarantine 집계
- [ ] 회사×세대×조판×OCR 여부별 층화 지표
- [ ] 자동승격 false positive 회귀 테스트
- [ ] 다축·cross-page auto 유입 금지 테스트
- [ ] revoke와 rollback 경로 검증

## 1차 자동승격 후보

- [ ] 단일 KCD + 정확 evidence span
- [ ] 조 번호·조항 제목 + 결정론적 패턴
- [ ] 승인된 동일 content hash 전파

## 1차 사람 검수 고정 대상

- [ ] 자기부담금·한도 다축 표
- [ ] cross-page 표
- [ ] 면책·예외 조항
- [ ] 판본 또는 parser 충돌
- [ ] OCR 값과 native text 불일치

## 2주 MVP 완료 기준

- [ ] 에이전트 단독으로 `auto_promoted`를 만들 수 없다.
- [ ] 자동승격 fact는 모두 문서 SHA·페이지·spans·header·evidence를 가진다.
- [ ] auto/review/quarantine의 분모와 사유가 대시보드에 표시된다.
- [ ] 감사 표본 없이는 자동승격 정밀도를 표시하지 않는다.
- [ ] 동일 hash 전파로 발생한 모든 승격을 원승인까지 역추적할 수 있다.
- [ ] 실패 시 PolicyGate 비활성화만으로 전부 사람 검수로 전환된다.

## 중단 기준

- [ ] 합의한 precision 하한 미달 시 auto gate 즉시 비활성화
- [ ] cross-page·다축·면책 fact가 자동승격되면 즉시 중단
- [ ] 출처·정책·모델 버전을 재현하지 못하면 배포 금지
- [ ] 회사·세대별 표본이 없는데 전역 신뢰도를 주장하지 않음

## 후속 단계

- [ ] 층별 라벨이 충분해지면 risk-coverage curve 생성
- [ ] selective prediction/conformal 후보를 shadow 평가
- [ ] LLM/VLM judge는 오프라인 약신호로만 비교
- [ ] 안전목표 충족 시에만 PolicyGate 입력으로 제한적 승격

