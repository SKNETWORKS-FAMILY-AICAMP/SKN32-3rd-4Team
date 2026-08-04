# S7 챗봇 연결 디버깅 노트

## 증상과 원인

배포 환경은 PG 인덱스를 사용하지만 `build_precheck()`가 저장소 종류를 확인하기 전에 로컬 `data/structured/*/s6_pymupdf-1.28.0/*.clauses.json`을 검사했다. 또한 챗봇은 기존 `data/glossary/passages.jsonl`만 읽어 S7.1 승인 OCR 사실이 실제 응답에 연결되지 않았다.

## 수정

- `CLAUSE_STORE=file`일 때만 로컬 문서별 JSON의 존재와 개수를 검사한다.
- `S7_FACT_ROOT`의 `approved_facts.jsonl`, `chunks.jsonl`, `occurrences.jsonl`을 챗봇 구절 소스로 연결한다.
- `serving_eligible=true`와 `citation_eligible=true`인 사실만 노출한다.
- 세 파일 중 일부만 배포되거나 승인 릴리스가 S7을 요구하는데 파일이 없으면 503으로 실패한다.
- `scripts/verify/verify_chatbot_s7.py`가 배포 묶음과 실제 챗봇 어댑터 연결을 독립적으로 검증한다.

## 검증

```text
python scripts/verify/verify_chatbot_s7.py
pytest -q tests/test_s7_chatbot_release.py tests/test_chat.py tests/test_terms_api.py
```

로컬 승인 묶음 기준 S7 사실 850건, occurrence 850건, 챗봇 S7 구절 850건이 연결됐으며 S7 전용 질의는 HTTP 200과 `kind=s7_approved_fact` 인용을 반환했다.

## 배포 계약

```text
CLAUSE_STORE=pg
S7_FACT_ROOT=/mounted/release/s7_1_approved_facts
```

`S7_FACT_ROOT` 아래에 위 세 JSONL 파일을 동일 릴리스 단위로 배치한 뒤 검증 스크립트가 성공해야 서비스를 시작한다.

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
