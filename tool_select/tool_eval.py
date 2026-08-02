"""tool calling 평가 (멀티턴): 툴을 실제 실행해 결과를 돌려주며 최대 3턴 진행.
채점 = "여정 중 목표 툴을 올바른 인자로 호출했는가" (도달 기준).
사용: python tool_select\tool_eval.py --models gpt-4.1,gpt-4.1-mini,qwen3
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tools import ALL_TOOLS

from langchain_core.messages import HumanMessage, ToolMessage

TOOL_MAP = {t.name: t for t in ALL_TOOLS}
MAX_TURNS = 3
TURN_TIMEOUT_NOTE = 60   # 초과 시 기록용 (강제 중단은 아님)


def build_llm(name):
    if name.startswith("gpt"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=name, temperature=0, timeout=120)
    if name.startswith("qwen"):
        from langchain_ollama import ChatOllama
        return ChatOllama(model="qwen3:8b", temperature=0)
    raise ValueError(name)


def args_match(expected_args, got_args):
    """기대 인자와 실제 인자 비교. 값이 None이면 존재만 확인."""
    mism = []
    for k, v in (expected_args or {}).items():
        got = str(got_args.get(k, "")).strip()
        if v is None:
            if k not in got_args:
                mism.append(f"{k} 없음")
        elif got != str(v):
            mism.append(f"{k}: 기대'{v}'/실제'{got}'")
    return (not mism), ("; ".join(mism) or "ok")


def run_case(llm_tools, case):
    """멀티턴 실행. 반환: (passed, note, trace, total_sec)"""
    msgs = [HumanMessage(content=case["query"])]
    trace = []          # ["1:search_disease_code(당뇨병)", ...]
    hit = None          # 목표 도달 기록
    wrong_call = None   # 목표 툴을 틀린 인자로 부른 기록
    t0 = time.time()

    for turn in range(1, MAX_TURNS + 1):
        resp = llm_tools.invoke(msgs)
        calls = getattr(resp, "tool_calls", []) or []

        if not calls:                      # 툴 호출 없이 종료 (최종 답변/거부)
            trace.append(f"{turn}:무호출종료")
            break

        msgs.append(resp)
        for call in calls:
            arg_str = ",".join(f"{k}={v}" for k, v in call["args"].items())
            trace.append(f"{turn}:{call['name']}({arg_str})")

            if case["expected_tool"] and call["name"] == case["expected_tool"]:
                ok, note = args_match(case["expected_args"], call["args"])
                if ok and hit is None:
                    hit = turn
                elif not ok and wrong_call is None:
                    wrong_call = note

            # 툴 실제 실행 후 결과를 대화에 반환
            tool_fn = TOOL_MAP.get(call["name"])
            try:
                result = tool_fn.invoke(call["args"]) if tool_fn else "알 수 없는 툴"
            except Exception as e:
                result = f"툴 에러: {e}"
            msgs.append(ToolMessage(content=str(result),
                                    tool_call_id=call.get("id", "")))

        if hit:                            # 목표 도달했으면 더 돌 필요 없음
            break

    total = time.time() - t0

    # ---- 채점 ----
    if case["expected_tool"] is None:
        # 무호출이 정답인 케이스: 목표가 없으므로 "어떤 툴도 안 불렀는가"
        any_call = any(":" in t and "무호출" not in t for t in trace)
        if not any_call:
            return True, "무호출 ok", trace, total
        # t14형 예외: 코드 조회 등 정보수집 후 무호출 종료(되묻기)는 허용
        called_names = {t.split(":")[1].split("(")[0] for t in trace if "(" in t}
        forbidden = {"get_approval_stats", "search_similar_cases"} & called_names
        if not forbidden and trace and trace[-1].endswith("무호출종료"):
            return True, f"정보수집 후 정지 (허용): {'>'.join(trace)}", trace, total
        return False, f"추측 호출: {'>'.join(trace)}", trace, total

    if hit:
        note = f"{hit}턴 도달" + ("" if hit == 1 else f" ({'>'.join(trace)})")
        return True, note, trace, total
    if wrong_call:
        return False, f"인자 오류: {wrong_call} | {'>'.join(trace)}", trace, total
    return False, f"미도달: {'>'.join(trace)}", trace, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-4.1,gpt-4.1-mini,qwen3")
    args = ap.parse_args()

    cases = json.loads((Path(__file__).parent / "tool_cases.json").read_text(encoding="utf-8"))
    rows = []

    for name in [m.strip() for m in args.models.split(",")]:
        print(f"\n===== 모델: {name} (멀티턴, 최대 {MAX_TURNS}턴)")
        try:
            llm_tools = build_llm(name).bind_tools(ALL_TOOLS)
        except Exception as e:
            print(f"  tool binding 실패: {e}")
            continue
        for c in cases:
            try:
                ok, note, trace, sec = run_case(llm_tools, c)
            except Exception as e:
                ok, note, trace, sec = False, f"에러: {e}", [], 0
            mark = "O" if ok else "X"
            slow = " ⚠지연" if sec > TURN_TIMEOUT_NOTE else ""
            print(f"  [{mark}] {c['id']} {c['func']:<4} {sec:6.1f}s{slow}  {note}")
            rows.append({"model": name, "id": c["id"], "func": c["func"],
                         "passed": int(ok), "sec": round(sec, 1),
                         "trace": ">".join(trace), "note": note})

    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "tool_eval_multiturn.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n===== 모델별 통과율 (멀티턴)")
    for name in sorted({r["model"] for r in rows}):
        sub = [r for r in rows if r["model"] == name]
        p = sum(r["passed"] for r in sub)
        print(f"  {name:<14} {p}/{len(sub)}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()