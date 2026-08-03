"""
tests/test_main.py

역할:
    main.py의 진입점(run)이 실제로 graph/precheck_graph.py(계약 기준 그래프)를
    부르는지 검증한다. 예전엔 graph/builder.py(5개 기능 라우터)를 불렀는데,
    인용검증·해시·기권구조가 없어서 옮겼다 -- 그 배선이 유지되는지 확인.

    LLM/약관검색은 monkeypatch로 대체해 API 키·벡터DB 없이도 검증 가능하게 한다.
"""

import graph.precheck_graph as precheck_graph_module
import main


class _FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, _prompt):
        return type("Response", (), {"content": self._content})()


def test_main_run_uses_precheck_graph(monkeypatch):
    monkeypatch.setattr(
        main,
        "build",
        lambda: precheck_graph_module.PrecheckGraph(
            resolve_policy=lambda body: precheck_graph_module.PolicyResolution(generation="3세대"),
            gate_document=lambda generation: True,
            retrieve=lambda body, generation: (
                precheck_graph_module.Citation(article_no="제9조", article_title="면책", quote="원문"),
            ),
            assess=lambda body, clauses: (
                precheck_graph_module.PerCodeVerdict(
                    code="F32", verdict=precheck_graph_module.Verdict.NEEDS_DOCUMENTS
                ),
            ),
            explain=lambda body, per_code, clauses: ("제9조에 따르면 조건부 확인이 필요합니다", ("E001",)),
            verify=lambda message, cited_handles, clauses: (True, None, ""),
        ),
    )

    result = main.run("F32 보장되나요?", kcd_codes=("F32",), enrolled_on="2020-01-01")

    assert result.abstained is False
    assert result.verdict.value == "needs_documents"
    assert result.citations[0].article_no == "제9조"


def test_main_run_abstains_without_enrolled_on():
    """가입일시 없이 물으면 resolve_policy가 확정 못 해서 기권해야 한다."""
    result = main.run("아무 질문")

    assert result.abstained is True
