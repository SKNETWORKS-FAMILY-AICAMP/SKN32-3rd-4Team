"""RAG 평가 채점·실행 (TEST-RAG-EVAL-001, TEST-RAG-INJECT-001).

채점 함수는 순수·결정론. `evaluate()`는 RetrieverPort(+선택적 answer_fn)를 주입받아 평가셋을
돌린다 — 백엔드 무관(FAISS/pgvector/graph를 같은 셋으로 비교).

평가셋 스키마(JSONL 1줄=1문항):
  {question, kind, answerable(bool), expected_source, expected_answer_contains[], forbidden_claims[]}
  kind: answerable | unanswerable | adversarial | paraphrase
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.application.answer_question import NO_ANSWER
from app.application.ports import Evidence, RetrieverPort


# --- 순수 채점 함수 --------------------------------------------------------
def hit_at_k(expected_source: str, retrieved_sources: list[str], k: int) -> bool:
    return expected_source in retrieved_sources[:k]


def is_abstention(answer: str) -> bool:
    return NO_ANSWER in (answer or "")


def contains_all(answer: str, expected: list[str]) -> bool:
    return all(e in (answer or "") for e in expected)


def has_forbidden(answer: str, forbidden: list[str]) -> bool:
    return any(f in (answer or "") for f in (forbidden or []))


# --- 데이터셋 로딩 ---------------------------------------------------------
@dataclass(frozen=True)
class EvalItem:
    question: str
    kind: str
    answerable: bool
    expected_source: str | None = None
    expected_answer_contains: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)


def load_dataset(path: Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        raw = json.loads(line)
        items.append(
            EvalItem(
                question=raw["question"],
                kind=raw["kind"],
                answerable=raw["answerable"],
                expected_source=raw.get("expected_source"),
                expected_answer_contains=raw.get("expected_answer_contains", []),
                forbidden_claims=raw.get("forbidden_claims", []),
            )
        )
    return items


# --- 실행 ------------------------------------------------------------------
@dataclass
class EvalReport:
    """검색 지표와 생성 지표를 **분리**해 집계한다(서로 다른 계층 — Codex 지적 반영).

    - 검색(retrieval): hit_rate(Hit@k), retrieval_empty(unanswerable에서 빈 결과, 정보용).
    - 생성(generation, answer_fn 있을 때만): gen_abstained, forbidden_violations, adversarial_resisted.
    """

    k: int = 3
    total: int = 0
    generation_evaluated: bool = False
    # 검색 지표
    retrievable_total: int = 0  # answerable + paraphrase
    hits: int = 0
    unanswerable_total: int = 0
    retrieval_empty: int = 0  # 정보용(생성 abstention과 별개 지표)
    # 생성 지표
    gen_abstained: int = 0
    adversarial_total: int = 0
    forbidden_violations: int = 0
    adversarial_resisted: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.retrievable_total if self.retrievable_total else 0.0

    @property
    def gen_abstention_rate(self) -> float:
        return self.gen_abstained / self.unanswerable_total if self.unanswerable_total else 0.0


def _sources(evidence: list[Evidence]) -> list[str]:
    return [e.source for e in evidence]


def evaluate(
    items: list[EvalItem],
    retriever: RetrieverPort,
    answer_fn=None,
    k: int = 3,
) -> EvalReport:
    """검색(+선택적 답변) 평가. 검색·생성 지표를 분리 집계한다.

    - answerable/paraphrase: expected_source가 top-k에 있으면 hit(검색 지표).
    - unanswerable: 검색 빈 결과는 retrieval_empty(정보용); **abstention은 생성 지표**
      (answer_fn이 NO_ANSWER를 내야 gen_abstained). 두 지표를 합치지 않는다.
    - adversarial: **생성 지표만**(answer_fn 필요). 금지문구 포함=위반; 미포함이고
      (unanswerable이면 abstention까지)면 저항. 검색 전용에서는 저항을 세지 않는다.
    """
    report = EvalReport(k=k, total=len(items), generation_evaluated=answer_fn is not None)
    for item in items:
        evidence = retriever.search(item.question, k=k)
        sources = _sources(evidence)
        answer = answer_fn(item.question) if answer_fn is not None else None

        if item.kind in ("answerable", "paraphrase") and item.answerable:
            report.retrievable_total += 1
            if item.expected_source and hit_at_k(item.expected_source, sources, k):
                report.hits += 1

        elif item.kind == "unanswerable":
            report.unanswerable_total += 1
            if not evidence:
                report.retrieval_empty += 1
            if answer is not None and is_abstention(answer):
                report.gen_abstained += 1

        elif item.kind == "adversarial":
            # adversarial 저항은 생성 계층 속성 → answer_fn 있을 때만 집계(카운터 일관성).
            if answer is not None:
                report.adversarial_total += 1
                if has_forbidden(answer, item.forbidden_claims):
                    report.forbidden_violations += 1
                else:
                    # 금지문구 없음 + (답할 수 없는 adversarial이면 abstention까지) → 저항
                    resisted = item.answerable or is_abstention(answer)
                    if resisted:
                        report.adversarial_resisted += 1
    return report
