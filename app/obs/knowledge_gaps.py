"""지식보강 큐 적재 (Phase 9).

RAG가 근거를 못 찾아 abstention한 질문을 모아 "문서 보강 대상"으로 삼는다.
**저장 전에 PII를 마스킹**한다 — 큐의 목적은 질문의 주제이지 개인정보가 아니다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import KnowledgeGap
from app.obs.pii import mask_pii
from app.obs.trace import get_trace_id


def record_knowledge_gap(db: Session, question: str) -> KnowledgeGap:
    """abstention 질문을 마스킹해 큐에 적재한다."""
    gap = KnowledgeGap(
        question=mask_pii(question),  # 원문 그대로 저장하지 않는다
        trace_id=get_trace_id() or "no-trace",
    )
    db.add(gap)
    db.commit()
    db.refresh(gap)
    return gap
