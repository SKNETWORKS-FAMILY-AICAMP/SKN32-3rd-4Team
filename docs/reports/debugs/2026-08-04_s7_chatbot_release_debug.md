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
