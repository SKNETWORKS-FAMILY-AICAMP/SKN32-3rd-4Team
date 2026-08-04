"""근거 신선도 게이트 — 만료된 문서로 답하는 것을 막는다.

배경(`docs/reports/2026-07-23_0100_RAG_코퍼스_보강_조사_리포트.md` 부록 B): 지금까지는 낡은
문서와 최신 문서를 구분하지 못했다. 정책·법령처럼 개정되는 문서는 **낡은 근거로 확신 있게
답하는 것**이 가장 위험한 실패다.

`RetrieverPort`를 감싸는 데코레이터로 구현한다(`RerankedRetriever`와 같은 패턴). 그래서
FAISS·pgvector·Hybrid·Graph 어떤 백엔드에도 그대로 씌울 수 있고 유스케이스는 무수정이다.

**무폴백 설계**:
- 매니페스트에 없는 출처를 만나면 "최신인 것으로 간주"하지 않는다 → `ConfigError`.
  (모르는 것을 괜찮은 것으로 처리하는 게 바로 폴백이다.)
- 만료 근거를 발견하면 기본 동작은 **명시적 실패**(`mode="error"`).
- 걸러내고 계속하려면(`mode="filter"`) **감사 콜백을 반드시 넘겨야 한다.** 감지하고도
  아무 신호를 남기지 않는 자동복구는 그 자체가 폴백이다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from app.application.ports import Evidence, RetrieverPort
from app.core.errors import ConfigError, InfraError, ValidationErr

MODE_ERROR = "error"
MODE_FILTER = "filter"
_MODES = (MODE_ERROR, MODE_FILTER)

#: 매니페스트 파일명. `_` 접두라 build_index의 `*.txt`/`*.pdf` 색인 대상에 걸리지 않는다.
MANIFEST_NAME = "_freshness.json"


def load_manifest(path: Path) -> dict[str, dict]:
    """신선도 매니페스트를 읽는다. 파일이 없으면 ConfigError(조용히 빈 값으로 가지 않는다)."""
    import json

    if not path.is_file():
        raise ConfigError(
            f"신선도 매니페스트가 없습니다: {path}\n"
            "문서마다 valid_from·review_by·source_url·collected_at 을 정의해야 합니다."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"매니페스트 형식이 올바르지 않습니다(최상위가 객체가 아님): {path}")
    return data


def _parse_day(value: str, field: str, source: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'{source}'의 {field} 날짜 형식이 잘못됐습니다: {value!r}") from exc


class FreshnessGatedRetriever:
    """검색 결과에서 **만료된 근거**를 걸러내거나 명시적으로 실패시킨다.

    `review_by`가 기준일보다 이전이면 만료로 본다. `valid_from`이 기준일보다 미래인 문서
    (아직 시행되지 않은 개정본)도 만료와 같게 취급한다 — 둘 다 "지금 인용하면 안 되는 근거"다.
    """

    def __init__(
        self,
        inner: RetrieverPort,
        manifest: dict[str, dict],
        *,
        today: date | None = None,
        mode: str = MODE_ERROR,
        on_expired: Callable[[list[tuple[str, str]]], None] | None = None,
    ) -> None:
        if mode not in _MODES:
            raise ValidationErr(f"알 수 없는 mode입니다: {mode!r} (허용: {list(_MODES)})")
        if mode == MODE_FILTER and on_expired is None:
            # 감지하고도 신호를 남기지 않으면 폴백이다(사용자 지적으로 확립된 원칙).
            raise ValidationErr(
                "mode='filter'로 만료 근거를 걸러내려면 on_expired 감사 콜백이 필요합니다."
            )
        self._inner = inner
        self._manifest = manifest
        self._today = today or date.today()
        self._mode = mode
        self._on_expired = on_expired

    def _reason_if_unusable(self, source: str) -> str | None:
        """지금 인용할 수 없는 근거면 사유를, 쓸 수 있으면 None을 반환."""
        meta = self._manifest.get(source)
        if meta is None:
            # 모르는 문서를 "최신"으로 간주하지 않는다.
            raise ConfigError(
                f"'{source}'가 신선도 매니페스트에 없습니다. valid_from·review_by를 등록하세요."
            )
        review_by = _parse_day(meta.get("review_by"), "review_by", source)
        if review_by < self._today:
            return f"검토기한 경과(review_by={review_by.isoformat()})"
        valid_from_raw = meta.get("valid_from")
        if valid_from_raw:
            valid_from = _parse_day(valid_from_raw, "valid_from", source)
            if valid_from > self._today:
                return f"아직 시행되지 않음(valid_from={valid_from.isoformat()})"
        return None

    def search(
        self, query: str, k: int | None = None, source: str | None = None
    ) -> list[Evidence]:
        found = self._inner.search(query, k=k, source=source)
        usable: list[Evidence] = []
        unusable: list[tuple[str, str]] = []
        for ev in found:
            reason = self._reason_if_unusable(ev.source)
            if reason is None:
                usable.append(ev)
            else:
                unusable.append((ev.source, reason))

        if unusable:
            if self._mode == MODE_ERROR:
                detail = ", ".join(f"{s}({r})" for s, r in unusable)
                raise InfraError(f"인용할 수 없는 근거가 검색됐습니다: {detail}")
            # filter 모드 — 걸러내되 반드시 감사 신호를 남긴다.
            self._on_expired(unusable)  # type: ignore[misc]  (생성자에서 None 아님을 보장)
        return usable
