# agent façade의 FastAPI 계층 침범

- 발견 시각: 2026-08-04 23:15 KST
- 대상: `app/application/agent_facade.py`
- 상태: 전체 회귀시험에서 재현, 수정 전 기록

## 현상

외부 에이전트용 application façade가 기존 HTTP 래퍼의 예외를 변환하려고
`fastapi.HTTPException`을 직접 import한다. 이 프로젝트의 ARCH-001 계약은
`app/application/`이 FastAPI·LangChain·SQLAlchemy·OpenAI를 import하지 못하게 한다.

## 재현

```text
python -m pytest -q -m "not llm and not ml and not mcp and not pg and not legacy_data"

FAILED tests/test_arch.py::test_arch_001_application_has_no_framework_imports
Application 계층 금지 import 발견:
['agent_facade.py: from fastapi import HTTPException']
```

전체 실행은 이 1건을 제외하고 끝까지 진행됐으며, application 계층 경계 검사에서만
실패했다.

## 원인과 영향

- FastAPI의 전송 계층 예외를 application 계층이 알고 있다.
- 보호 API가 내부 HTTP 래퍼를 재사용하면서 예외 변환 위치까지 안쪽 계층으로 끌고 왔다.
- 프레임워크 교체 또는 비-HTTP 호출 시 application façade를 독립적으로 쓰기 어렵다.

## 수정 방향

application façade에서는 내부 호출 결과와 예외를 그대로 전달하고, `HTTPException`을
`AppError`로 바꾸는 책임은 FastAPI 라우터 경계로 옮긴다. ARCH-001과 외부 에이전트
오류 응답 계약을 함께 회귀시험한다.
