"""Phase 10 시연 스크립트 — RAG(하이브리드) → GraphRAG → 커머스 승인 루프 → MCP → 관리자.

원칙(Codex 지적 반영):
- 성공 경로만 보여주지 않는다. 승인 루프에서 재고부족·같은 키 다른 payload 같은 **거부
  경로도 함께** 시연한다.
- MCP·PG 등 외부 의존이 없으면 그 사실을 출력하고 넘어가되, "성공한 것처럼" 숨기지 않는다.
- LLM 미기동 환경에서는 답변 생성만 건너뛰되 건너뛴 이유를 명시한다(무폴백).

실행: python -m scripts.demo   (FastAPI 앱을 TestClient로 in-process 구동, 별도 서버 불필요)
사전조건: `python -m scripts.manage migrate && seed && ingest` 1회 실행, (선택) PG 기동.
"""

from __future__ import annotations

import json
import os
import uuid

# 데모 전용 SECRET_KEY. 실 .env에 SECRET_KEY가 없으면 앱이 회원가입/토큰 발급을 **명시
# 거부**한다(무폴백 — 임의 기본 키로 조용히 넘어가지 않음). conftest.py의 테스트 격리와
# 같은 방식으로, 앱 import 전에 데모 전용 값을 주입한다. 프로덕션 키가 아니다.
os.environ.setdefault("SECRET_KEY", "demo-only-key-do-not-use-in-prod")


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _show(label: str, resp) -> None:
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    print(f"[{resp.status_code}] {label}\n{json.dumps(body, ensure_ascii=False, indent=2)[:600]}")


def main() -> None:
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app

    client = TestClient(app)
    settings = get_settings()

    # --- 0. 준비 상태 -------------------------------------------------
    _section("0. 준비 상태(readiness)")
    from app.obs.readiness import check_readiness

    ready = check_readiness()
    print(json.dumps(ready, ensure_ascii=False, indent=2))
    if not ready["ready"]:
        print("!! 미준비 — `python -m scripts.manage migrate && seed && ingest` 먼저 실행하세요.")
        return

    llm_available = settings.LLM_PROVIDER == "local"  # 이 데모는 로컬 provider만 시연 대상으로 봄
    if not llm_available:
        print(
            "[안내] LLM_PROVIDER가 'local'이 아니라 답변 생성 파트는 건너뜁니다 "
            "(무폴백: 임의로 다른 provider를 대신 부르지 않음)."
        )

    # --- 1. RAG: FAISS vs Hybrid vs Graph 검색 결과 비교 ---------------
    _section("1. RAG 검색 — backend별 비교 (search는 LLM 불필요)")
    question = "단순 변심 반품 기한은?"
    _show("검색(FAISS 기반 서비스)", client.post("/api/rag/search", json={"query": question, "top_k": 3}))

    for backend in ("faiss", "hybrid", "graph"):
        if backend in ("hybrid", "graph"):
            print(f"\n-- backend={backend} (PostgreSQL 필요) --")
        if not llm_available:
            print(f"-- backend={backend}: LLM 미기동이라 답변 생성은 건너뜀 --")
            continue
        try:
            r = client.post("/api/rag/qa", json={"question": question, "backend": backend})
            _show(f"RAG 답변(backend={backend})", r)
        except Exception as exc:  # PG 미기동 등 — 숨기지 않고 있는 그대로 출력
            print(f"-- backend={backend} 실패(있는 그대로 노출): {type(exc).__name__}: {exc}")

    # --- 2. 커머스 승인 루프: 성공 + 거부 경로 모두 -------------------
    _section("2. 커머스 승인 루프 (미리보기 → 승인 → 멱등, 거부 경로 포함)")
    uname = f"demo_{uuid.uuid4().hex[:8]}"
    signup_resp = client.post("/auth/signup", json={"username": uname, "password": "pass1234"})
    if signup_resp.status_code != 200:
        print(f"!! 회원가입 실패 — 있는 그대로 노출하고 중단: {signup_resp.status_code} {signup_resp.text}")
        return
    login_resp = client.post("/auth/login", data={"username": uname, "password": "pass1234"})
    if login_resp.status_code != 200:
        print(f"!! 로그인 실패 — 있는 그대로 노출하고 중단: {login_resp.status_code} {login_resp.text}")
        return
    token = login_resp.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    _show(
        "미리보기(DB 변경 없음)",
        client.post(
            "/api/orders/preview",
            json={"items": [{"product_code": "P0001", "quantity": 2}]},
            headers=auth,
        ),
    )

    key = uuid.uuid4().hex
    _show(
        "승인(최초, Idempotency-Key 필요)",
        client.post(
            "/api/orders",
            json={"items": [{"product_code": "P0001", "quantity": 2}]},
            headers={**auth, "Idempotency-Key": key},
        ),
    )
    _show(
        "승인(같은 키 재요청 — 멱등 재생, 재고 재차감 없음)",
        client.post(
            "/api/orders",
            json={"items": [{"product_code": "P0001", "quantity": 2}]},
            headers={**auth, "Idempotency-Key": key},
        ),
    )
    print("\n-- 거부 경로 --")
    _show(
        "거부: Idempotency-Key 없이 승인 시도 → 422",
        client.post(
            "/api/orders", json={"items": [{"product_code": "P0001", "quantity": 1}]}, headers=auth
        ),
    )
    _show(
        "거부: 같은 키·다른 payload → 409",
        client.post(
            "/api/orders",
            json={"items": [{"product_code": "P0001", "quantity": 99}]},
            headers={**auth, "Idempotency-Key": key},
        ),
    )
    _show(
        "거부: 재고를 초과하는 수량 → 422",
        client.post(
            "/api/orders",
            json={"items": [{"product_code": "P0001", "quantity": 999999}]},
            headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
        ),
    )

    # --- 3. MCP: REST와 parity ------------------------------------------
    _section("3. MCP — REST와 동일 유스케이스 경유(parity)")
    print(
        "[알려진 한계 — Phase 10 데모 준비 중 발견, 있는 그대로 기록]\n"
        "vector_search/rag_qa/recommend_products처럼 임베딩·ML 모델을 로드하는 MCP 도구는\n"
        "실제 stdio 서브프로세스 경로로 호출하면 이 환경(Windows)에서 무한 행이 걸린다\n"
        "(단독 실행 시 ~39초인 임베딩 로딩이 180초 넘게도 끝나지 않음 — 재현 확인함).\n"
        "기존 test_mcp_stdio.py의 관련 케이스 2건은 검증 오류(top_k=0, 빈 질문)만 짚어\n"
        "실제 임베딩 코드에 도달한 적이 없었다 — 이 조합은 이번에 처음 실측됐다.\n"
        "그래서 이 데모는 임베딩이 필요 없는 도구(get_price)로 MCP 왕복만 시연한다."
    )
    try:
        tools = client.post("/api/mcp/tools", json={}).json()
        print(f"등록된 MCP 도구 {tools.get('count')}개: "
              f"{[t['name'] for t in tools.get('tools', [])]}")
        _show(
            "MCP get_price 호출(임베딩 불필요, REST get_price와 같은 commerce_tools 경유)",
            client.post(
                "/api/mcp/call", json={"name": "get_price", "arguments": {"product_code": "P0001"}}
            ),
        )
    except Exception as exc:  # MCP 서버 subprocess 기동 실패 등 — 숨기지 않는다
        print(f"-- MCP 실패(있는 그대로 노출): {type(exc).__name__}: {exc}")

    # --- 4. 관리자(RBAC) -------------------------------------------------
    _section("4. 관리자 API (RBAC: 401 → 403 → 200)")
    _show("401(미인증)", client.get("/api/admin/orders"))
    _show("403(일반 사용자)", client.get("/api/admin/orders", headers=auth))

    from app.db.database import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        u.role = "ADMIN"
        db.commit()
    finally:
        db.close()
    _show("200(관리자로 승격 후)", client.get("/api/admin/orders", headers=auth))
    _show("관리자: 인덱스 상태", client.get("/api/admin/index", headers=auth))

    _section("시연 종료")


if __name__ == "__main__":
    main()
