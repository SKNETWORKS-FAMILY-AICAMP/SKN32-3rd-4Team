"""기능 2·3·4의 mock 툴. 실구현 시 내부만 DB 조회로 교체 (인터페이스 유지)"""
from langchain_core.tools import tool

DISEASE_DB = {
    "우울증": [{"code": "F32", "name": "우울에피소드"},
             {"code": "F33", "name": "재발성 우울장애"}],
    "당뇨병": [{"code": "E10", "name": "1형 당뇨병"},
             {"code": "E11", "name": "2형 당뇨병"}],
    "고혈압": [{"code": "I10", "name": "본태성(원발성) 고혈압"}],
    "위염": [{"code": "K29", "name": "위염 및 십이지장염"}],
    "비만": [{"code": "E66", "name": "비만"}],
}

APPROVAL_STATS = {
    ("F32", "20대"): {"approved": 15, "total": 20},
    ("F32", "30대"): {"approved": 33, "total": 40},
    ("E11", "40대"): {"approved": 28, "total": 30},
    ("I10", "50대"): {"approved": 12, "total": 18},
    ("E66", "30대"): {"approved": 3, "total": 15},
}


@tool
def search_disease_code(disease_name: str) -> str:
    """질병명(한글)을 받아 KCD 질병코드 목록을 반환한다. 예: '우울증' -> F32, F33"""
    r = DISEASE_DB.get(disease_name.strip())
    if not r:
        return f"'{disease_name}' 코드를 찾을 수 없습니다."
    return "; ".join(f"{x['code']} ({x['name']})" for x in r)


@tool
def get_approval_stats(disease_code: str, age_group: str) -> str:
    """질병코드와 연령대(예: '30대')로 청구 승인 통계를 반환한다."""
    s = APPROVAL_STATS.get((disease_code.strip().upper(), age_group.strip()))
    if not s:
        return f"{disease_code}/{age_group} 통계 없음"
    a, t = s["approved"], s["total"]
    return f"승인 {a}건 / 전체 {t}건 (승인율 {a/t:.0%}, 미지급 {t-a}건)"


@tool
def search_similar_cases(disease_code: str, age_group: str, insurer: str = "") -> str:
    """유사 케이스 조회: 같은 질병코드·연령대의 기지급 사례 요약을 반환한다."""
    return f"[mock] {disease_code}/{age_group}/{insurer or '전체'} 유사 케이스 요약"


ALL_TOOLS = [search_disease_code, get_approval_stats, search_similar_cases]