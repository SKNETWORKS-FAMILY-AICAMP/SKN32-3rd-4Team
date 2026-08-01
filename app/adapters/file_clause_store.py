"""확정된 약관 버전의 **조항**을 꺼낸다 (어댑터).

이 모듈은 **파일을 읽는다** — 그래서 `app/adapters/` 에 있다.
도메인 타입은 `app/core/ports/precheck.py` 것을 쓴다.

★검색 범위를 약관 버전으로 **가둔다**

    이게 이 모듈의 존재 이유다. 전체 조항에서 검색하면
    **2019년 가입자에게 2024년 약관 조항**이 근거로 붙는다.
    `policy_version.resolve()` 로 확정한 `sha256` 안에서만 찾는다.

★판정에 쓸 수 없는 것은 내주지 않는다

    · `parse_status != "ok"`      조항 구조화가 실패한 문서다. `page_fallback`
                                  청크는 "제N조"를 댈 수 없으므로 근거가 못 된다.
    · `chunk_type == "page_fallback"`  위와 같은 이유.

    검색(RAG)에는 쓸 수 있어도 **판정 근거로는 못 쓴다.** 둘을 구분해 내준다.

★조 번호만으로는 유일하지 않다

    특별약관이 여러 개면 조 번호가 1부터 다시 시작한다.
    실측: 한 문서에서 `제2조` 가 51번 나왔다(부 구분 실패 시).
    그래서 `qualified_no`(`부/제N조`)를 식별자로 쓰고,
    같은 번호가 여럿이면 **모두 돌려준다** — 하나를 골라 주지 않는다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.core.errors import InfraError
from app.core.ports.precheck import ClauseRow

_ROOT = Path(__file__).resolve().parents[2]
_STRUCTURED = _ROOT / "data" / "structured"

#: 판정 근거로 쓸 수 없는 청크.
_NON_CLAUSE = {"page_fallback"}


def _latest_version_dir() -> str:
    """가장 최근 추출기 버전 폴더 이름(`s3_pymupdf-1.28.0`).

    ★버전을 고정하지 않고 **최신을 고른다.** 산출 경로에 버전이 박혀 있어
      옛 버전이 남아 있는데, 판정은 최신 것으로 해야 한다.
    """
    dirs = {p.name for p in _STRUCTURED.glob("*/s*_*") if p.is_dir()}
    if not dirs:
        raise InfraError(
            f"조항 산출물이 없습니다: {_STRUCTURED}\n"
            "`python -m scripts.extract.run_all` 을 먼저 돌리세요."
        )
    #: `s3_...` > `s2_...` — 스키마 번호로 정렬한다(문자열 정렬이면 s10 이 s2 앞에 온다).
    def key(name: str) -> tuple[int, str]:
        m = re.match(r"^s(\d+)_(.*)$", name)
        return (int(m.group(1)), m.group(2)) if m else (0, name)

    return sorted(dirs, key=key)[-1]


@lru_cache(maxsize=256)
def _load_doc(sha256: str) -> dict:
    """조항 JSON 하나. sha 로 찾는다."""
    tag = _latest_version_dir()
    hits = list(_STRUCTURED.glob(f"*/{tag}/{sha256[:12]}.clauses.json"))
    if not hits:
        raise InfraError(
            f"조항 산출물을 찾지 못했습니다: {sha256[:12]} (추출기 {tag})\n"
            "전처리가 아직 안 돌았거나 판정 대상에서 제외된 문서입니다."
        )
    return json.loads(hits[0].read_text(encoding="utf-8"))


def _to_clause(sha256: str, c: dict, parse_status: str) -> ClauseRow:
    reason = ""
    if parse_status != "ok":
        reason = f"문서 파싱 상태가 '{parse_status}'"
    elif c.get("chunk_type") in _NON_CLAUSE:
        reason = f"조항이 아니라 '{c.get('chunk_type')}' 청크"
    loc = c.get("locator", {})
    return ClauseRow(
        sha256=sha256,
        qualified_no=c.get("qualified_no", ""),
        clause_no=c.get("clause_no", ""),
        section=c.get("section", ""),
        title=c.get("title", ""),
        text=c.get("text", ""),
        page_from=loc.get("page_from", 0),
        page_to=loc.get("page_to", 0),
        content_hash=c.get("content_hash", ""),
        usable=not reason,
        unusable_reason=reason,
    )


def load_clauses(sha256: str, *, usable_only: bool = True) -> list[ClauseRow]:
    """한 약관 버전의 조항 전부.

    Args:
        sha256: `policy_version.resolve()` 가 확정한 문서.
        usable_only: 판정 근거로 쓸 수 있는 것만. `False` 면 전부(검색용).
    """
    doc = _load_doc(sha256)
    status = doc.get("parse_status", "ok")
    out = [_to_clause(sha256, c, status) for c in doc.get("clauses", [])]
    return [c for c in out if c.usable] if usable_only else out


def find_by_number(sha256: str, number: str) -> list[ClauseRow]:
    """조 번호로 찾는다. `"제9조"` 또는 `"보통약관/제9조"`.

    ★같은 번호가 여럿이면 **전부** 돌려준다. 하나를 골라 주지 않는다 —
      특별약관마다 조 번호가 1부터 다시 시작하므로 어느 것인지 우리가 정할 수 없다.
    """
    want = _norm_no(number)
    return [c for c in load_clauses(sha256) if _norm_no(c.qualified_no) == want]


def _norm_no(s: str) -> str:
    """`보통약관/제 9 조` → `제9조`."""
    tail = (s or "").rsplit("/", 1)[-1]
    m = re.search(r"제\s*(\d{1,3})\s*조(?:\s*의\s*(\d{1,2}))?", tail)
    if not m:
        return re.sub(r"\s+", "", tail)
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def search(sha256: str, query: str, *, limit: int = 8) -> list[ClauseRow]:
    """낱말 기준 조항 검색.

    ★임베딩 검색은 아직 없다. 여기서는 **낱말 포함**만 본다.
      이 단계의 목적은 "조항 단위로 근거를 뽑아 낼 수 있는가"를 세우는 것이고,
      의미 검색은 pgvector 색인이 선 뒤에 붙인다.

      ★"검색이 안 되면 판정하지 않는다"가 원칙이므로,
        낱말이 안 걸리면 **빈 목록**을 돌려준다. 비슷한 걸 끌어오지 않는다.
    """
    terms = [t for t in re.split(r"\s+", (query or "").strip()) if len(t) >= 2]
    if not terms:
        return []
    scored: list[tuple[int, ClauseRow]] = []
    for c in load_clauses(sha256):
        body = c.text
        hit = sum(body.count(t) for t in terms)
        if hit:
            #: 제목에 걸리면 가점 — 조항 제목은 그 조항의 주제다.
            hit += sum(3 for t in terms if t in c.title)
            scored.append((hit, c))
    scored.sort(key=lambda x: (-x[0], x[1].page_from))
    return [c for _, c in scored[:limit]]


def stats(sha256: str) -> dict:
    """문서 요약 — 판정 전에 쓸 만한 문서인지 본다."""
    doc = _load_doc(sha256)
    st = doc.get("stats", {})
    total = len(doc.get("clauses", []))
    usable = sum(1 for c in load_clauses(sha256, usable_only=False) if c.usable)
    return {
        "parse_status": doc.get("parse_status", "ok"),
        "numbering": doc.get("numbering", ""),
        "pages": st.get("pages", 0),
        "clauses_total": total,
        "clauses_usable": usable,
        "sections": doc.get("sections", []),
        "extractor": doc.get("extractor", ""),
    }
