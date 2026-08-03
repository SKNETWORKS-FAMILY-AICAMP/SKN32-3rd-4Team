"""app/workflow/precheck_graph.py::build() -- 실제 조립(LLM explain 포함)이
끝까지 도는지 확인한다. 페이크 어댑터 + 페이크 LLM으로 real build()를 검증.
"""

from app.core.domain.insurance import Verdict
from app.core.ports.precheck import ClauseRow, PolicyVersionRow
from app.workflow.precheck_graph import build


class _FakePolicies:
    def __init__(self, version):
        self._version = version

    def load_versions(self):
        return [self._version]

    def resolve(self, **kwargs):
        return self._version


class _FakeClauses:
    def __init__(self, rows, stats):
        self._rows = rows
        self._stats = stats

    def stats(self, sha256):
        return self._stats

    def load_clauses(self, sha256, *, usable_only=True):
        return [r for r in self._rows if (not usable_only or r.usable)]

    def search(self, sha256, query, *, limit=8):
        return self._rows[:limit]


class _FakeLlm:
    def __init__(self, response):
        self._response = response
        self.call_count = 0

    def complete(self, prompt):
        self.call_count += 1
        return self._response


def _version():
    return PolicyVersionRow(
        insurer="가보험", product_name="실손의료비보험", sale_start="20180101",
        sale_end="", generation=3, generation_label="3세대", product_line="standard",
        sha256="a" * 64, date_confidence="exact", generation_confidence="exact",
    )


def _clause_row(text):
    return ClauseRow(
        sha256="a" * 64, qualified_no="제4조", clause_no="4", section="본문",
        title="보상하지 않는 사항", text=text, page_from=3, page_to=3,
        content_hash="h1",
    )


def _setup(monkeypatch, *, clause_text, llm_response, parse_status="ok"):
    policies = _FakePolicies(_version())
    clauses = _FakeClauses(
        [_clause_row(clause_text)],
        stats={"parse_status": parse_status, "extractor": "test"},
    )
    monkeypatch.setattr(
        "app.composition.build_precheck",
        lambda: {"policies": policies, "clauses": clauses},
    )
    fake_llm = _FakeLlm(llm_response)
    monkeypatch.setattr("app.core.llm_clients.LlmClient", lambda: fake_llm)
    return fake_llm


def test_끝까지_돌면_LLM이_만든_설명이_응답에_실린다(monkeypatch):
    fake_llm = _setup(
        monkeypatch,
        clause_text="회사는 다음의 의료비에 대해서는 보상하지 않습니다. 정신질환(F32~F39)",
        llm_response="답변: F32는 정신질환 면책 조항에 해당합니다 [E001]\n인용: E001",
    )
    from app.core.domain.precheck_result import PrecheckInput

    graph = build()
    outcome, _st = graph.invoke(
        PrecheckInput(insurer="가보험", enrolled_on="20200101", kcd_codes=("F32",))
    )

    assert outcome.verdict is Verdict.UNLIKELY
    assert outcome.abstained is False
    assert "면책" in outcome.message
    assert outcome.cited_handles == ("E001",)
    assert fake_llm.call_count == 1


def test_LLM이_없는_조항을_지어내면_검증에서_걸러지고_기권한다(monkeypatch):
    """★규칙엔진 근거는 있는데, LLM이 손잡이를 엉뚱하게 지어낸 경우."""
    _setup(
        monkeypatch,
        clause_text="회사는 다음의 의료비에 대해서는 보상하지 않습니다. 정신질환(F32~F39)",
        llm_response="답변: 면책입니다 [E099]\n인용: E099",  # 존재하지 않는 손잡이
    )
    from app.core.domain.precheck_result import PrecheckInput

    graph = build()
    outcome, st = graph.invoke(
        PrecheckInput(insurer="가보험", enrolled_on="20200101", kcd_codes=("F32",))
    )

    #: ★재시도(최대 2회) 후에도 검증 실패하면 설명 초안을 버리고 기권한다.
    assert outcome.abstained is True
    assert outcome.citations == () and outcome.per_code == ()
    assert st.retries <= 2


def test_문서상태가_ok가_아니면_LLM을_아예_안_부른다(monkeypatch):
    fake_llm = _setup(
        monkeypatch,
        clause_text="아무 내용",
        llm_response="답변: 아무 설명\n인용: E001",
        parse_status="suspect",
    )
    from app.core.domain.precheck_result import PrecheckInput

    graph = build()
    outcome, _st = graph.invoke(
        PrecheckInput(insurer="가보험", enrolled_on="20200101", kcd_codes=("F32",))
    )

    assert outcome.abstained is True
    assert outcome.reason_code.value == "document_not_reliable"
    assert fake_llm.call_count == 0
