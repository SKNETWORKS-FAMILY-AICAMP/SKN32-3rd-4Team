"""사전판정 유스케이스가 바깥에 요구하는 것 — 포트.

이 모듈은 **프레임워크도 바깥 계층도 모른다**(클린아키텍처 2단계 안쪽).
구현은 `app/adapters/` 가 한다.

★왜 이 포트가 따로 필요한가

    `app/core/ports/insurance.py` 에 이미 `PolicyVersionResolverPort` 가 있다.
    그건 **DB 에 적재된 뒤**를 전제로 `product_id` 로 해소한다.

    지금 프로토타입은 **매니페스트 파일**을 직접 읽는다. 아직 DB 적재 전이다.
    그래서 "보험사명 + 가입일 + 상품명"으로 찾는 **파일 단계 포트**를 따로 둔다.

    ★DB 적재가 끝나면 이 포트는 사라지고 `PolicyVersionResolverPort` 로 합친다.
      두 개가 영구히 공존하면 안 된다 — 같은 일을 두 곳에서 하게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class PolicyVersionRow:
    """매니페스트 한 줄을 판정에 필요한 만큼만 투영한 것.

    ★`app/core/domain/insurance.PolicyVersion` 과 **다른 것**이다.
      저쪽은 DB 적재 후의 도메인 엔티티(`date` 타입·`identification_status`)이고,
      이쪽은 **파일에서 막 읽은 값**이다(`YYYYMMDD` 문자열).
      섞으면 "확정된 것"과 "아직 아닌 것"이 구분되지 않는다.
    """

    insurer: str
    product_name: str
    sale_start: str
    sale_end: str
    generation: int | None
    generation_label: str
    product_line: str
    sha256: str
    date_confidence: str
    generation_confidence: str
    generation_review: str = ""

    @property
    def is_rider(self) -> bool:
        """특별약관(부가 특약)인가."""
        from app.core.domain.policy_naming import looks_like_rider

        return looks_like_rider(self.product_name)

    @property
    def usable_for_judgment(self) -> bool:
        """자동 판정에 쓸 수 있는가."""
        if self.date_confidence not in ("exact", "month"):
            return False
        #: ★`00000000` 은 "모른다"를 뜻하는 자리표시자다. 날짜가 아니다.
        if not self.sale_start or self.sale_start == "00000000":
            return False
        return True


@dataclass(frozen=True)
class NotResolved:
    """확정하지 못했다. **추측하지 않는다.**"""

    reason_code: str
    message: str
    candidates: tuple[PolicyVersionRow, ...] = ()


@dataclass(frozen=True)
class ClauseRow:
    """조항 하나. 판정에 넘길 최소 단위."""

    sha256: str
    qualified_no: str
    clause_no: str
    section: str
    title: str
    text: str
    page_from: int
    page_to: int
    content_hash: str
    usable: bool = True
    unusable_reason: str = ""

    @property
    def clause_id(self) -> str:
        """문서 안에서 이 조항을 가리키는 식별자.

        ★`{sha12}/{qualified_no}` 만으로는 **유일하지 않다.**
          실측(v4 전량 1,367문서): `qualified_no` 중복 31,085건 / 1,181문서(86%).
          부 탐지 입도가 특약보다 굵어 서로 다른 특약이 한 라벨 아래 뭉친다.

              p73  보험료 자동납입 특별약관/1.   "보험료 납입"            324자
              p73  보험료 자동납입 특별약관/1.   "특별약관의 체결 및 효력"  798자

          그래서 **내용 해시**를 덧붙인다. 같은 자리에 실린 다른 내용이 구분된다.
          `content_hash` 는 조항 구조화 때 이미 계산해 둔 값이다.

        ★영속 식별자가 아니다. 재추출하면 부 라벨이 바뀔 수 있다.
          저장소에 넣을 때는 별도 UUID 를 발급하고 이건 조회 키로만 쓴다.
        """
        tail = f"#{self.content_hash[:8]}" if self.content_hash else ""
        return f"{self.sha256[:12]}/{self.qualified_no}{tail}"


@runtime_checkable
class PolicyVersionSourcePort(Protocol):
    """판정 대상 약관 버전 목록을 준다."""

    def load_versions(self) -> list[PolicyVersionRow]: ...

    def resolve(
        self,
        *,
        insurer: str,
        enrolled_on: str,
        product_name: str | None = None,
        versions: list[PolicyVersionRow] | None = None,
    ) -> PolicyVersionRow | NotResolved: ...


@runtime_checkable
class ClauseSourcePort(Protocol):
    """확정된 약관 버전의 조항을 준다.

    ★검색 범위를 약관 버전으로 **가둔다.** 전체에서 찾으면
      2019년 가입자에게 2024년 조항이 근거로 붙는다.
    """

    def load_clauses(self, sha256: str, *, usable_only: bool = True) -> list[ClauseRow]: ...

    def stats(self, sha256: str) -> dict: ...

    def search(self, sha256: str, query: str, *, limit: int = 8) -> Sequence[ClauseRow]: ...
