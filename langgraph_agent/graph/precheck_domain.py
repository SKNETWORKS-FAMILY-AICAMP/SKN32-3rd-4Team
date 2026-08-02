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
    NOT_RESOLVED = "NOT_RESOLVED"
    DOCUMENT_NOT_RELIABLE = "DOCUMENT_NOT_RELIABLE"
    NO_EVIDENCE = "NO_EVIDENCE"
    CITATION_UNVERIFIED = "CITATION_UNVERIFIED"
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
    abstained: bool = False
    reason_code: ReasonCode | None = None
    applied_generation: str | None = None
