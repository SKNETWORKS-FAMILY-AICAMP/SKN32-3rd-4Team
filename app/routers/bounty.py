"""지식 바운티 라우터 — L1 기계 검증 노출 (운영 표면).

설계: `docs/plans/2026-07-22_2100_지식바운티_검증모델_재설계.md`

**응답 계약(중요)**: 이 엔드포인트는 제출물이 **사실인지 판정하지 않는다.**
`status: grounded`는 "근거가 있고, 그 근거가 주장을 지지하며, 기존 지식과 중복이 아니다"만
의미한다. 근거 자체가 거짓이면 통과한다 — 응답의 `disclaimer`로 이를 명시한다.

L2(escrow·이의제기·slash)와 L4(결과연동)는 **미구현**이다. 따라서 이 라우터는 정산을 하지
않으며, `settleable`은 "정산 단계로 넘길 수 있는 후보"라는 뜻일 뿐 지급이 아니다.

운영/통합 표면이라 고객 공개 포트에는 싣지 않는다(main.py의 운영 라우터 그룹).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.bounty import GRADES, Submission
from app.application.ports import Evidence
from app.auth.roles import require_admin
from app.composition import build_verify_bounty_submission
from app.db.database import get_db
from app.db.models import KnowledgeGap

# 운영 표면이라 **라우터 전역** fail-closed 의존성을 건다. 엔드포인트마다 붙이면
# 새 엔드포인트에서 누락되므로 전역으로 고정한다(관리자 라우터와 동일 패턴).
router = APIRouter(
    prefix="/api/bounty", tags=["bounty"], dependencies=[Depends(require_admin)]
)

_DISCLAIMER = (
    "이 결과는 사실성 판정이 아닙니다. 제시된 근거의 존재·지지·비중복만 기계적으로 "
    "확인했으며, 근거 자체가 거짓·조작·낡은 경우는 통과할 수 있습니다."
)


class EvidenceIn(BaseModel):
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    locator: str | None = None


class SubmitRequest(BaseModel):
    question: str = Field(min_length=1, description="바운티 질문")
    answer: str = Field(min_length=1, description="Provider 제출 답변")
    provider_id: str = Field(min_length=1)
    grade: str = Field(description=f"바운티 등급 {list(GRADES)}")
    evidence: list[EvidenceIn] = Field(default_factory=list)


@router.get("/grades")
def list_grades() -> dict:
    """바운티 등급과 각 등급의 정산 취급 방식(L0)."""
    return {
        "grades": [
            {"name": "verifiable", "설명": "명시된 출처로 재현 확인 가능", "정산": "L1 통과 시 정산 후보"},
            {"name": "outcome_linked", "설명": "사후 관측 결과 존재(반품률 등)", "정산": "결과 확인까지 대기(L4 미구현)"},
            {"name": "opinion", "설명": "객관 검증 불가(취향·전망)", "정산": "사실성 정산 대상 제외"},
        ],
        "disclaimer": _DISCLAIMER,
    }


@router.get("/open")
def open_bounties(db: Session = Depends(get_db)) -> dict:
    """바운티 후보 = 미해결 지식갭(RAG가 근거를 못 찾아 abstention한 질문).

    질문은 저장 시 PII가 마스킹돼 있다(KnowledgeGap 규약).
    """
    rows = (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.resolved.is_(False))
        .order_by(KnowledgeGap.id.desc())
        .limit(50)
        .all()
    )
    return {
        "count": len(rows),
        "items": [{"id": r.id, "question": r.question, "created_at": str(r.created_at)} for r in rows],
    }


@router.post("/submit")
def submit(
    body: SubmitRequest,
    db: Session = Depends(get_db),
) -> dict:
    """제출물에 L1 기계 검증을 적용한다. 미통과 사유는 고정 코드로 반환(자유 서술 아님).

    알 수 없는 등급·빈 입력은 폴백 없이 422로 실패한다.
    """
    verify = build_verify_bounty_submission()
    sub = Submission(
        bounty_question=body.question,
        answer=body.answer,
        evidence=[
            Evidence(content=e.content, source=e.source, locator=e.locator, score=0.0, backend="submitted")
            for e in body.evidence
        ],
        provider_id=body.provider_id,
    )
    result = verify(sub, body.grade)  # 알 수 없는 등급이면 ValidationErr(422)
    return {
        "status": result.status,
        "grade": result.grade,
        "reason": result.reason,
        "settleable": result.settleable,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
        "disclaimer": _DISCLAIMER,
        "note": "L2(escrow·이의제기·slash)와 L4(결과연동)는 미구현이며 정산은 수행되지 않았습니다.",
    }
