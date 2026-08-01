"""근거 신선도 게이트 — 만료·미시행 근거로 답하지 못하게 막는지 검증.

핵심 관점: **모르는 문서를 최신으로 간주하지 않는다**(그게 폴백), **감지하고도 신호를
남기지 않는 자동복구를 허용하지 않는다**.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.adapters.freshness_gate import (
    MANIFEST_NAME,
    MODE_ERROR,
    MODE_FILTER,
    FreshnessGatedRetriever,
    load_manifest,
)
from app.application.ports import Evidence
from app.core.errors import ConfigError, InfraError, ValidationErr

TODAY = date(2026, 7, 23)


class FakeRetriever:
    def __init__(self, sources: list[str]) -> None:
        self.sources = sources

    def search(self, query: str, k: int | None = None, source: str | None = None):
        return [Evidence(f"{s} 본문", s, "p.1", 0.9, "fake") for s in self.sources]


def _mf(**entries) -> dict[str, dict]:
    return dict(entries)


FRESH = {"valid_from": "2026-01-01", "review_by": "2027-01-01"}
EXPIRED = {"valid_from": "2024-01-01", "review_by": "2025-01-01"}
FUTURE = {"valid_from": "2027-01-01", "review_by": "2028-01-01"}


def test_fresh_evidence_passes_through():
    gate = FreshnessGatedRetriever(
        FakeRetriever(["a.pdf"]), _mf(**{"a.pdf": FRESH}), today=TODAY
    )
    evs = gate.search("q")
    assert [e.source for e in evs] == ["a.pdf"]


def test_expired_evidence_fails_explicitly_by_default():
    """기본 모드는 명시적 실패 — 낡은 근거로 조용히 답하지 않는다."""
    gate = FreshnessGatedRetriever(
        FakeRetriever(["old.pdf"]), _mf(**{"old.pdf": EXPIRED}), today=TODAY
    )
    with pytest.raises(InfraError) as exc:
        gate.search("q")
    assert "review_by" in str(exc.value)


def test_not_yet_effective_document_is_also_blocked():
    """아직 시행되지 않은 개정본도 '지금 인용하면 안 되는 근거'다."""
    gate = FreshnessGatedRetriever(
        FakeRetriever(["future.pdf"]), _mf(**{"future.pdf": FUTURE}), today=TODAY
    )
    with pytest.raises(InfraError) as exc:
        gate.search("q")
    assert "시행" in str(exc.value)


def test_unknown_source_raises_instead_of_assuming_fresh():
    """★매니페스트에 없는 문서를 '최신'으로 간주하면 폴백이다 → ConfigError."""
    gate = FreshnessGatedRetriever(FakeRetriever(["unknown.pdf"]), _mf(), today=TODAY)
    with pytest.raises(ConfigError) as exc:
        gate.search("q")
    assert "매니페스트" in str(exc.value)


def test_filter_mode_requires_audit_callback():
    """★감지하고도 아무 신호를 남기지 않는 자동복구는 폴백 — 콜백 없으면 생성 자체를 거부."""
    with pytest.raises(ValidationErr):
        FreshnessGatedRetriever(
            FakeRetriever(["old.pdf"]), _mf(**{"old.pdf": EXPIRED}),
            today=TODAY, mode=MODE_FILTER, on_expired=None,
        )


def test_filter_mode_drops_expired_and_emits_audit():
    seen: list[list[tuple[str, str]]] = []
    gate = FreshnessGatedRetriever(
        FakeRetriever(["old.pdf", "ok.pdf"]),
        _mf(**{"old.pdf": EXPIRED, "ok.pdf": FRESH}),
        today=TODAY, mode=MODE_FILTER, on_expired=seen.append,
    )
    evs = gate.search("q")
    assert [e.source for e in evs] == ["ok.pdf"]          # 만료분만 제거
    assert seen and seen[0][0][0] == "old.pdf"            # 감사 신호 발생
    assert "review_by" in seen[0][0][1]


def test_unknown_mode_rejected():
    with pytest.raises(ValidationErr):
        FreshnessGatedRetriever(FakeRetriever([]), _mf(), mode="skip")


def test_bad_date_format_raises():
    gate = FreshnessGatedRetriever(
        FakeRetriever(["x.pdf"]), _mf(**{"x.pdf": {"review_by": "2026/01/01"}}), today=TODAY
    )
    with pytest.raises(ConfigError):
        gate.search("q")


# --- 매니페스트 로딩 ------------------------------------------------------
def test_missing_manifest_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_manifest(tmp_path / MANIFEST_NAME)


def test_real_corpus_manifest_covers_every_indexed_document():
    """실제 코퍼스의 모든 색인 대상 문서가 매니페스트에 등록돼 있어야 한다.

    문서를 추가하고 매니페스트를 빠뜨리면 런타임에 ConfigError가 나므로, 그걸 미리 잡는다.
    """
    from app.core.config import get_settings

    docs = get_settings().DOCS_DIR
    manifest = load_manifest(docs / MANIFEST_NAME)
    indexed = sorted([p.name for p in docs.glob("*.txt")] + [p.name for p in docs.glob("*.pdf")])
    missing = [n for n in indexed if n not in manifest]
    assert not missing, f"매니페스트에 없는 색인 문서: {missing}"


def test_dev_docs_are_not_in_rag_corpus():
    """개발 참고 문서는 RAG 색인 대상에서 분리돼 있어야 한다(엉뚱한 인용 방지)."""
    from app.core.config import get_settings

    docs = get_settings().DOCS_DIR
    names = {p.name for p in docs.iterdir() if p.is_file()}
    for dev in ("loop_safety.txt", "react_agent_overview.txt", "tool_design_rules.txt"):
        assert dev not in names, f"{dev}가 아직 코퍼스에 있습니다"
    assert (docs.parent / "dev_docs" / "loop_safety.txt").is_file(), "dev_docs로 이동돼야 합니다"


def test_manifest_json_is_valid():
    from app.core.config import get_settings

    raw = (get_settings().DOCS_DIR / MANIFEST_NAME).read_text(encoding="utf-8")
    data = json.loads(raw)
    for name, meta in data.items():
        assert "review_by" in meta, f"{name}: review_by 누락"
        assert "source_url" in meta, f"{name}: source_url 누락"
        date.fromisoformat(meta["review_by"])
