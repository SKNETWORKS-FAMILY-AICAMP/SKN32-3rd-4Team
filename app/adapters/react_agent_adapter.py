"""ReactAgentAdapter — 기존 ReAct 루프를 AgentPort로 감싼다(Phase 7).

도구 관찰(observation)을 근거 문장으로 언어화해 자기검증에 넘긴다. RAG 관찰은 검색된
문서 조각을, 나머지 도구는 구조화 사실을 근거로 만든다. 실패 관찰(ok=false)은 근거가 아니다.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.application.chat_commerce import AgentTurn


def _rag_evidence(obs: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for r in obs.get("results", []) or []:
        text = r.get("text") or r.get("content") or ""
        source = r.get("source") or ""
        if text:
            out.append(f"[{source}] {text}" if source else text)
    return out


def observation_to_evidence(action: str, obs: dict[str, Any]) -> list[str]:
    """도구 관찰 → 근거 문장들. 실패 관찰은 근거로 쓰지 않는다."""
    if not isinstance(obs, dict) or not obs.get("ok", False):
        return []
    if action == "search_knowledge_base":
        return _rag_evidence(obs)
    if action == "preview_order":
        lines = ", ".join(
            f"{ln.get('name') or ln.get('product_code')} {ln.get('quantity')}개"
            f"×{ln.get('unit_price')}원" for ln in obs.get("lines", []) or []
        )
        return [
            f"주문 미리보기: {lines} / 총액 {obs.get('total')}원 / "
            f"재고충족={obs.get('feasible')} (주문 생성되지 않음)"
        ]
    # 그 외 도구는 관찰 dict를 그대로 사실 문장화(키-값 요약)
    facts = {k: v for k, v in obs.items() if k != "ok"}
    return [f"{action}: {json.dumps(facts, ensure_ascii=False)}"] if facts else []


class ReactAgentAdapter:
    """AgentPort 구현 — 기존 run_react_agent 재사용(수정 없음)."""

    def __init__(self, db: Session, chat_fn=None, max_steps: int = 3) -> None:
        self._db = db
        self._chat_fn = chat_fn
        self._max_steps = max_steps

    def run(self, question: str) -> AgentTurn:
        from app.agent.react import run_react_agent

        resp = run_react_agent(
            question, self._db, chat_fn=self._chat_fn, max_steps=self._max_steps
        )
        evidence: list[str] = []
        steps: list[dict[str, Any]] = []
        for s in resp.steps:
            evidence.extend(observation_to_evidence(s.action, s.observation))
            steps.append(
                {
                    "step": s.step,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": s.observation,
                }
            )
        return AgentTurn(
            draft=resp.answer, evidence=evidence, steps=steps, stopped_by=resp.stopped_by
        )
