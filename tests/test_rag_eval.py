"""RAG 평가 하네스 — 결정론 채점 로직 + 데이터셋 구성(TEST-RAG-EVAL 채점부)."""

from __future__ import annotations

import pathlib
from collections import Counter

from app.application.answer_question import NO_ANSWER
from app.application.ports import Evidence
from app.eval.rag_eval import (
    EvalItem,
    contains_all,
    evaluate,
    has_forbidden,
    hit_at_k,
    is_abstention,
    load_dataset,
)

_DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval" / "rag_v1.jsonl"


def test_scoring_functions():
    assert hit_at_k("a.pdf", ["a.pdf", "b.txt"], 3) is True
    assert hit_at_k("c.pdf", ["a.pdf", "b.txt"], 3) is False
    assert hit_at_k("b.txt", ["a.pdf", "b.txt", "c.md"], 1) is False  # top-1만
    assert is_abstention(NO_ANSWER) is True
    assert is_abstention("환불은 7일입니다") is False
    assert contains_all("환불은 7일 이내", ["7일"]) is True
    assert contains_all("환불", ["7일"]) is False
    assert has_forbidden("무료 반품 가능합니다", ["무료 반품 가능"]) is True
    assert has_forbidden("고객 부담입니다", ["무료 반품 가능"]) is False


def test_dataset_composition():
    # 구성 고정: 개발 참고 문서를 RAG 코퍼스에서 분리(data/dev_docs/)하면서 그 문서를 정답
    # 출처로 하던 answerable 10문항을 dev_docs_v1.jsonl로 옮겼다 → 30문항에서 20문항으로 축소.
    # 과거 리포트의 Hit@3 수치는 개발 문서가 포함된 코퍼스 기준이라 직접 비교할 수 없다.
    items = load_dataset(_DATA)
    assert len(items) == 20
    c = Counter(i.kind for i in items)
    assert c["answerable"] == 10
    assert c["unanswerable"] == 5
    assert c["adversarial"] == 3
    assert c["paraphrase"] == 2
    # answerable/paraphrase는 expected_source가 있어야 함
    for i in items:
        if i.kind in ("answerable", "paraphrase"):
            assert i.expected_source


class _MapRetriever:
    """질문→소스 리스트 매핑을 반환하는 결정론 페이크(평가 로직 검증용)."""

    def __init__(self, mapping: dict[str, list[str]]):
        self._m = mapping

    def search(self, query, k=None, source=None):
        return [Evidence("c", s, None, 0.9, "map") for s in self._m.get(query, [])]


def test_evaluate_retrieval_hits_and_empty():
    items = [
        EvalItem("q1", "answerable", True, expected_source="a.pdf"),
        EvalItem("q2", "answerable", True, expected_source="b.txt"),
        EvalItem("q3", "unanswerable", False),
    ]
    retr = _MapRetriever({"q1": ["a.pdf", "x"], "q2": ["z"], "q3": []})  # q2 miss, q3 empty
    rep = evaluate(items, retr, k=3)  # 검색만
    assert rep.retrievable_total == 2
    assert rep.hits == 1  # q1 hit, q2 miss
    assert rep.hit_rate == 0.5
    assert rep.unanswerable_total == 1
    assert rep.retrieval_empty == 1  # q3 검색 빈 결과(정보용)
    assert rep.gen_abstained == 0  # 생성 미평가 → abstention 지표 0
    assert rep.generation_evaluated is False


def test_evaluate_generation_abstention_and_adversarial():
    items = [
        EvalItem("unans", "unanswerable", False),
        EvalItem("bad", "adversarial", True, forbidden_claims=["무료 반품 가능"]),
        EvalItem("unans_adv", "adversarial", False, forbidden_claims=["비밀번호는"]),
    ]
    retr = _MapRetriever({})

    def _answer(q: str) -> str:
        return {
            "unans": NO_ANSWER,  # 정상 abstention
            "bad": "무료 반품 가능합니다",  # 금지문구 위반
            "unans_adv": "제공된 문서에서 찾을 수 없습니다.",  # unanswerable-adv → abstain(저항)
        }[q]

    rep = evaluate(items, retr, k=3, answer_fn=_answer)
    assert rep.generation_evaluated is True
    assert rep.gen_abstained == 1  # unans
    assert rep.gen_abstention_rate == 1.0
    assert rep.forbidden_violations == 1  # bad
    assert rep.adversarial_resisted == 1  # unans_adv(금지문구 없음 + abstain)


def test_adversarial_not_counted_in_retrieval_only():
    items = [EvalItem("x", "adversarial", False, forbidden_claims=["무료"])]
    rep = evaluate(items, _MapRetriever({}), k=3)  # answer_fn 없음
    assert rep.adversarial_resisted == 0  # 검색 전용에서 trivial 성공 처리 안 함
    assert rep.forbidden_violations == 0
