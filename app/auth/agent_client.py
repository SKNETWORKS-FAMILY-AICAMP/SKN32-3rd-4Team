"""외부 에이전트 클라이언트 인증·scope·레이트리밋.

계약(06_계약_Agent.md §4):
    · 등록 — agent_client(이름·API 키 해시·scope·레이트리밋)
    · 인증 — `Authorization: Bearer <key>`. 키는 해시로 저장(평문 금지)
    · scope — `precheck:read` `terms:read` `observations:write` `cohort:read`
    · 레이트리밋 — `client_id + subject_hash + operation` 기준
    · 감사 — client, trace_id, verdict, latency 기록. 원문 대신 해시

이 모듈은 **data_subject(고객)를 식별하지 않는다** — 누가 호출했는지(인증
주체)만 다룬다. 데이터 주체 식별은 다른 계층(백엔드)의 일이다.

★DB 적재 전까지는 파일(JSON)로 대신한다. 이 레포의 다른 어댑터(예:
manifest_policy_resolver)와 같은 원칙 — 설정이 없으면 아무거나 고르지 않고
실패한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import AuthErr, ForbiddenErr, InfraError, RateLimitErr

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "config" / "agent_clients.json"

#: ★계약이 정한 scope 넷. 여기 없는 값을 요구하면 프로그래밍 오류다
#:   (클라이언트 잘못이 아니라 우리 코드가 존재하지 않는 권한을 검사한 것).
VALID_SCOPES = frozenset({"precheck:read", "terms:read", "observations:write", "cohort:read"})

#: ★인증 실패 사유를 자세히 알려주지 않는다 — "키가 존재하는지"까지 유출하면
#:   무차별 대입으로 유효한 키를 가려낼 실마리를 준다. 이유가 뭐든 같은 메시지.
_AUTH_FAIL_MESSAGE = "인증에 실패했습니다."


def hash_api_key(raw_key: str) -> str:
    """API 키를 저장/비교용으로 해시한다. 평문은 여기 말고는 남지 않는다."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentClient:
    """인증된 외부 에이전트 클라이언트 하나.

    ★`data_subject`(고객)와 다른 개념이다 — 이건 "누가 우리를 불렀나"이고,
      데이터 주체는 "누구의 데이터인가"다. 섞으면 삭제권 처리 등에서
      인증 주체를 지웠는데 그 데이터가 사라지는 사고가 난다.
    """

    agent_client_id: str
    name: str
    api_key_hash: str
    scopes: tuple[str, ...]
    rate_limit_rpm: int
    status: str = "active"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _load_registry() -> list[AgentClient]:
    """레지스트리 전체. 없거나 깨졌으면 **폴백하지 않고** InfraError.

    ★자동으로 아무 클라이언트나 허용하지 않는다 — 레지스트리가 없으면
      그 자체로 서비스 미준비 상태다.
    """
    if not _REGISTRY.exists():
        raise InfraError(f"에이전트 클라이언트 레지스트리가 없습니다: {_REGISTRY}")
    try:
        raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InfraError(f"에이전트 클라이언트 레지스트리를 읽을 수 없습니다: {e}") from e

    out: list[AgentClient] = []
    for r in raw.get("clients", []):
        scopes = tuple(r.get("scopes", ()))
        unknown = [s for s in scopes if s not in VALID_SCOPES]
        if unknown:
            raise InfraError(
                f"클라이언트 '{r.get('agent_client_id')}'에 정의되지 않은 scope: {unknown}"
            )
        out.append(
            AgentClient(
                agent_client_id=r["agent_client_id"],
                name=r.get("name", ""),
                api_key_hash=r["api_key_hash"],
                scopes=scopes,
                rate_limit_rpm=int(r.get("rate_limit_rpm", 60)),
                status=r.get("status", "active"),
            )
        )
    return out


def authenticate(authorization_header: str | None) -> AgentClient:
    """`Authorization: Bearer <key>` 헤더로 클라이언트를 확인한다.

    ★해시로만 비교한다 — 평문 키가 이 함수 밖으로 나가지 않는다.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthErr(_AUTH_FAIL_MESSAGE)
    raw_key = authorization_header[len("Bearer "):].strip()
    if not raw_key:
        raise AuthErr(_AUTH_FAIL_MESSAGE)

    key_hash = hash_api_key(raw_key)
    for client in _load_registry():
        #: ★`==`가 아니라 상수시간 비교. 문자열 `==`는 앞에서부터 다른 글자가
        #:   나오는 순간 바로 끝나서, 반복 호출 시 걸리는 시간 차이로 해시를
        #:   한 글자씩 추정하는 타이밍 공격의 여지가 이론상 있다.
        if hmac.compare_digest(client.api_key_hash, key_hash):
            if not client.is_active:
                raise AuthErr(_AUTH_FAIL_MESSAGE)
            return client
    raise AuthErr(_AUTH_FAIL_MESSAGE)


def require_scope(client: AgentClient, scope: str) -> None:
    """`client`가 `scope`를 갖고 있는지 강제한다. 없으면 403."""
    if scope not in VALID_SCOPES:
        #: ★이건 클라이언트 잘못이 아니라 호출부(우리 코드)가 존재하지 않는
        #:   scope를 검사한 것이다 — 조용히 통과시키면 안 되는 프로그래밍 오류.
        raise ValueError(f"정의되지 않은 scope: {scope!r}")
    if not client.has_scope(scope):
        raise ForbiddenErr(f"이 작업에 필요한 권한이 없습니다: {scope}")


@dataclass
class RateLimiter:
    """`client_id + subject_hash + operation` 기준 분당 요청 제한.

    ★메모리 기반이다(단일 프로세스 전제). 워커를 여러 개로 늘리면
      프로세스마다 따로 세게 되어 실제 한도보다 더 많이 통과될 수 있다 —
      그 시점엔 공유 저장소(Redis 등)로 바꿔야 한다. 지금은 시연 규모라
      정직하게 이 한계를 문서로 남긴다.
    """

    _window_seconds: float = 60.0
    _hits: dict[tuple[str, str, str], list[float]] = field(default_factory=dict)

    def check(self, client: AgentClient, subject_hash: str, operation: str) -> None:
        """한도를 넘었으면 `RateLimitErr`. 넘지 않았으면 이번 호출을 기록한다."""
        key = (client.agent_client_id, subject_hash, operation)
        now = time.monotonic()
        cutoff = now - self._window_seconds
        recent = [t for t in self._hits.get(key, []) if t > cutoff]
        if len(recent) >= client.rate_limit_rpm:
            raise RateLimitErr(
                f"요청 한도를 초과했습니다 (분당 {client.rate_limit_rpm}회)."
            )
        recent.append(now)
        self._hits[key] = recent


#: ★프로세스 전역 인스턴스 하나. 요청마다 새로 만들면 한도가 의미 없어진다.
rate_limiter = RateLimiter()
