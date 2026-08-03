"""Composition root — 어댑터를 유스케이스에 조립·주입한다.

★이 파일은 Agent 담당 범위(사전판정)만 남긴 버전이다. 원본(`app/composition.py`,
  feature-frontend)에는 RAG 질문·코호트·용어설명·챗커머스·바운티 조립도 있지만,
  그건 다른 역할(AI1/AI2 다른 유스케이스) 담당이라 이 브랜치에는 안 가져왔다.
  나중에 정본과 합칠 때는 이 파일 전체를 덮어쓰지 말고 `build_precheck` 부분만
  대조해야 한다.
"""

from __future__ import annotations

import os

from app.core.errors import ConfigError

#: 조항을 어디서 읽을 것인가. 이 브랜치(Agent 담당 범위)는 `file`만 지원한다.
#:
#: ★원본(feature-frontend)의 composition.py는 `pg`(인덱스 A) 구현도 고를 수
#:   있지만, 그 어댑터(app/adapters/pg_clause_store.py)는 다른 역할(AI1/AI2)
#:   담당이라 이 브랜치엔 없다. 예전엔 여기서도 `CLAUSE_STORE=pg`를 시도하는
#:   분기가 그대로 남아 있었는데, 그러면 다듬어지지 않은 raw ImportError가
#:   그대로 터졌다 -- "설정 문제는 ConfigError/InfraError로 명시적으로
#:   실패시킨다"는 이 프로젝트 전체 원칙과 어긋난다. 병합 후 정본에서는
#:   원래 분기를 대조해서 되살려야 한다.
_CLAUSE_STORE = os.getenv("CLAUSE_STORE", "file").strip().lower()


def build_precheck():
    """보장 사전판정에 쓸 어댑터 묶음.

    ★구체 구현을 고르는 것은 **조립 지점의 일**이다.
      라우터가 어댑터를 직접 import 하면 "어느 저장소를 쓰는가"가
      HTTP 계층에 흩어진다.

    ★이 브랜치는 `file`(추출 산출물, `data/structured/…`)만 지원한다.
      다른 값이 오면(`pg` 포함) 명시적으로 실패한다 -- 조용히 아무 저장소나
      골라 쓰지 않는다.
    """
    if _CLAUSE_STORE != "file":
        raise ConfigError(
            f"이 브랜치(Agent 범위)는 CLAUSE_STORE='file'만 지원합니다"
            f"(받은 값: {_CLAUSE_STORE!r}). pg_clause_store는 다른 역할 "
            "담당이라 이 브랜치에 없습니다."
        )

    from app.adapters import file_clause_store, manifest_policy_resolver

    return {"policies": manifest_policy_resolver, "clauses": file_clause_store}
