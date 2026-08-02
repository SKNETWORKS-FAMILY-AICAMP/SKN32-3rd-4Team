"""
graph/extractors.py

역할:
    사용자의 자연어 질문에서 라우팅/검색에 필요한 정보(연령대, 가입년도 -> 세대)를
    정규식으로 뽑아내는 전처리 유틸리티.

    LLM을 안 쓰고 정규식으로 하는 이유: "30대", "2020년에 가입" 같은 표현은
    패턴이 단순해서 굳이 LLM 호출(비용/지연)이 필요 없고, 결과도 결정적이어야
    나중에 디버깅이 가능하다.

주의:
    두 함수 다 애매한 경우(경계 케이스) 임의로 확정하지 않고 None을 반환한다.
    잘못된 값으로 확정하면 "틀린 근거로 답하는" 상황이 되어 무폴백 원칙에 어긋난다.
"""

import datetime
import re

_AGE_PATTERN = re.compile(r"(\d{1,3})\s*(?:대|살|세)")


def extract_age_group(user_query: str) -> str | None:
    """
    "30대", "35살", "35세" 같은 표현에서 나이를 찾아 10살 단위 연령대로 반환.
    10 미만 숫자는 "3대 질환", "2대 보험사" 같은 오탐이 많아 제외한다.

    반환 형식("30대")은 데이터팀의 과거 청구DB 연령대 라벨과 맞춰야 한다 --
    라벨 형식이 다르면(예: "20-29") 이 함수의 return 포맷팅만 바꾸면 된다.
    """
    match = _AGE_PATTERN.search(user_query)
    if not match:
        return None

    age = int(match.group(1))
    if age < 10 or age > 120:
        return None

    bucket = (age // 10) * 10
    return f"{bucket}대"


# 세대 구분 -- 금융위원회 공식 보도자료 기준으로 확인됨:
#   "3세대['17.4월~'21.6월]", "7.1일부터 제4세대 실손의료보험이 출시됩니다"(2021.7.1)
# (https://www.fsc.go.kr/no010101/76157)
# insurance_assistant_design_doc.md(DB팀 설계문서) 4.2절의 계약일시->세대 규칙과도
# 날짜까지 정확히 일치함 (~09.09/09.10~17.03/17.04~21.06/21.07~).
# 1-2세대, 4-5세대 경계는 소비자 매체 정리 기준이라 공식 확인 전이라 상대적으로
# 불확실 -- 그래서 경계에 걸친 연도(2009/2017/2021/2026)는 확정하지 않고 None.
_GENERATION_RANGES = [
    (None, 2008, "1세대"),
    (2010, 2016, "2세대"),
    (2018, 2020, "3세대"),
    (2022, 2025, "4세대"),
    (2027, None, "5세대"),
]

_YEAR_PATTERN = re.compile(r"(\d{2,4})\s*년도?\s*(?:에)?\s*가입")


def extract_generation(user_query: str) -> str | None:
    """
    "2020년에 가입", "20년도 가입" 같은 표현에서 가입년도를 찾아 세대로 변환.

    경계 연도(2009/2017/2021/2026)만 딱 말하고 몇 월인지 안 알려주면 세대를
    특정할 수 없으므로 None을 반환한다 -- 이 경우 호출한 쪽(judge_coverage 등)이
    "몇 월에 가입하셨는지 확인해주세요"라고 되물어야 한다.
    """
    match = _YEAR_PATTERN.search(user_query)
    if not match:
        return None

    year = int(match.group(1))
    if year < 100:
        year += 2000

    if year < 2000 or year > 2035:
        return None

    for start, end, generation in _GENERATION_RANGES:
        if (start is None or year >= start) and (end is None or year <= end):
            return generation

    return None  # 경계 연도(2009/2017/2021/2026) -- 월 정보 없이는 확정 불가


# DB팀 스키마(insurance_product.generation_type)는 세대를 정수 1~4로 저장한다.
# 우리 쪽(state.py, rag/chunking.py 메타데이터)은 "3세대" 같은 문자열을 쓰므로,
# 화면1에서 입력받은 session 데이터를 그래프에 넘길 때 이 변환이 필요하다.
_GENERATION_TYPE_LABELS = {1: "1세대", 2: "2세대", 3: "3세대", 4: "4세대"}


def generation_type_to_label(generation_type: int | None) -> str | None:
    """DB의 정수 generation_type(1~4)을 우리 쪽 문자열 형식("N세대")으로 변환."""
    if generation_type is None:
        return None
    return _GENERATION_TYPE_LABELS.get(generation_type)


# resolve_policy 노드용 -- 정확한 날짜("YYYY-MM-DD")가 있으면 extract_generation()과
# 달리 경계 연도라도 100% 확정 가능하다. 날짜 기준은 금융위 보도자료 근거(graph/router.py 참고).
_GENERATION_DATE_RANGES = [
    (datetime.date.min, datetime.date(2009, 9, 30), "1세대"),
    (datetime.date(2009, 10, 1), datetime.date(2017, 3, 31), "2세대"),
    (datetime.date(2017, 4, 1), datetime.date(2021, 6, 30), "3세대"),
    (datetime.date(2021, 7, 1), datetime.date.max, "4세대"),
]


def resolve_generation_from_date(enrolled_on: str) -> str | None:
    """
    "YYYY-MM-DD" 형식의 가입일시로 세대를 확정한다 (resolve_policy 노드용).

    extract_generation()과 달리 정확한 날짜가 있으므로 경계 케이스가 없다 --
    파싱 자체가 실패하면(형식이 이상하면) None을 반환한다.
    """
    try:
        d = datetime.date.fromisoformat(enrolled_on)
    except (ValueError, TypeError):
        return None

    for start, end, generation in _GENERATION_DATE_RANGES:
        if start <= d <= end:
            return generation
    return None