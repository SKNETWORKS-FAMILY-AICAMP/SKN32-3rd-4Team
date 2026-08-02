"""멀티턴 툴 실행 루프 (tool_eval.py 검증 패턴의 서비스판).
타임아웃·인자부족 되묻기 내장 — README_FEATURE234 6절 요구사항 반영."""
import time

from langchain_core.messages import HumanMessage, ToolMessage

MAX_TURNS = 3
BUDGET_S = 30       # 전체 처리 시간 예산 (Qwen 장고 방어)

ASK_MORE = "정확한 조회를 위해 추가 정보가 필요합니다. 연령대(예: 30대)와 질병명을 함께 알려주세요."
TIMEOUT_MSG = "처리 시간이 초과되었습니다. 질문을 조금 더 구체적으로 다시 입력해 주세요."


def run_agent(llm, tools, question: str) -> dict:
    """반환: {"answer": str, "trace": [str], "elapsed": float}"""
    tool_map = {t.name: t for t in tools}
    llm_tools = llm.bind_tools(tools)
    msgs = [HumanMessage(content=question)]
    trace = []
    t0 = time.time()

    for turn in range(1, MAX_TURNS + 1):
        if time.time() - t0 > BUDGET_S:
            return {"answer": TIMEOUT_MSG, "trace": trace,
                    "elapsed": time.time() - t0}
        resp = llm_tools.invoke(msgs)
        calls = getattr(resp, "tool_calls", []) or []

        if not calls:
            # 툴 없이 종료: 최종 답변이 있으면 그대로, 비었으면 되묻기
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            answer = text.strip() or ASK_MORE
            return {"answer": answer, "trace": trace,
                    "elapsed": time.time() - t0}

        msgs.append(resp)
        for call in calls:
            trace.append(f"{turn}:{call['name']}({call['args']})")
            fn = tool_map.get(call["name"])
            try:
                result = fn.invoke(call["args"]) if fn else "알 수 없는 도구입니다."
            except Exception as e:
                result = f"도구 실행 오류: {e}"
            msgs.append(ToolMessage(content=str(result),
                                    tool_call_id=call.get("id", "")))

    # 턴 소진: 마지막으로 정리 답변 요청
    msgs.append(HumanMessage(content="지금까지의 도구 결과로 최종 답변을 정리해 주세요."))
    resp = llm_tools.invoke(msgs)
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return {"answer": text.strip() or ASK_MORE, "trace": trace,
            "elapsed": time.time() - t0}