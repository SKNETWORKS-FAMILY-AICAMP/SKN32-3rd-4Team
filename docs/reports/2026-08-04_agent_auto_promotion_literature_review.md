# S7 에이전트 자동승격 문헌조사와 권고안

작성일: 2026-08-04  
범위: 약관 candidate fact의 자동승격·사람검수 라우팅  
제외: 실제 보험금 지급 승인, 보험사 증빙 진위 확정

## 1. 결론

현재 가장 타당한 구조는 **LLM 심사위원의 직접 승인**이 아니다.

1. native PDF 우선 + 필요한 영역만 고해상도 재인식
2. 값과 원문 좌표·행/열 헤더를 묶은 atomic fact 생성
3. 결정론적 불변식과 원문 grounding 검사
4. 에이전트는 구조화된 `DecisionProposal`만 생성
5. 버전이 고정된 `PolicyGate`가 `auto_promoted / needs_review / quarantined`로 라우팅
6. 사람 결정과 자동승격 감사 표본을 라벨로 축적
7. 충분한 층별 라벨이 생긴 뒤에만 selective prediction/conformal risk control 적용

즉, 현재 단계의 자동승격은 **통계적 신뢰도 점수**보다 “안전하다고 정의한 단순 fact
유형 + 결정론적 검증 통과”를 기준으로 해야 한다.

## 2. 조사 방법과 인용수 해석

기술 주장은 arXiv 원문, ACL Anthology, OpenReview, PMLR, 학회·공식 저장소를 우선했다.
인용수는 검색 인덱스마다 달라 정확한 순위로 사용하지 않고, 성숙한 기반 연구를 고르는
보조 신호로만 사용했다. 2026-08-04 검색 인덱스에서는
[Donut 약 313회](https://www.scilynk.com/paper/W4312233877),
[SelectiveNet 약 300회 이상](https://liner.com/review/selectivenet-deep-neural-network-with-integrated-reject-option),
[FActScore 약 269회](https://arxiv.gg/abs/2305.14251), LayoutLMv3도 수백 회 규모로 나타났다.
이 수치는 변동 가능하며 방법의 보험 도메인 적합성을 보증하지 않는다.

## 3. 고인용 기반 연구

| 연구 | 핵심 | 채택할 것 | 그대로 쓰면 안 되는 이유 |
|---|---|---|---|
| [LayoutLMv3](https://arxiv.org/abs/2204.08387) | text·image·layout의 통합 사전학습 | 좌표와 시각 특징을 버리지 않는 설계 | 표 셀의 의미축·교차 페이지 결합을 직접 보증하지 않음 |
| [Donut](https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136880493.pdf) | OCR-free end-to-end 문서 이해 | OCR 기반 결과와 다른 실패모드의 shadow 후보 | OOD 한국 약관과 긴 다축 표에서 verifier로 사용 불가 |
| [PubTables-1M/Table Transformer](https://arxiv.org/abs/2110.00061) | row·column·cell·header bbox와 canonicalization | fact에 header·span을 저장하는 스키마, 구조 평가 | 과학 문서 중심이며 의미상 올바른 헤더 귀속을 보증하지 않음 |
| [SelectiveNet](https://proceedings.mlr.press/v97/geifman19a.html) | reject option과 risk-coverage | 확신 없는 사례를 검수로 보내는 제품 원칙 | 지금 라벨로 학습형 선택기를 바로 만들 근거는 부족 |
| [FActScore](https://aclanthology.org/2023.emnlp-main.741/) | 출력을 atomic fact로 분해해 소스별 검증 | 문서 전체가 아니라 fact별 evidence 판정 | 자유문장/위키 기반 점수 체계를 표 셀에 그대로 적용할 수 없음 |
| [Conformal Risk Control](https://research.google/pubs/conformal-risk-control/) | 단조 손실의 기대위험 제어 | 충분한 라벨 이후 층별 자동승격 위험 보정 | exchangeability와 calibration 표본이 부족하면 보증이 약하거나 coverage가 0에 가까워짐 |

## 4. 최근 주목할 연구

| 연구 | 최근 기여 | S7 적용 판단 |
|---|---|---|
| [OmniDocBench](https://arxiv.org/abs/2412.07626) | 문서 유형·layout·table·formula를 분해 평가 | 단일 전체 점수 대신 오류 유형별 평가 채택 |
| [MinerU2.5](https://arxiv.org/abs/2509.22186) | 저해상도 전역 layout 후 원해상도 crop 재인식 | OCR 필요 영역만 처리하는 S7 하이브리드와 잘 맞음 |
| [PaddleOCR-VL](https://arxiv.org/abs/2510.14528) | 0.9B 다국어 문서 파서의 저자 보고 SOTA | 한국어 shadow 후보로 평가하되 저자 보고만으로 승격 금지 |
| [MonkeyOCR v1.5](https://arxiv.org/abs/2511.10390) | 교차 페이지/열 표 병합, render-and-compare | cross-page 복원 후보와 약신호로 사용, 독립 verifier로 간주하지 않음 |
| [ParseBench](https://arxiv.org/abs/2604.08538) | 보험·금융·정부 문서에서 agent-critical semantic correctness 평가 | text similarity보다 표 의미·visual grounding을 DoD로 사용 |
| [Selective Generation](https://openreview.net/forum?id=glfYOAzh2f) | entailment 기반 선택적 생성과 FDR 제어 | 충분한 사람 라벨이 생긴 이후 fact-type별 abstention 보정 후보 |
| [Adaptive Conformal Risk Control](https://proceedings.mlr.press/v258/blot25a.html) | 입력 난이도에 적응한 조건부 위험 제어 | 회사·세대·조판 난이도별 라벨이 충분해진 장기 단계 후보 |
| [Judging the Judges](https://aclanthology.org/2025.ijcnlp-long.18/) | position bias와 judge별 변동성 실증 | LLM judge 단독 승인 금지, 순서 교란·반복 안정성 평가 |
| [MM-JudgeBias](https://aclanthology.org/2026.acl-long.1162/) | 시각·텍스트 단서 누락/불일치에서 multimodal judge 편향 | 표 이미지 judge도 독립 진실 판정기로 취급하지 않음 |

최신 parser들의 SOTA 주장은 대부분 저자 자체 벤치마크 또는 arXiv 단계다. 우리 보험약관
층화 표본에서 같은 경향이 재현되기 전에는 제품 승인 근거로 사용하지 않는다.

## 5. Claude 교차검토 결과

Claude와의 반박 리뷰에서 다음을 채택했다.

- 지금 라벨 수로 conformal 보증을 주장하지 않는다.
- 회사·세대·조판 분포가 다르므로 전역 confidence threshold 하나를 쓰지 않는다.
- render-and-compare와 LLM judge는 승인 게이트가 아니라 관측 신호로 강등한다.
- `bbox` 하나가 아니라 병합·교차 페이지를 표현하는 `spans[]`를 저장한다.
- 자동승격 정밀도를 주장하려면 auto-promoted 사례도 무작위 감사 표본으로 검수한다.
- S6 실측 중복을 이용한 동일 content hash 승인 전파를 우선한다.

S6 전량 실측은 조항 등장 204,098개 중 고유 내용 68,431개로 **66.5%가 중복**이며,
한 조항이 최대 170문서에 나타난다. 고유 해시의 37.7%가 2개 이상 문서에 걸쳐 있어,
동일 내용에 대한 사람 승인 전파는 라벨 하나의 효과를 크게 확대할 수 있다.

## 6. 권고 아키텍처

```text
page candidate
  → native text/layout extractor
  → OCR-needed detector
  → targeted parser A + shadow parser B
  → fact assembler(value + spans + headers + evidence)
  → deterministic verifier
  → grounding verifier
  → optional signals(parser agreement / visual render / LLM proposal)
  → versioned PolicyGate
       ├─ auto_promoted
       ├─ needs_review
       └─ quarantined
  → human decision / audit sample
  → confirmed fact
  → embedding·retrieval·precheck serving
```

분리 원칙:

- 에이전트는 `DecisionProposal`만 기록하고 `confirmed`를 직접 만들 수 없다.
- `PolicyGate`는 코드·정책 버전과 근거를 감사 이벤트에 남긴다.
- OCR/VLM 두 모델의 합의는 정확성의 증명이 아니라 불일치 검출 신호다.
- 실제 보험금 지급 승인과 candidate fact 승격은 서로 다른 상태기계다.

## 7. 자동승격 정책 v0

### 자동승격 허용

- 승인 판본의 명시적 보험사·상품·판매기간
- 정확한 원문 substring과 좌표가 있는 단일 KCD
- 단일 문장/셀의 명시적 금액·비율
- 조 번호·조항 제목처럼 결정론적 패턴이 있는 항목
- 동일 content hash에서 사람이 이미 승인한 fact의 전파

공통 조건:

- `doc_sha + page + spans[] + evidence_text` 존재
- 정규화된 값이 evidence에 직접 존재
- fact-type 불변식 통과
- 충돌 판본·값 없음
- cross-page, multi-axis, exclusion/exception 플래그가 모두 false

### 사람 검수

- 자기부담금·한도처럼 행/열/급여 여부가 결합된 다축 표
- 부록과 본문 또는 서로 다른 판본 간 충돌
- 면책과 예외가 동시에 관련된 경우
- parser 간 구조·값 불일치
- OCR이 필요하고 원문 문자열과 값이 직접 일치하지 않는 경우

### 격리

- 원문 근거·문서 SHA·좌표 없음
- 읽기 순서 또는 헤더 귀속 미복원
- 존재하지 않는 식별자
- payload/hash 충돌
- 문서 밖 지시문이나 prompt injection 의심

## 8. 최소 데이터 모델

- `fact_candidate`
  - `fact_id, doc_sha, page, spans_json, row_headers, column_headers`
  - `value_raw, value_norm, unit, fact_type, parser_version, cross_page`
- `fact_verification`
  - `fact_id, verifier, verdict, reason_codes, evidence_json, version`
- `decision_proposal`
  - `fact_id, model, prompt_hash, proposal, reasons, created_at`
- `policy_evaluation`
  - `fact_id, policy_version, route, matched_rules`
- `fact_decision_event`
  - append-only `from_state, to_state, actor, reason, timestamp`
- `human_review_task`
  - `fact_id, priority, reason, assignee, decision`
- `fact_hash_propagation`
  - `source_fact_id, target_fact_id, content_hash, policy_version`

상태:

```text
candidate
→ evidence_bound
→ auto_promoted | needs_review | quarantined
→ human_confirmed | human_rejected
→ published | revoked
```

## 9. 평가 방법

전역 accuracy 하나를 쓰지 않는다.

- fact type별 auto-promotion precision
- fact type별 coverage
- review rate / quarantine rate
- false promotion count와 Wilson 또는 exact lower confidence bound
- 회사×세대×조판×열 수×OCR 여부별 precision/coverage
- parser disagreement rate
- evidence/header/axis 오류율
- 승인 후 회귀에서 revoke된 비율
- 사람 검수 1건당 중복 전파된 fact 수

초기 안전목표 예시는 자동승격 화이트리스트에서 표본 precision 99% 이상이다. 이것은
현재 달성 사실이 아니라 팀이 정하고 감사 표본으로 검증해야 할 배포 기준이다.

## 10. 단계적 도입

### Phase 0 — 라벨 거의 없음

- 결정론적 verifier와 grounding만 사용
- auto-promote fact type을 1~2개로 제한
- 다축·교차 페이지는 구조적으로 auto 경로 진입 금지
- 모든 자동승격에서 고정 비율 audit sample 생성

### Phase 1 — 사람 라벨 축적

- review 결과를 층별 평가셋으로 고정
- parser disagreement와 경계 사례를 우선 라벨링
- 동일 content hash에 승인 전파
- confidence가 아닌 실측 risk-coverage 곡선 보고

### Phase 2 — 충분한 층별 라벨

- 회사·세대·fact type별 calibration
- selective prediction 또는 conformal risk control 실험
- shadow 결과가 안전목표를 만족할 때만 PolicyGate에 연결

## 11. 중단 기준

- audit 표본에서 합의한 precision 하한 미달
- 다축·cross-page·면책 fact가 auto 경로로 한 건이라도 유입
- evidence와 value가 직접 연결되지 않은 fact가 자동승격
- 어떤 policy/model/parser 버전이 승인했는지 재현 불가
- 회사·세대별 성능 편차를 측정할 라벨이 없는데 전역 보증을 주장

## 12. 최종 선택

1차 구현은 `conformal + LLM judge`가 아니라 다음 네 가지다.

1. full-provenance atomic fact
2. deterministic invariant + evidence grounding
3. fact-type whitelist PolicyGate
4. human audit + content-hash propagation

이 네 가지가 안정된 뒤에 parser ensemble과 통계적 abstention을 확장한다.
