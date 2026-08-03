# 올바른 보험 비서 — 서비스 설계 문서

![스토리보드](./storyboard.png)

## 1. 서비스 흐름 개요

```
[진입]
  channel 판별: web(직접 접속) | agent(외부 API 클라이언트 경유)
    ├─ web:   data_subject 식별 또는 신규 생성 (1회 익명이면 NULL 허용)
    └─ agent: agent_client 인증(api_key_hash) + data_subject 지정/신규 생성
  session_manager.session_id 생성 (created_at 기록, data_subject_id/agent_client_id 연결)
          │
          ▼
[화면 1] 보험정보 입력 (선택)
  상품명 / 보험사명 / 보험계약일시(가입일) / 사고일 입력
          │
     ┌────┴──────────────┐
    등록            다음에 할게요
     │                    │
     ▼                    │
  policy_holding 생성      │
  (data_subject_id,       │
   product_id,            │
   enrolled_on,           │
   generation_type)       │
     │                    │
     ▼                    │
  coverage_review 생성     │
  (data_subject_id,       │
   policy_holding_id,     │
   incident_on,           │
   channel,               │
   agent_client_id)       │
  session_manager         │
  .coverage_review_id 연결 │
     │                    │
     └─────────┬──────────┘
                ▼
[화면 2] 챗봇 서비스 화면
  (등록했다면 상단에 세션/상품 정보 요약 표시)
  증빙서류 제출 시 → event 생성 (coverage_review_id 연결)
                │
                ▼
[이탈] session_manager.expires_at 기록
```

---

## 2. 화면별 와이어프레임 설명

### 화면 1 · 보험정보 입력

| 요소 | 타입 | 설명 |
|---|---|---|
| 타이틀 | 텍스트 | "가지고 계신 보험 정보를 입력해주세요" |
| 상품명 | input | placeholder: `예) 다이렉트실손의료보험` |
| 보험사명 | select | placeholder: `보험사 선택` |
| 보험계약일시(가입일) | input | placeholder: `예) 20260801`. `policy_holding.enrolled_on`에 저장 |
| 사고일 *(신규)* | input | `coverage_review.incident_on`에 저장 — 아직 실제 화면 코드에는 반영되지 않음 (7절 참고) |
| 등록 버튼 | button | `insurance_product`(dedup) → `policy_holding` → `coverage_review` 순으로 생성, `session_manager.coverage_review_id` 연결 후 화면 2로 이동 |
| 다음에 할게요 버튼 | button | `policy_holding`/`coverage_review` 모두 미생성, `session_manager.coverage_review_id = NULL`인 채로 화면 2로 이동 |

### 화면 2 · 챗봇 서비스

| 요소 | 설명 |
|---|---|
| 상단 정보 바 | 보험정보를 입력한 경우에만 노출. `session_id`, 보험사명, 상품명, 세대 정보(`policy_holding.generation_type`) 표시 |
| 챗봇 인사말 | "질병코드로 보장여부를 확인할 수 있습니다. 질병코드를 모른다면 병명을 입력해보세요. 어려운 보험 용어를 쉽게 설명해드려요." |
| 채팅 입력창 + 보내기 버튼 | 입력한 질문에 대해 챗봇이 답변, `chatbot_count` 증가 |

---

## 3. 최종 DB 스키마
![ERD](./erd.png)
🔗링크: https://dbdiagram.io/d/6a6e1ac5067336e1de404869
> ⚠️ 아래 표의 변경사항은 아직 dbdiagram 링크에 반영되지 않았습니다.

### agent_client (외부 API 호출자 — 구 `agent` + `agent_credential` 통합, 명칭 통일)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `agent_client_id` | VARCHAR | PK, NOT NULL | 불변 식별자. 인증정보(`api_key_hash`)와 개념적으로 분리해서 생각한다 |
| `name` | VARCHAR | NOT NULL | 파트너/클라이언트 명 |
| `api_key_hash` | VARCHAR | NOT NULL | 인증키 해시값. **교체 가능** — 유출 시 이것만 갈아끼운다 (평문 저장 금지) |
| `rate_limit_rpm` | INTEGER | NOT NULL | 분당 호출 제한. API 클라이언트는 사람보다 수백 배 빠르게 호출할 수 있어 필요 |
| `status` | VARCHAR | NOT NULL | 계정 상태 (예: `active`, `disabled`) |
| `created_at` | TIMESTAMP | | 등록 시각 |
| `disabled_at` | TIMESTAMP | NULL 허용 | 비활성화 시각 |

> **범위가 명확해졌습니다: `agent_client`는 WEB 브라우저 세션을 포함하지 않습니다.** `coverage_review.channel`/`session_manager.channel`이 `'agent'`일 때만 `agent_client_id`가 채워지고, `'web'`이면 NULL입니다. WEB 접속자는 이 테이블에 행을 만들지 않고 `data_subject`로 곧장 식별됩니다.
> **고객(데이터 주체) 식별자로 쓰지 않습니다.** 인증 주체(누가 호출했나)와 데이터 주체(누구의 데이터인가)는 다릅니다 — `data_subject`와는 별개 테이블로 유지합니다.
> 이전 `agent_credential`(별도 테이블, 1:1)의 역할을 `api_key_hash` 컬럼 하나로 흡수해 테이블을 통합했습니다.

### agent_client_auth_log (인증 시도 로그)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `log_id` | VARCHAR | PK, NOT NULL | 로그 ID (UUID 등) |
| `agent_client_id` | VARCHAR | FK → agent_client, NULL 허용 | 인증을 시도한 클라이언트. 삭제 후에도 로그는 남아야 하므로 NULL 허용 |
| `attempted_at` | TIMESTAMP | NOT NULL | 인증 시도 시각 |
| `result` | VARCHAR | NOT NULL | `SUCCESS` \| `FAILURE` |
| `retention_until` | TIMESTAMP | NULL 허용 | 로그 보존기한 |

### data_subject (데이터 주체 — 실제 개인)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `data_subject_id` | VARCHAR | PK, NOT NULL | 실제 개인 식별자 (계약/의료 정보의 진짜 주인) |
| `age_band` | VARCHAR | NULL 허용 | 연령대 구간. **생년월일·출생연도는 저장하지 않음** |
| `created_at` | TIMESTAMP | | 최초 생성 시각 |
| `consent_at` | TIMESTAMP | NULL 허용 | 개인정보 수집·이용 동의 시각 |
| `retention_until` | TIMESTAMP | NULL 허용 | 보존기한 |
| `deleted_at` | TIMESTAMP | NULL 허용 | 삭제권 행사 처리 시각(소프트 삭제) |

> `agent_client`(인증 주체)와 `data_subject`(데이터 주체)는 서로 다른 테이블로 유지합니다 — 삭제권·동의는 항상 `data_subject` 기준으로 처리해야 하기 때문입니다.

### insurance_product (보험상품 마스터 — 카탈로그, 중복 저장 안 함)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `product_id` | VARCHAR | PK, NOT NULL | 상품 코드 (자동 생성, 아래 4.3 참고) |
| `product_name` | VARCHAR | NULL 허용 | 상품명 |
| `insurance_company` | VARCHAR | NULL 허용 | 보험사명 |

### policy_holding (가입 계약)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `policy_holding_id` | VARCHAR | PK, NOT NULL | 가입 계약 ID |
| `data_subject_id` | VARCHAR | FK → data_subject, NOT NULL | 계약의 실제 소유자. 계약은 항상 특정 개인에게 귀속(익명 불가) |
| `product_id` | VARCHAR | FK → insurance_product, NOT NULL | 연결된 보험 상품 |
| `enrolled_on` | DATE | NOT NULL | **가입일** |
| `generation_type` | SMALLINT | NULL 허용 | 세대 정보. `enrolled_on` 기준 1회 계산 (4.2절). `NULL`=계산 전, `0`=판정 불가(미상), `1`~`5`=정상 판정. 같은 계약을 참조하는 모든 `coverage_review`가 이 값을 공유해 재사용 |
| `consent` | TIMESTAMP | NULL 허용 | 이 계약 정보를 분석에 이용하는 것에 대한 동의 시각 |
| `retention_until` | TIMESTAMP | NULL 허용 | 보존기한 |
| `deleted_at` | TIMESTAMP | NULL 허용 | 삭제권 행사 처리 시각(소프트 삭제) |

### coverage_review (사전검토 요청)

> **명명 근거**: 원래 이름은 `case`였으나 PostgreSQL 예약어(`CASE WHEN...END`)와 충돌해 `coverage_review`로 변경했다.   

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `coverage_review_id` | VARCHAR | PK, NOT NULL | 보험 분석 건 ID |
| `data_subject_id` | VARCHAR | FK → data_subject, NULL 허용 | **1회 익명 분석은 NULL** |
| `policy_holding_id` | VARCHAR | FK → policy_holding, NOT NULL | **직접 연결.** `data_subject` 경유로 조인하면 계약이 여럿일 때 결과가 잘못 배분됨 |
| `incident_on` | DATE | NOT NULL | **사고일** — 약관 버전 매칭의 기준 |
| `channel` | VARCHAR | NOT NULL | `web`(직접 접속) \| `agent`(외부 API 클라이언트 경유) |
| `agent_client_id` | VARCHAR | FK → agent_client, NULL 허용 | `channel = 'agent'`일 때만 사용 |
| `created_at` | TIMESTAMPTZ | NOT NULL | 케이스 생성 시각 |
| `consent` | TIMESTAMP | NULL 허용 | 이 케이스를 분석 목적으로 이용하는 것에 대한 동의 시각 |
| `retention_until` | TIMESTAMP | NULL 허용 | 보존기한 |
| `deleted_at` | TIMESTAMP | NULL 허용 | 삭제권 행사로 파기 처리된 시각(소프트 삭제) |

> 이전에 있던 `created_by_agent_id`(시스템 호출 주체 감사용 컬럼)는 **제거**했습니다. `channel` + `agent_client_id` 조합만으로 "누구를 통해 들어온 요청인지"를 충분히 표현할 수 있어 중복이었습니다.

### event (증빙서류 제출 기록)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `event_id` | VARCHAR | PK, NOT NULL | `{날짜}_{파일명}_{division}_{sha256 전체 64자}` 형식 |
| `coverage_review_id` | VARCHAR | FK → coverage_review, NOT NULL | 연결된 분석 건 |
| `sha256_hash` | VARCHAR(64) | NOT NULL | 증빙서류 원본 SHA-256 해시 (전체 64자) |
| `division` | VARCHAR | | `진단서` \| `소견서` \| `처방전` \| `입퇴원확인서` \| `진료비세부내역서` \| `의무기록 사본` |
| `submitted_at` | TIMESTAMP | | 제출 시각 |
| `consent` | TIMESTAMP | NULL 허용 | 이 건(서류 제출)에 대한 개별 동의 시각 |
| `retention_until` | TIMESTAMP | NULL 허용 | 이 증빙서류의 보존기한 |
| `deleted_at` | TIMESTAMP | NULL 허용 | 삭제권 행사로 파기 처리된 시각(소프트 삭제) |

### session_manager (대화창 세션 관리)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `session_id` | VARCHAR | PK, NOT NULL | 대화창(챗봇) 세션 ID |
| `data_subject_id` | VARCHAR | FK → data_subject, NULL 허용 | 세션 보유자. 익명 채팅은 NULL |
| `channel` | VARCHAR | NOT NULL | `web` \| `agent` — `coverage_review`와 동일한 패턴 |
| `agent_client_id` | VARCHAR | FK → agent_client, NULL 허용 | `channel = 'agent'`일 때만 사용 |
| `coverage_review_id` | VARCHAR | FK → coverage_review, NULL 허용 | 특정 분석 건에 대한 대화면 연결; 스킵 시 NULL |
| `created_at` | TIMESTAMP | | 세션 생성 시각 |
| `expires_at` | TIMESTAMP | | 세션 만료 시각 |
| `action_type` | VARCHAR | | `VISIT` \| `INPUT_INFO` \| `CHATBOT_USE` |
| `chatbot_count` | SMALLINT | DEFAULT 0 | 챗봇 이용 횟수 |
| `retention_until` | TIMESTAMP | NULL 허용 | 세션 로그 보존기한 |
| `deleted_at` | TIMESTAMP | NULL 허용 | 파기 처리 시각(소프트 삭제) |

> 예전엔 `session_manager.agent_id`(WEB\|API 통합 개념)로 세션 보유자를 표현했지만, `agent_client`가 API 전용으로 범위가 좁아지면서 **`coverage_review`와 동일한 `data_subject_id` + `channel` + `agent_client_id` 패턴으로 통일**했습니다.

**참조 관계 요약**

| 참조 | 삭제 정책 | 수정 정책 |
|---|---|---|
| `agent_client_auth_log.agent_client_id` → `agent_client.agent_client_id` | SET NULL | CASCADE |
| `policy_holding.data_subject_id` → `data_subject.data_subject_id` | **RESTRICT** | CASCADE |
| `policy_holding.product_id` → `insurance_product.product_id` | RESTRICT | CASCADE |
| `coverage_review.data_subject_id` → `data_subject.data_subject_id` | SET NULL | CASCADE |
| `coverage_review.policy_holding_id` → `policy_holding.policy_holding_id` | **RESTRICT** | CASCADE |
| `coverage_review.agent_client_id` → `agent_client.agent_client_id` | SET NULL | CASCADE |
| `event.coverage_review_id` → `coverage_review.coverage_review_id` | RESTRICT | CASCADE |
| `session_manager.data_subject_id` → `data_subject.data_subject_id` | SET NULL | CASCADE |
| `session_manager.agent_client_id` → `agent_client.agent_client_id` | SET NULL | CASCADE |
| `session_manager.coverage_review_id` → `coverage_review.coverage_review_id` | SET NULL | CASCADE |

> 삭제 보호 체인은 `event → coverage_review → policy_holding → data_subject`(모두 RESTRICT)로 유지됩니다. `agent_client`는 삭제돼도(API 파트너 계약 종료 등) 이 체인에 영향을 주지 않습니다(SET NULL).

---

## 4. 핵심 로직 설명

### 4.1 식별 및 세션 생명주기
1. **channel 판별**: 요청이 브라우저 직접 접속(`web`)인지 외부 API 클라이언트 경유(`agent`)인지 구분한다.
2. **`web`**: `data_subject`를 식별하거나(반복 방문) 신규 생성한다. 정보 입력 전까지는 익명(`session_manager.data_subject_id = NULL`)일 수 있다.
3. **`agent`**: `agent_client.api_key_hash`로 호출자를 인증하고, 요청에 포함된 `data_subject_id`를 사용하거나 없으면 신규 생성한다. **`data_subject_id` 없이는 `policy_holding`을 생성할 수 없다.**
4. 고유한 `session_id`를 발급해 `session_manager`에 저장한다.
5. 화면을 벗어나면 `expires_at`을 기록해 세션을 종료 처리한다.

### 4.2 세대(generation_type) 계산 규칙 — 계약(policy_holding) 단위로 1회만 계산
`policy_holding.enrolled_on`(가입일)을 기준으로 실손의료보험 표준 세대 구분을 적용하고, **`policy_holding.generation_type`에 계약 단위로 저장**합니다.

| 가입일 | 세대 |
|---|---|
| ~ 2009.09.30 | 1세대 |
| 2009.10.01 ~ 2017.03.31 | 2세대 |
| 2017.04.01 ~ 2021.06.30 | 3세대 |
| 2021.07.01 ~ 2026.05.05 | 4세대 |
| 2026.05.06 ~ | 5세대 |

> 2026.05.06 5세대 출시일은 금융위원회 보도자료 기준으로 확인된 값입니다.

> `enrolled_on`이 위 표의 어느 구간에도 매핑되지 않으면 `generation_type = 0`(미상/UNKNOWN)으로 저장한다.

> **왜 `coverage_review`가 아니라 `policy_holding`에서 계산하는가**: 같은 계약에 여러 건의 사전검토(`coverage_review`)가 있을 수 있는데, 세대는 가입 시점에 고정되는 값이라 케이스마다 달라지지 않는다. 계약 생성 시 1회만 계산해두면 이후 그 계약을 참조하는 모든 `coverage_review`가 재계산 없이 재사용한다.

> `coverage_review.incident_on`(사고일)은 세대 계산에는 쓰이지 않고, "사고 시점 기준으로 적용 약관을 재확인"하는 별도 매칭에 쓰인다 — 이 매칭 로직은 아직 상세 설계가 없다(7절 참고).

### 4.3 product_id 생성 규칙
형식: `{보험사코드}-{일련번호 4자리}` (예: 삼성화재·1번째 상품 → `SS-0001`)
- 자주 쓰는 보험사는 코드 매핑 테이블(`COMPANY_CODE_MAP`)을 사용
- 매핑에 없는 보험사는 이름을 해시하여 4자리 코드로 자동 생성

### 4.4 상품 중복 방지 로직
`product_name` + `insurance_company` 조합이 `insurance_product`에 이미 존재하면 카탈로그에는 새로 삽입하지 않고, 기존 `product_id`를 조회해 `policy_holding.product_id`에 연결한다.

### 4.5 보험정보 입력은 선택사항
화면 1에서 "다음에 할게요"를 선택하면 `policy_holding`, `coverage_review` 모두 생성하지 않고 화면 2로 이동한다. `session_manager.coverage_review_id`는 `NULL`로 유지, `action_type = VISIT`으로 기록한다.

### 4.6 챗봇 이용 기록
채팅 입력 시마다 `session_manager.action_type`을 `CHATBOT_USE`로 갱신하고 `chatbot_count`를 1씩 증가시킨다.

### 4.7 증빙서류 제출 (event)
- `event_id`: `{날짜}_{증빙서류 파일명}_{division}_{sha256 전체 64자}` 형식으로 자동 생성
- `sha256_hash`: 원본 파일의 SHA-256 전체(64자)를 저장해 중복·위변조를 감지
- `coverage_review`가 없는 세션(보험정보 스킵)에서는 서류 제출 불가

### 4.8 coverage_review 테이블 병합 검토 결과 — 병합하지 않음
`policy_holding`과 `coverage_review`를 하나로 합칠 수 있는지 검토했으나, **분리 유지로 결론**냈다.
1. **1:N 관계**: 계약 하나에 사전검토가 여러 건 붙을 수 있다. 합치면 계약 정보(상품·가입일·세대)가 케이스마다 중복 저장된다.
2. **재추론 방지 원칙 위반**: `generation_type`을 계약 단위로 1회만 계산해 재사용하는 게 핵심 설계인데, 합치면 케이스마다 다시 계산해야 하거나 값이 어긋날 위험이 생긴다.
3. **소유자 필수 여부 비대칭**: `coverage_review.data_subject_id`는 NULL 허용(익명 분석), `policy_holding.data_subject_id`는 필수. 합치면 이 비대칭을 표현하기 어렵다.
4. **가입일·사고일 분리 문제 재발**: 애초에 두 테이블을 나눈 이유 자체가 다시 발생한다.

---

## 5. 관련 산출물(임시 작성)
| 파일 | 설명 |
|---|---|
| `app/db/models.py` | SQLAlchemy ORM 모델 (보험 도메인 + 레거시) |
| `app/db/database.py` | DB 엔진·세션·Base 정의 |
| `config/generation_profiles.json` | 세대 판정 기준 컷오프 설정 |
| `app/adapters/pg_graph.py` | PostgreSQL 그래프 적재 어댑터 토대 |
| `docs/reports/` | 수집·전처리 결정 기록 리포트 |

---

## 6. 보관 기간(retention) 반영 현황

| 데이터 | 상태 |
|---|---|
| `event` (증빙서류) | ✅ `consent`, `retention_until`, `deleted_at` |
| `policy_holding` | ✅ `consent`, `retention_until`, `deleted_at` |
| `coverage_review` | ✅ `consent`, `retention_until`, `deleted_at` |
| `session_manager` | ✅ `retention_until`, `deleted_at` |
| `data_subject` | ✅ `retention_until`, `deleted_at` (`consent_at` 별도 유지) |
| `agent_client_auth_log` | ✅ `retention_until` |

### 남은 과제
1. **보존기간 값 확정** — 법무 검토 필요
2. **파기 배치 작업 구현** — 아직 없음
3. **삭제 실행 순서 자동화** — `event → coverage_review → policy_holding → data_subject`
4. **`consent` 컬럼 구조 재검토** — 지금은 `data_subject`/`policy_holding`/`coverage_review`/`event` 네 곳에 각각 타임스탬프로 흩어져 있다. 목적별로 여러 건을 남기거나(같은 데이터 주체가 여러 목적에 각각 동의) 철회 이력을 관리해야 한다면, 흩어진 컬럼 대신 **별도 동의 테이블(주체 기준 1개, 목적별로 행이 늘어나는 구조)**로 정규화하는 걸 고려할 필요가 있다 — 아직 구현하지 않음, 별도 논의 필요.

---

## 7. 남은 미해결 이슈

1. **화면 1에 "사고일" 입력 UI 추가 필요** — `coverage_review.incident_on`이 `NOT NULL`인데 기존 스토리보드/화면 코드엔 입력란이 없음
2. **보장기간 상한선(`terminated_on`) 필요 여부** — `policy_holding.enrolled_on`(하한)만으로는 "보장기간 안"을 판단할 수 없음. 갱신형 상품이라 만료가 사실상 없다면 문제 없지만, 중도 해지·기간 한정 상품이 있다면 해지일 컬럼이 필요
3. **`incident_on` 기준 약관 매칭 로직 미설계** — "사고 시점 기준으로 적용 약관 재확인"이 구체화되지 않음
4. **`consent` 구조 정규화 여부** — 6절 남은 과제 4 참고
