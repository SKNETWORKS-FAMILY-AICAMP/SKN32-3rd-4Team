"""
nodes/mcp_caller.py

역할:
    state["intent"]에 따라 알맞은 MCP 도구(mcp_tools/*)를 호출하는 공통 노드.
    타임아웃과 실패 처리를 여기서 담당한다.

무폴백 원칙:
    - 도구 호출이 타임아웃/예외로 실패하거나, 정상 응답이지만 내용이 비어 있으면
      (또는 claim_stats처럼 아직 실데이터 연동 전 목업 응답이면) "근거 없음"으로 취급한다.
    - 요청된 intent 중 단 하나도 실제 근거를 못 찾으면 needs_fallback=True로 표시해서
      knowledge_gap 노드로 보낸다. 여기서 억지로 답을 만들어내지 않는다.

주의 (사람이 검토해야 하는 부분):
    - disease_lookup/glossary는 사용자 질문에서 "질병명"/"용어"만 뽑아내는 전처리가
      아직 없어서, 지금은 user_query 원문을 그대로 넘긴다. 실제 질병명/용어 추출
      로직(NER 등)이 붙기 전까지는 disease_code_server, glossary_server가 항상
      빈 결과를 반환하는 것과 맞물려 있는 임시 동작이다.
    - 질병명 하나에 코드가 여러 개 매칭되면(예: "우울증" -> F32, F33 ...) 임의로
      하나를 고르지 않고 disease_candidates에 후보를 그대로 담아둔다. 여기서 하나를
      잘못 확정하면 보장 여부 판단 자체가 틀어질 수 있기 때문.
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from graph.state import InsuranceState
from graph.privacy import hash_code
from config import MCP_TIMEOUT_SECONDS

from mcp_tools.policy_rag_server import search_policy_clause
from mcp_tools.disease_code_server import lookup_disease_code
from mcp_tools.claim_stats_server import get_approval_stats, search_similar_cases
from mcp_tools.glossary_server import search_glossary

# 네트워크/일시 오류로 볼 수 있는 예외만 재시도한다.
# ValueError, TypeError 같은 "잘못 호출한" 오류는 재시도해봐야 결과가 같으므로 바로 전파한다.
_TRANSIENT_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)

# disease_lookup이 claim_stats/similar_case보다 먼저 실행돼야
# 방금 찾은 disease_code를 뒤 intent들이 이어 받아 쓸 수 있다.
_INTENT_ORDER = ["disease_lookup", "policy_rag", "claim_stats", "similar_case", "glossary"]


def _call_with_timeout(func, *args, **kwargs):
    """
    호출마다 새 1-worker executor를 쓴다 (공유 풀을 쓰지 않는다).

    ★예전엔 모듈 전역에 max_workers=4짜리 공유 풀을 두고 거기서 꺼내 썼는데,
      타임아웃이 나도 실제 스레드는 안 멈춘다(파이썬은 스레드를 강제 종료할
      방법이 없음). 외부 API가 4번만 연속으로 응답 없이 멈추면 스레드 4개가
      전부 좀비 상태로 잠기고, 그 뒤로는 이 프로세스의 모든 사용자·모든 요청이
      빈 스레드를 못 구해 매번 타임아웃만 나는 상태가 된다(서버는 안 죽고
      계속 느려터진 채로 사실상 먹통).
      호출마다 독립된 executor를 쓰면, 스레드 하나가 영영 안 멈춰도 "그 호출
      전용"으로 격리돼 있어서 다른 호출들을 막지 않는다. shutdown(wait=False)로
      멈추지 않는 스레드를 기다리지 않고 바로 손을 뗀다.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    try:
        result = future.result(timeout=MCP_TIMEOUT_SECONDS)
        executor.shutdown(wait=False)
        return result
    except FutureTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(
            f"MCP 호출 타임아웃 ({MCP_TIMEOUT_SECONDS}초 초과): {func.__name__}"
        )


def _call_tool(func, *args, retries: int = 1, **kwargs):
    attempt = 0
    while True:
        try:
            return _call_with_timeout(func, *args, **kwargs)
        except _TRANSIENT_EXCEPTIONS:
            if attempt >= retries:
                raise
            attempt += 1


def mcp_caller_node(state: InsuranceState) -> InsuranceState:
    """
    state["intent"] 리스트를 순회하며 각 기능에 맞는 MCP 도구를 호출.
    intent 하나가 실패해도 나머지 intent는 계속 시도한다 (한 도구 오류가
    관계없는 다른 도구 호출까지 막아버리면 안 되므로).
    """
    intents = set(state.get("intent", []))
    updated_state = dict(state)
    errors: list[str] = []
    found_any_result = False

    for intent in _INTENT_ORDER:
        if intent not in intents:
            continue

        try:
            if intent == "policy_rag":
                # disease_lookup이 같은 호출에서 먼저 실행돼 disease_name을 찾아줬다면
                # (_INTENT_ORDER 순서 덕분에 가능) 검색어에 반영해서 관련 조항을
                # 더 정확히 찾도록 한다. 안 그러면 질병코드를 찾아놓고도 약관
                # 검색은 원문 질문만 갖고 따로 놀게 된다.
                search_query = state["user_query"]
                resolved_name = updated_state.get("disease_name")
                if resolved_name:
                    search_query = f"{search_query} {resolved_name}"

                clauses = _call_tool(
                    search_policy_clause,
                    search_query,
                    generation=state.get("generation"),
                )
                updated_state["matched_clauses"] = clauses
                found_any_result = found_any_result or bool(clauses)

            elif intent == "disease_lookup":
                # TODO: 질병명 전처리(추출) 붙기 전까지는 원문 질문을 그대로 넘김
                query_term = state.get("disease_name") or state["user_query"]
                candidates = _call_tool(lookup_disease_code, query_term)

                if len(candidates) == 1:
                    code = candidates[0].get("code")
                    updated_state["disease_code"] = code
                    updated_state["disease_name"] = candidates[0].get("name")
                    # 질병기호는 민감정보 -- 로그/트레이스에는 평문 대신 이 해시를
                    # 참조하게 한다. disease_code 자체는 실제 도구 호출(claim_stats
                    # 등)에 필요해서 그대로 둔다 (그래프B의 GraphState와 같은 원리).
                    if code:
                        updated_state["disease_code_hash"] = hash_code(code)
                elif len(candidates) > 1:
                    updated_state["disease_candidates"] = candidates
                found_any_result = found_any_result or bool(candidates)

            elif intent == "claim_stats":
                stats = _call_tool(
                    get_approval_stats,
                    disease_code=updated_state.get("disease_code"),
                )
                updated_state["approval_stats"] = stats
                # _mock=True면 아직 실데이터 연동 전이므로 "근거"로 세지 않는다
                found_any_result = found_any_result or (
                    bool(stats) and not stats.get("_mock")
                )

            elif intent == "similar_case":
                cases = _call_tool(
                    search_similar_cases,
                    disease_code=updated_state.get("disease_code"),
                    age_group=state.get("user_age_group"),
                )
                updated_state["similar_cases"] = cases
                found_any_result = found_any_result or bool(cases)

            elif intent == "glossary":
                # TODO: 용어 추출 전처리 붙기 전까지는 원문 질문을 그대로 넘김
                term = state["user_query"]
                result = _call_tool(search_glossary, term)
                updated_state["glossary_terms"] = [result] if result else []
                found_any_result = found_any_result or bool(result)

        except Exception as e:
            errors.append(f"{intent}: {e}")

    # policy_rag가 요청됐으면 약관 조항이 반드시 있어야 한다 -- 보장판단의
    # 유일한 근거이기 때문에, disease_lookup 등 다른 intent가 성공했다고 해서
    # 대신할 수 없다. (한 intent만 성공해도 통과되던 버그 수정)
    if "policy_rag" in intents:
        has_required_evidence = bool(updated_state.get("matched_clauses"))
    else:
        has_required_evidence = found_any_result

    if not has_required_evidence:
        updated_state["needs_fallback"] = True
        updated_state["error"] = (
            "; ".join(errors) if errors else "요청한 정보에 대한 근거를 찾지 못했습니다."
        )
    else:
        updated_state["needs_fallback"] = False
        if errors:
            # 일부만 실패한 경우 -- 전체를 폴백시키진 않지만 사유는 남겨둔다
            updated_state["error"] = "; ".join(errors)

    return updated_state