# S7 챗봇 연결 디버깅 노트

## 증상

배포 체크아웃에서 챗봇/판정 흐름이 승인 설정의 `s6_pymupdf-1.28.0` 문서별 파일을 찾다가 실패했다. 배포 산출물에는 로컬 `data/structured` 개별 JSON이 없고 PG 인덱스와 메타데이터만 존재했다.

## 원인

1. `app/composition.build_precheck()`가 저장소 종류를 확인하기 전에 `release.ensure_ready()`를 호출했다. `CLAUSE_STORE=pg`인 배포에서도 파일 저장소의 s6 디렉터리 검사를 수행했다.
2. 챗봇의 `build_glossary()`는 `data/glossary/passages.jsonl`만 읽었다. S7.1 승인 OCR 사실(`approved_facts.jsonl`, `chunks.jsonl`, `occurrences.jsonl`)은 검색 경로에 연결되지 않았다.
3. 배포 체크아웃은 `data/work`와 `data/glossary`를 포함하지 않으므로, 모델/사실 산출물 마운트 경로를 명시할 설정이 필요했다.

## 수정

- `CLAUSE_STORE=file`일 때만 `release.ensure_ready()`를 실행한다. `pg`는 승인 임베딩 프로필과 PG 인덱스 경로를 사용한다.
- 파일 용어 어댑터가 기존 glossary와 S7.1 승인 사실을 합쳐 읽는다.
- `serving_eligible=true` 및 `citation_eligible=true`인 사실만 챗봇 구절로 materialize한다. quarantine 후보는 제외한다.
- `S7_FACT_ROOT` 환경변수로 배포 시 S7 산출물 마운트 위치를 지정한다. 기본값은 `data/work/s7_1_approved_facts`다.
- `scripts/verify/verify_chatbot_s7.py`를 독립 검증 에이전트 역할의 검증기로 추가했다. API를 기동하거나 데이터를 변경하지 않고 릴리스·산출물·격리·챗봇 연결을 검사한다.

## 검증 명령

```text
python scripts/verify/verify_chatbot_s7.py
pytest -q tests/test_pg_clause_store.py tests/test_release_single_source.py -k "pg or store"
```

검증기는 S7 승인 사실 수, occurrence/chunk 연결 수, 실제 챗봇 어댑터가 읽은 `s7_approved_fact` 수, quarantine 미노출 여부를 출력한다.

## 배포 전제

디벨롭 브랜치 배포에는 다음 세 파일을 같은 릴리스로 마운트해야 한다.

```text
S7_FACT_ROOT/approved_facts.jsonl
S7_FACT_ROOT/chunks.jsonl
S7_FACT_ROOT/occurrences.jsonl
```

이 파일들이 없으면 챗봇은 근거 없는 폴백으로 답하지 않고 503으로 실패한다. 이는 S7이 연결되지 않은 상태를 정상 응답으로 오인하지 않게 하기 위한 fail-closed 동작이다.

## 2026-08-04 추가 점검 — 중복 표시와 상품명 폴백

### 재현

- DB손해보험 `통원` 조회에서 `02aaee47b190`, `045dd5140f47`, `08c8694914c9`가 연속 노출됐다.
- 삼성생명 `7f46168fa6c9`의 `별표2/제4조`가 p62–64와 p83–85에서 같은 제목으로 노출됐다.
- `insurer=삼성화재`, `product_name=삼성보험`처럼 존재하지 않는 상품명을 보내도 상품명 필터가 실패한 뒤 날짜 기준 후보가 선택됐다.

### 원인과 수정

- 용어 인용은 앞 120자 원문 일치만 보아 줄바꿈·페이지 장식 차이를 중복으로 인식하지 못했다. 같은 보험사 안에서 NFKC·공백·표 머리말만 제거한 문구가 정확히 같을 때만 대표 인용으로 묶는다. `병원`과 `의료기관`처럼 단어가 다르면 별도 정의로 유지한다.
- 두 삼성생명 조항은 중복이 아니라 각각 `상급병실료차액보험금`과 `요양병원 의료비` 담보다. 둘 다 유지하고 원문에서 담보 범위를 추출해 카드 제목에 표시한다.
- 한 조항의 `F04~F99` 면책과 `F30~F39` 예외가 모두 F32를 포함해 코드별 인용이 두 번 생기던 경로도 조항 단위로 중복 제거했다.
- 상품명을 입력했는데 일치 후보가 0건이면 `product_not_matched`로 기권한다. 날짜 후보로 폴백하지 않는다.
- API 인용에 `scope`와 `occurrence_id`를 전달해 화면 구분과 정확한 원문 추적을 유지한다.

### 실데이터 결과

```text
보고된 DB손해보험 3건: 2개 정의 그룹(02aa…/045d… 통합, 08c8… 유지)
DB손해보험 통원 전체: 160 passages → 동일 문구 154건 통합 → 서로 다른 6개 그룹 중 3개 표시
삼성생명 F32 p62–64: 2 mentions → 코드별 인용 1건, scope=상급병실료차액보험금
삼성생명 F32 p83–85: 2 mentions → 코드별 인용 1건, scope=요양병원 의료비
전체 근거: 서로 다른 특약 2건 유지
```

독립 검증 에이전트가 원본 PDF·S6/S7 구조화 파일을 별도로 대조했다. 퍼지 유사도 방식이 문언 차이를 숨길 위험과 코드별 인용 중복을 지적했고, 최종 구현은 그 지적에 따라 정확 일치 방식과 코드별 dedupe로 수정했다.
