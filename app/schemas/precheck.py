"""보장 사전판정 계약 스키마 (v1).

★이 파일이 팀 전체의 **단일 계약**이다

    AI 담당 2명 · Agent 담당 · 백엔드 담당이 병렬로 일하려면
    주고받는 것의 모양이 먼저 얼어야 한다. 여기가 그 자리다.
    **바꾸려면 팀에 알리고 버전을 올린다.** 조용히 필드를 늘리지 않는다.

★설계에서 지킨 것

    1. `unknown` 은 **정상 결과**다. 오류가 아니다.
       근거를 못 대면 그렇게 답하는 것이 맞고, HTTP 200 으로 나간다.
    2. 인용은 **조항 발생(occurrence)** 을 가리킨다 — 어느 약관 버전의 몇 쪽인지가
       같이 나와야 사용자가 원문을 확인할 수 있다.
    3. 모든 응답에 **무엇으로 판정했는지**(약관 버전·규칙 버전·추출기 버전)를 담는다.
       나중에 "왜 그때 그렇게 답했나"를 재현할 수 있어야 한다.
    4. 외부 에이전트가 준 정보는 **약관과 같은 등급으로 쓰지 않는다**(`evidence_tier`).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.core.domain.insurance import Verdict

SCHEMA_VERSION = "v1"


#: ★판정 결과는 **도메인이 정의한다.** 여기서 다시 만들지 않는다.
#:
#:   처음에 `covered / not_covered / conditional / unknown` 4값을 여기 새로 만들었다가
#:   `app/core/domain/insurance.py` 에 이미 `Verdict` 가 있는 것을 뒤늦게 알았다.
#:   같은 사실이 두 곳에 있으면 반드시 갈라진다(ARCH-003 이 이걸 막는다).
#:
#:   도메인 쪽 4단이 더 낫다 — *"이진 판정(된다/안된다)은 만들지 않는다"* 는
#:   원칙이 값 자체에 박혀 있다.
#:
#:       LIKELY_COVERED   보장 조항 근거가 있다
#:       UNLIKELY         면책 조항 근거가 있다
#:       NEEDS_DOCUMENTS  조건부 — 요양급여 해당 여부 등 확인이 필요하다
#:       NEEDS_EXPERT     ★근거가 부족하다. 사람이 봐야 한다(정상 결과다)


class ReasonCode(str, Enum):
    """왜 그렇게 판정했는지. `unknown` 일 때 특히 중요하다."""

    # 판정에 이른 경우
    EXCLUDED_BY_CLAUSE = "excluded_by_clause"
    EXCEPTION_APPLIES = "exception_applies"
    COVERED_BY_CLAUSE = "covered_by_clause"
    # 판정하지 못한 경우
    INSURER_NOT_SUPPORTED = "insurer_not_supported"
    NO_VERSION_AT_DATE = "no_version_at_date"
    AMBIGUOUS_PRODUCT = "ambiguous_product"
    AMBIGUOUS_PRODUCT_LINE = "ambiguous_product_line"
    NO_EVIDENCE = "no_evidence"
    DOCUMENT_NOT_RELIABLE = "document_not_reliable"
    CITATION_UNVERIFIED = "citation_unverified"
    INVALID_CODE = "invalid_code"


class EvidenceTier(str, Enum):
    """근거의 급. ★섞어 쓰지 않는다."""

    POLICY_CLAUSE = "policy_clause"       # 약관 원문 — 유일하게 판정 근거가 된다
    EXTERNAL_REPORT = "external_report"   # 외부 에이전트가 준 사례 — 참고만
    STATISTICS = "statistics"             # 승인율 등 집계 — 참고만


class Citation(BaseModel):
    """인용 조항 하나. **원문을 찾아갈 수 있어야 한다.**"""

    clause_id: str = Field(description="`{sha12}/{부}/{조번호}`")
    qualified_no: str = Field(description="`보통약관/제9조`")
    section: str = ""
    title: str = ""
    quote: str = Field(default="", description="실제 인용한 문장(원문 부분 문자열)")
    page_from: int = 0
    page_to: int = 0
    tier: EvidenceTier = EvidenceTier.POLICY_CLAUSE


class AppliedPolicy(BaseModel):
    """무엇으로 판정했는가."""

    insurer: str
    product_name: str
    sale_start: str
    sale_end: str = ""
    generation: int | None = None
    generation_label: str = ""
    product_line: str = ""
    sha256: str = ""
    #: 날짜·세대를 얼마나 믿을 수 있나. `exact` / `month` / `ambiguous` / `unknown`
    date_confidence: str = "exact"
    generation_confidence: str = ""
    #: 조항 구조화 상태. `ok` 가 아니면 판정 근거로 쓰지 않는다.
    parse_status: str = "ok"


class PrecheckRequest(BaseModel):
    """사전판정 요청."""

    insurer: str = Field(description="보험사명. 예: 삼성화재")
    enrolled_on: str = Field(description="가입일 `YYYYMMDD`")
    kcd_codes: list[str] = Field(description="질병기호. 예: ['F32','S72.0']", min_length=1)
    product_name: str | None = Field(
        default=None, description="상품명. 없으면 여러 후보일 때 되묻는다"
    )
    #: 외부 에이전트가 호출할 때 자기 참조를 담는다(감사용).
    client_ref: str | None = None


class CodeAssessment(BaseModel):
    """질병코드 하나에 대한 판정."""

    code: str
    verdict: Verdict
    reason_code: ReasonCode | None = None
    citations: list[Citation] = Field(default_factory=list)
    note: str = ""


class PrecheckResult(BaseModel):
    """사전판정 결과.

    ★`abstained=True` 여도 HTTP 200 이다. "확인 불가"는 정상 응답이다.
      입력 오류는 422, 검색·DB 장애는 503 으로 구분한다.
    """

    schema_version: str = SCHEMA_VERSION
    verdict: Verdict
    abstained: bool = False
    reason_code: ReasonCode | None = None
    message: str = ""

    applied_policy: AppliedPolicy | None = None
    per_code: list[CodeAssessment] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    #: 되묻기용 후보(상품이 여럿일 때).
    candidates: list[AppliedPolicy] = Field(default_factory=list)

    #: 재현에 필요한 것들. ★"왜 그때 그렇게 답했나"를 답할 수 있어야 한다.
    rule_engine_version: str = ""
    extractor: str = ""
    trace_id: str = ""

    #: 판정에 쓰지 못한 근거가 있으면 여기 남긴다(조용히 버리지 않는다).
    warnings: list[str] = Field(default_factory=list)


class ExternalCaseSubmission(BaseModel):
    """외부 에이전트가 주는 사례 보고.

    ★이건 **판정 근거가 아니다.** 통계·검증에만 쓴다.
      약관 조항과 같은 인덱스에 넣지 않는다(§docs/handoff/ 데이터 축적 설계).
    """

    client_ref: str = Field(description="보고한 에이전트의 자기 식별자")
    insurer: str
    enrolled_on: str = ""
    kcd_codes: list[str] = Field(default_factory=list)
    #: 실제로 어떻게 됐나. `paid` / `denied` / `partial` / `pending`
    outcome: str
    outcome_reason: str = ""
    #: 우리 판정과 대조할 수 있게 `trace_id` 를 주면 좋다(선택).
    precheck_trace_id: str | None = None
    #: ★검증 상태. 기본은 미검증이다. 검증 없이 통계에 넣지 않는다.
    verification: str = "unverified"
