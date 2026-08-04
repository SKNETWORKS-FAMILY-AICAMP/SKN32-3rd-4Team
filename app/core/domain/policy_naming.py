"""약관 상품명 판별 규칙.

이 모듈은 **프레임워크도 바깥 계층도 모른다**(클린아키텍처 2단계 안쪽).
정규식만 쓴다.

★왜 따로 뺐나

    "이 상품명이 특약인가"는 **도메인 지식**이지 파일 읽기가 아니다.
    어댑터에 두면 다른 어댑터(DB 적재본)에서 같은 규칙을 또 쓰게 되고,
    그러면 두 곳이 갈라진다.
"""

from __future__ import annotations

import re

#: 특별약관·특약 — 본계약에 붙는 것이지 그 자체가 "가입 상품"이 아니다.
#:
#: ★본약관과 같은 자리에서 경쟁시키면 안 된다.
#:   "삼성화재 2019-05-01 가입" 을 물었더니 후보에
#:   `[갱신형] 무배당 실손의료비 특별약관` 이 본약관과 나란히 올라와
#:   `ambiguous_product` 로 되물었다.
_RIDER = re.compile(r"특별약관|특약|할인|중지\s*및\s*재개|계약전환|제도성")


def looks_like_rider(product_name: str) -> bool:
    """특별약관(부가 특약)인가."""
    return bool(_RIDER.search(product_name or ""))


def normalize(name: str) -> str:
    """비교용 정규화. 공백·구분기호 차이를 흡수한다."""
    return re.sub(r"[\s·∙・()（）\[\]]+", "", name or "")
