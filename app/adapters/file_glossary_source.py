"""용어 정의 구절 — 파일 색인에서 읽는 어댑터.

색인은 `scripts/extract/build_glossary.py` 가 만든다.

    data/glossary/passages.jsonl   구절 2,739개(조항 1,621 · 붙임 1,118)
    data/glossary/meta.json        무엇으로 언제 만들었나

★색인이 없으면 **없다고 말한다.**

    조용히 빈 결과를 돌려주면 "약관에 그 용어가 없다"로 읽힌다.
    없는 것은 색인이지 용어가 아니다. `InfraError` 로 올려 503 이 되게 한다
    (무폴백 원칙 — CLAUDE.md §0).

★색인 파일은 **약관 원문 조각이다.** 저작물이므로 커밋하지 않는다(`.gitignore`).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.core.errors import InfraError
from app.core.ports.glossary import TermPassage

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "data" / "glossary"
_PASSAGES = _DIR / "passages.jsonl"
_META = _DIR / "meta.json"

_lock = threading.Lock()
_cache: list[TermPassage] | None = None
_meta_cache: dict | None = None


def _load() -> list[TermPassage]:
    """색인 전체를 한 번만 읽어 둔다(16MB · 구절 2,739개).

    ★요청마다 1,367문서를 훑지 않는다. 훑으면 한 번에 수십 초가 걸린다.
    """
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not _PASSAGES.exists():
            raise InfraError(
                "용어 색인이 없습니다: data/glossary/passages.jsonl. "
                "`python -m scripts.extract.build_glossary` 로 만드세요."
            )
        rows: list[TermPassage] = []
        with _PASSAGES.open(encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError as e:
                    #: ★조용히 건너뛰지 않는다. 분모가 줄면 커버리지가 좋아 보인다.
                    raise InfraError(f"용어 색인 {ln}행이 깨졌습니다: {e}") from e
                rows.append(
                    TermPassage(
                        kind=d.get("kind") or "",
                        sha256=d.get("sha256") or "",
                        insurer=d.get("insurer") or "",
                        qualified_no=d.get("qualified_no") or "",
                        section=d.get("section") or "",
                        title=d.get("title") or "",
                        page_from=int(d.get("page_from") or 0),
                        page_to=int(d.get("page_to") or 0),
                        content_hash=d.get("content_hash") or "",
                        text=d.get("text") or "",
                    )
                )
        _cache = rows
        return rows


def find(term: str, *, insurer: str | None = None, limit: int = 20) -> list[TermPassage]:
    """용어가 들어 있는 정의 구절.

    ★부분 문자열로 찾는다. 형태소 분석이나 임베딩을 쓰지 않는다 —
      지금 필요한 것은 "약관에 이 낱말이 정의돼 있나"이고,
      그건 문자열 일치로 충분하며 **틀릴 여지가 없다.**
      의미 검색이 필요해지면 인덱스 A(pgvector)로 간다.

    ★`limit` 에 닿아도 **끝까지 센다.**

        처음엔 `limit` 에서 멈췄더니 `total_passages` 가 항상 200 이 나왔다.
        그건 개수가 아니라 상한인데 응답에는 "구절 200개"로 실렸고,
        `insurers` 도 훑다 만 순서에 따라 2개만 나왔다.
        구절이 2,739개뿐이라 전부 훑어도 문자열 검사 2,739번이다 — 셀 수 있으면 센다.
    """
    t = (term or "").strip()
    if not t:
        return []
    ins = (insurer or "").strip()
    out: list[TermPassage] = []
    for p in _load():
        if ins and p.insurer != ins:
            continue
        if t in p.text:
            out.append(p)
    return out[:limit] if limit and len(out) > limit else out


def meta() -> dict:
    """색인을 무엇으로 언제 만들었나. **응답에 실어 나간다.**"""
    global _meta_cache
    if _meta_cache is None:
        if not _META.exists():
            raise InfraError("용어 색인 메타가 없습니다: data/glossary/meta.json")
        _meta_cache = json.loads(_META.read_text(encoding="utf-8"))
    return _meta_cache


def _reset_for_tests() -> None:
    """테스트에서 색인을 갈아 끼울 때만 쓴다."""
    global _cache, _meta_cache
    _cache = None
    _meta_cache = None


__all__ = ["find", "meta"]
