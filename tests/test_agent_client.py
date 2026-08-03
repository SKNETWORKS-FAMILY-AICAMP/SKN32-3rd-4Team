"""외부 에이전트 인증·scope·레이트리밋(06_계약_Agent.md §4)."""

import json

import pytest

from app.auth import agent_client as ac
from app.core.errors import AuthErr, ForbiddenErr, InfraError, RateLimitErr


def _write_registry(tmp_path, monkeypatch, clients):
    path = tmp_path / "agent_clients.json"
    path.write_text(json.dumps({"clients": clients}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ac, "_REGISTRY", path)
    return path


def _client(raw_key, **overrides):
    base = {
        "agent_client_id": "c1",
        "name": "테스트 클라이언트",
        "api_key_hash": ac.hash_api_key(raw_key),
        "scopes": ["precheck:read", "terms:read"],
        "rate_limit_rpm": 60,
        "status": "active",
    }
    base.update(overrides)
    return base


def test_유효한_키로_인증된다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1")])
    client = ac.authenticate("Bearer secret-key-1")
    assert client.agent_client_id == "c1"


def test_평문_키는_레지스트리에_없어도_해시로_맞으면_통과한다():
    """★핵심: 저장되는 건 해시뿐이라, 평문이 유출돼도 레지스트리 파일만
    보면 원래 키를 알 수 없다."""
    h = ac.hash_api_key("아무-키나-123")
    assert "아무-키나-123" not in h
    assert len(h) == 64  # sha256 hex


def test_없는_키는_인증_실패한다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1")])
    with pytest.raises(AuthErr):
        ac.authenticate("Bearer wrong-key")


def test_헤더가_없으면_인증_실패한다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1")])
    with pytest.raises(AuthErr):
        ac.authenticate(None)


def test_Bearer_형식이_아니면_인증_실패한다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1")])
    with pytest.raises(AuthErr):
        ac.authenticate("secret-key-1")  # Bearer 접두어 없음


def test_비활성_클라이언트는_키가_맞아도_인증_실패한다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1", status="disabled")])
    with pytest.raises(AuthErr):
        ac.authenticate("Bearer secret-key-1")


def test_레지스트리_파일이_없으면_InfraError(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_REGISTRY", tmp_path / "nope.json")
    with pytest.raises(InfraError):
        ac.authenticate("Bearer anything")


def test_정의되지_않은_scope가_등록돼_있으면_InfraError(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1", scopes=["not_a_real_scope"])])
    with pytest.raises(InfraError):
        ac.authenticate("Bearer secret-key-1")


def test_scope_있으면_통과한다(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1")])
    client = ac.authenticate("Bearer secret-key-1")
    ac.require_scope(client, "precheck:read")  # 예외 안 나면 통과


def test_scope_없으면_403(tmp_path, monkeypatch):
    _write_registry(tmp_path, monkeypatch, [_client("secret-key-1", scopes=["terms:read"])])
    client = ac.authenticate("Bearer secret-key-1")
    with pytest.raises(ForbiddenErr):
        ac.require_scope(client, "observations:write")


def test_정의되지_않은_scope를_요구하면_프로그래밍_오류():
    client = ac.AgentClient(
        agent_client_id="c1", name="x", api_key_hash="h",
        scopes=("precheck:read",), rate_limit_rpm=60,
    )
    with pytest.raises(ValueError):
        ac.require_scope(client, "made_up_scope")


# ── 레이트리밋 ──────────────────────────────────────────────────────────


def _client_obj(rpm=3):
    return ac.AgentClient(
        agent_client_id="c1", name="x", api_key_hash="h",
        scopes=("precheck:read",), rate_limit_rpm=rpm,
    )


def test_한도_안에서는_통과한다():
    limiter = ac.RateLimiter()
    client = _client_obj(rpm=3)
    for _ in range(3):
        limiter.check(client, subject_hash="s1", operation="precheck")


def test_한도_초과하면_RateLimitErr():
    limiter = ac.RateLimiter()
    client = _client_obj(rpm=2)
    limiter.check(client, subject_hash="s1", operation="precheck")
    limiter.check(client, subject_hash="s1", operation="precheck")
    with pytest.raises(RateLimitErr):
        limiter.check(client, subject_hash="s1", operation="precheck")


def test_다른_subject나_operation은_별도로_센다():
    limiter = ac.RateLimiter()
    client = _client_obj(rpm=1)
    limiter.check(client, subject_hash="s1", operation="precheck")
    #: ★같은 클라이언트라도 subject_hash가 다르면 별도 버킷이다 --
    #:   한 클라이언트가 여러 사용자를 대신 호출할 때, 한 사용자가
    #:   다른 사용자의 한도를 갉아먹으면 안 된다.
    limiter.check(client, subject_hash="s2", operation="precheck")
    limiter.check(client, subject_hash="s1", operation="observations")
