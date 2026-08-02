# 올바른 보험 비서 — 서비스 설계 문서

![스토리보드](./storyboard.png)

## 1. 서비스 흐름 개요

```
[진입]
  agent 식별 또는 신규 생성 (agent_type = WEB | API)
  session_manager.session_id 생성 (create_at 기록, agent_id 연결)
          │
          ▼
[화면 1] 보험정보 입력 (선택)
  상품명 / 보험사명 / 보험계약일시 입력
          │
     ┌────┴─────────┐
    등록      다음에 할게요
     │              │
     ▼              │
  case 생성          │
  (product_id,      │
   contracted_at)   │
  session_manager   │
  .case_id 연결      │
     │              │
     └─────┬────────┘
           ▼
[화면 2] 챗봇 서비스 화면
  (등록했다면 상단에 세션/상품 정보 요약 표시)
  증빙서류 제출 시 → event 생성 (case_id 연결)
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
| 보험계약일시 | input | placeholder: `예) 20260801` |
| 등록 버튼 | button | 입력값을 `insurance_product` / `case`에 저장하고 `session_manager.case_id` 연결 후 화면 2로 이동 |
| 다음에 할게요 버튼 | button | `case` 미생성, `session_manager.case_id = NULL`인 채로 화면 2로 이동 |

### 화면 2 · 챗봇 서비스

| 요소 | 설명 |
|---|---|
| 상단 정보 바 | 보험정보를 입력한 경우에만 노출. `session_id`, 보험사명, 상품명, 세대 정보 표시 |
| 챗봇 인사말 | "질병코드로 보장여부를 확인할 수 있습니다. 질병코드를 모른다면 병명을 입력해보세요. 어려운 보험 용어를 쉽게 설명해드려요." |
| 채팅 입력창 + 보내기 버튼 | 입력한 질문에 대해 챗봇이 답변, `chatbot_count` 증가 |

---

## 3. 최종 DB 스키마
![ERD](./erd.png)   
🔗링크: https://dbdiagram.io/d/6a6e1ac5067336e1de404869

### agent (에이전트 — 웹·API 공통 식별자)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `agent_id` | VARCHAR | PK, NOT NULL | 내부 처리용 에이전트 ID |
| `agent_type` | VARCHAR | | `WEB` \| `API` |
| `created_at` | TIMESTAMP | | 최초 접속(등록) 시각 |
| `last_active_at` | TIMESTAMP | | 가장 최근 활동 시각 |

### agent_credential (에이전트 인증 자격증명 — 1 agent : 1 credential)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `agent_id` | VARCHAR | PK, FK → agent, NOT NULL | 에이전트 식별자 |
| `auth_key` | VARCHAR | NOT NULL | 인증키 해시값 (평문 저장 금지) |
| `issued_at` | TIMESTAMP | | 최초 발급 시각 (교체해도 불변) |
| `rotated_at` | TIMESTAMP | NULL 허용 | 가장 최근 교체 시각; 교체 이력 없으면 NULL |

### insurance_product (보험상품 마스터 — 카탈로그, 중복 저장 안 함)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `product_id` | VARCHAR | PK, NOT NULL | 상품 코드 (자동 생성, 아래 4.3 참고) |
| `product_name` | VARCHAR | | 상품명 |
| `insurance_company` | VARCHAR | | 보험사명 |
| `generation_type` | TINYINT | | 세대 정보 (1~5, 아래 4.2 참고) |

### case (보험 분석 건)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `case_id` | VARCHAR | PK, NOT NULL | 보험 분석 건 ID |
| `agent_id` | VARCHAR | FK → agent, NOT NULL | 분석 건을 생성한 에이전트 |
| `product_id` | VARCHAR | FK → insurance_product, NULL 허용 | 연결된 보험 상품; 입력 안 하면 NULL |
| `contracted_at` | TIMESTAMP | NULL 허용 | 보험 계약일시 |
| `created_at` | TIMESTAMP | | 케이스 생성 시각 |

### event (증빙서류 제출 기록)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `event_id` | VARCHAR | PK, NOT NULL | `{날짜}_{파일명}_{구분}_{sha256}` 형식 |
| `case_id` | VARCHAR | FK → case, NOT NULL | 연결된 분석 건 |
| `sha256_hash` | VARCHAR(64) | NOT NULL | 증빙서류 원본 SHA-256 해시 |
| `division` | VARCHAR | | `진단서` \| `소견서` \| `처방전` \| `입퇴원확인서` \| `진료비세부내역서` \| `의무기록 사본` |
| `submitted_at` | TIMESTAMP | | 제출 시각 |

### session_manager (대화창 세션 관리)
| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `session_id` | VARCHAR | PK, NOT NULL | 대화창(챗봇) 세션 ID |
| `agent_id` | VARCHAR | FK → agent, NOT NULL | 세션을 보유한 에이전트 |
| `case_id` | VARCHAR | FK → case, NULL 허용 | 특정 분석 건에 대한 대화면 연결; 스킵 시 NULL |
| `create_at` | TIMESTAMP | | 세션 생성 시각 |
| `expires_at` | TIMESTAMP | | 세션 만료 시각 |
| `action_type` | VARCHAR | | `VISIT` \| `INPUT_INFO` \| `CHATBOT_USE` |
| `chatbot_count` | TINYINT | DEFAULT 0 | 챗봇 이용 횟수 |

**참조 관계 요약**

| 참조 | 삭제 정책 | 수정 정책 |
|---|---|---|
| `agent_credential.agent_id` → `agent.agent_id` | CASCADE | CASCADE |
| `case.agent_id` → `agent.agent_id` | CASCADE | CASCADE |
| `case.product_id` → `insurance_product.product_id` | RESTRICT | CASCADE |
| `event.case_id` → `case.case_id` | CASCADE | CASCADE |
| `session_manager.agent_id` → `agent.agent_id` | CASCADE | CASCADE |
| `session_manager.case_id` → `case.case_id` | SET NULL | CASCADE |

---

## 4. 핵심 로직 설명

### 4.1 에이전트 식별 및 세션 생명주기
1. 웹·API 진입 시 `agent`를 식별하거나 신규 생성하고 `agent_type`(`WEB`|`API`)을 기록한다.
2. 고유한 `session_id`를 발급해 `session_manager`에 `create_at`·`agent_id`와 함께 저장한다.
3. 화면을 벗어나면 `expires_at`을 기록해 세션을 종료 처리한다.
4. `agent.last_active_at`은 활동이 일어날 때마다 갱신한다.

### 4.2 세대(generation_type) 계산 규칙
`case.contracted_at`(보험 계약일시)을 기준으로 실손의료보험 표준 세대 구분을 적용합니다.

| 계약일시 | 세대 |
|---|---|
| ~ 2009.09.30 | 1세대 |
| 2009.10.01 ~ 2017.03.31 | 2세대 |
| 2017.04.01 ~ 2021.06.30 | 3세대 |
| 2021.07.01 ~ 2024.12.31 | 4세대 |
| 2025.01.01 ~ | 5세대 |

> 회사 내부 기준이 다르면 `config/generation_profiles.json`의 `GENERATION_CUTOFFS` 값만 조정하면 됩니다.

### 4.3 product_id 생성 규칙
형식: `{보험사코드}{세대}G-{일련번호 4자리}` (예: 삼성화재·4세대·1번째 상품 → `SS4G-0001`)
- 자주 쓰는 보험사는 코드 매핑 테이블(`COMPANY_CODE_MAP`)을 사용
- 매핑에 없는 보험사는 이름을 해시하여 4자리 코드로 자동 생성
- 같은 보험사·세대 조합 내에서 기존 상품 개수를 세어 일련번호 부여

### 4.4 상품 중복 방지 로직
`product_name` + `insurance_company` 조합이 `insurance_product`에 이미 존재하면:
- 카탈로그에는 **새로 삽입하지 않음**
- 대신 기존 `product_id`를 조회해 `case.product_id`에 연결
→ 여러 에이전트·케이스가 같은 상품을 입력해도 `insurance_product`에는 한 줄만 유지됨

### 4.5 보험정보 입력은 선택사항
화면 1에서 "다음에 할게요"를 선택하면:
- `case` 행을 생성하지 않고 화면 2로 이동
- `session_manager.case_id`는 `NULL`로 유지, `action_type = VISIT`으로 기록
- 화면 2 상단 정보 요약 바는 노출되지 않음

### 4.6 챗봇 이용 기록
채팅 입력 시마다 `session_manager.action_type`을 `CHATBOT_USE`로 갱신하고 `chatbot_count`를 1씩 증가시켜 세션당 챗봇 이용 빈도를 추적합니다.

### 4.7 증빙서류 제출 (event)
서류를 제출하면 `case_id`에 연결된 `event` 행을 생성합니다.
- `event_id`: `{날짜}_{파일명}_{division}_{sha256 앞 8자리}` 형식으로 자동 생성
- `sha256_hash`: 원본 파일의 SHA-256 전체(64자)를 저장해 중복·위변조를 감지
- `division`: 문서 종류(`진단서` | `소견서` | `처방전` | `입퇴원확인서` | `진료비세부내역서` | `의무기록 사본`)
- `case`가 없는 세션(보험정보 스킵)에서는 서류 제출 불가 — 먼저 케이스를 생성해야 함

---

## 5. 관련 산출물(임시 작성)
| 파일 | 설명 |
|---|---|
| `app/db/models.py` | SQLAlchemy ORM 모델 (보험 도메인 + 레거시) |
| `app/db/database.py` | DB 엔진·세션·Base 정의 |
| `config/generation_profiles.json` | 세대 판정 기준 컷오프 설정 |
| `app/adapters/pg_graph.py` | PostgreSQL 그래프 적재 어댑터 토대 |
| `docs/reports/` | 수집·전처리 결정 기록 리포트 |
