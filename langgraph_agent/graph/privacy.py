"""
graph/privacy.py

역할:
    질병기호 같은 민감정보를 상태/로그에 남기기 전에 해시하는 공용 유틸리티.
    precheck_graph.py(그래프B)와 mcp_caller.py(그래프A) 둘 다 이걸 쓴다 --
    해시 로직이 두 곳에 따로 있으면 나중에 한쪽만 바뀌어 어긋나기 쉽다.
"""

import hashlib


def hash_code(code: str) -> str:
    """질병기호 등을 상태에 담기 전에 해시한다. 원문은 입력 객체 안에만 둔다."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()[:16]
