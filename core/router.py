"""질문 → 기능 라우팅. 규칙 기반 1차 (빠르고 결정적, 로깅 용이).
분류 결과는 기능6 대시보드의 로그 소스가 된다."""
import re

# 우선순위 순서대로 검사 (위가 먼저)
ROUTES = [
    # 기능5: 용어 질문 ("~란?", "~가 무슨 말" 등 — FEATURE5 이월 항목의 보강판)
    ("terms", re.compile(
        r"(이?란\??$|의 정의|뭐야|무슨 뜻|무슨 말|용어|설명해\s*줘?\s*$)")),
    # 기능2: 승인율/통계
    ("stats", re.compile(r"(승인율|승인 ?현황|지급 ?통계|몇 ?건|미지급)")),
    # 기능3: 유사 케이스
    ("similar", re.compile(r"(비슷한|유사한?|다른 사람|사례)")),
    # 기능4: 질병코드
    ("disease_code", re.compile(r"(질병 ?코드|코드가 뭐|코드 ?알려|kcd)", re.I)),
    # 기능1: 보장 판별 (약관 RAG) — 보장/보상/공제/한도 등
    ("coverage", re.compile(r"(보장|보상|공제|한도|면책|청구|보험금|약관)")),
]

DEFAULT = "coverage"    # 미분류 시 약관 RAG로 (가장 범용적 안전 기본값)


def route(question: str) -> str:
    q = question.strip()
    for name, pat in ROUTES:
        if pat.search(q):
            return name
    return DEFAULT


if __name__ == "__main__":
    tests = [
        ("기왕증이란?", "terms"),
        ("30대 우울증 승인율 어때?", "stats"),
        ("나랑 비슷한 사례 있어?", "similar"),
        ("당뇨병 질병코드 알려줘", "disease_code"),
        ("통원 공제금액 얼마야?", "coverage"),
        ("안녕하세요", "coverage"),
    ]
    for q, want in tests:
        got = route(q)
        print(f"[{'O' if got == want else 'X'}] {q!r} -> {got} (기대 {want})")