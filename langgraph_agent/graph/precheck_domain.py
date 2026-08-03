"""
graph/precheck_domain.py

역할:
    사전판정(precheck) 흐름에서 쓰는 도메인 타입 (계약: 06_계약_Agent.md,
    docs/storyboard.html).
    PrecheckInput/PrecheckOutcome, Verdict/ReasonCode enum, Citation,
    ProductCandidate, PolicyResolution, PerCodeVerdict 정의.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    LIKELY_COVERED = "likely_covered"
    NEEDS_DOCUMENTS = "needs_documents"
    UNLIKELY = "unlikely"
    NEEDS_EXPERT = "needs_expert"


class ReasonCode(Enum):
    """
    값은 전부 소문자 snake_case -- storyboard.html/08_계약_프론트.md에 나오는
    실제 reason_code 예시(예: "no_evidence", "ambiguous_product_line")와 맞춘 것.
    REST로 그대로 나가는 값이라 대소문자가 섞이면 클라이언트 매칭 로직이 깨진다.
    """

    NOT_RESOLVED = "not_resolved"
    DOCUMENT_NOT_RELIABLE = "document_not_reliable"
    NO_EVIDENCE = "no_evidence"
    CITATION_UNVERIFIED = "citation_unverified"
    NO_VERSION_AT_DATE = "no_version_at_date"
    INSURER_NOT_SUPPORTED = "insurer_not_supported"
    AMBIGUOUS_PRODUCT_LINE = "ambiguous_product_line"


@dataclass(frozen=True)
class Citation:
    article_no: str
    article_title: str
    quote: str
    generation: str | None = None
    source_file: str | None = None
    #: 영속 식별자(문서해시+조항번호 등). 실데이터 연동 전까지는 비어있을 수 있음.
    clause_id: str = ""
    #: citation_guard 검증용 정규화 경로("보통약관/제9조" 등).
    #: 비어있으면 article_no만으로 취급된다 -- 특약이 여러 개면 이 값을 채워야
    #: 같은 번호(제9조)가 다른 문서를 가리키는 걸 구분할 수 있다.
    qualified_no: str = ""


@dataclass(frozen=True)
class ProductCandidate:
    """resolve_policy가 1:N으로 확정 못 했을 때 돌려주는 후보 하나."""

    product_name: str
    product_line: str
    generation: str


@dataclass(frozen=True)
class PolicyResolution:
    """
    resolve_policy 노드의 결과.

    generation이 있으면 확정된 것이고, 없으면 reason_code로 왜 확정
    못 했는지(candidates가 있으면 1:N 되묻기, 없으면 그 외 사유)를 구분한다.
    """

    generation: str | None = None
    candidates: tuple[ProductCandidate, ...] = ()
    reason_code: ReasonCode | None = None


@dataclass(frozen=True)
class PerCodeVerdict:
    """kcd_codes 하나하나에 대한 개별 판정."""

    code: str
    verdict: Verdict
    reason_code: ReasonCode | None = None


@dataclass(frozen=True)
class PrecheckInput:
    """PrecheckRequest -- 외부(REST/MCP)에서 받는 입력."""

    query: str
    kcd_codes: tuple[str, ...] = ()
    insurer: str = ""
    enrolled_on: str = ""  # "YYYY-MM-DD"


@dataclass
class PrecheckOutcome:
    """PrecheckResult -- 그래프가 출력하는 구조화된 결과."""

    verdict: Verdict
    citations: tuple[Citation, ...] = ()
    per_code: tuple[PerCodeVerdict, ...] = ()
    candidates: tuple[ProductCandidate, ...] = ()
    message: str = ""
    #: explain()이 message 안에서 실제로 인용했다고 선언한 손잡이(E001 등).
    #: verify_citations이 citations와 대조하는 데 쓴다.
    cited_handles: tuple[str, ...] = ()
    abstained: bool = False
    reason_code: ReasonCode | None = None
    applied_generation: str | None = None
