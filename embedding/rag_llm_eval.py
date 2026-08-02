"""RAG + LLM 평가: 검색된 근거로 답변 생성 -> citation/환각/거부 자동 점검
사용: python rag_llm_eval.py --models gpt-4.1
     python rag_llm_eval.py --models gpt-4.1,qwen3 --questions llm_questions.json"""
import argparse
import csv
import json
import re
import time
from pathlib import Path

from rag_config import search, search_terms, TOP_K

TOP_K = 5
TERM_PAT = re.compile(r"(이?란\??$|뭐야|무슨 뜻|정의)")

SYSTEM = """당신은 실손의료보험 약관 안내 챗봇입니다. 규칙:
1. 반드시 아래 [근거] 청크의 내용만으로 답하세요. 근거에 없는 내용은 절대 추가하지 마세요.
2. 답변 끝에 사용한 근거의 출처를 표기하세요. 형식: (출처: 보험사 세대, citation)
3. 근거로 답할 수 없는 질문이면 "제공된 약관에서 확인할 수 없습니다"라고 답하세요.
4. 보험사마다 내용이 다르면 보험사별로 구분해서 답하세요."""


def build_llm(name):
    if name.startswith("gpt"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=name, temperature=0)
    if name.startswith("qwen"):
        from langchain_ollama import ChatOllama
        return ChatOllama(model="qwen3:8b", temperature=0)
    raise ValueError(name)


INSURERS = ["삼성화재", "DB손해보험", "NH농협생명", "동양생명"]
GEN_PAT = re.compile(r"([1-5])\s*세대")


def retrieve(q):
    if TERM_PAT.search(q):
        return "terms_e5", search_terms(q, k=TOP_K)
    insurer = next((i for i in INSURERS if i in q or i[:2] in q), None)
    m = GEN_PAT.search(q)
    generation = f"{m.group(1)}세대" if m else None
    return "policy_e5", search(q, insurer=insurer, generation=generation, k=TOP_K)

def make_prompt(q, chunks):
    ev = "\n\n".join(
        f"[근거{i}] ({c['insurer']} {c['generation']}, {c['citation']})\n{c['text']}"
        for i, c in enumerate(chunks, 1))
    return f"[근거]\n{ev}\n\n[질문]\n{q}"


def auto_check(qtype, answer, chunks, trap=False):
    """자동 점검: 출처표기 / 거부표현 / (답없음·함정 문항의) 환각 여부"""
    has_cite = bool(re.search(r"출처", answer))
    said_no = any(p in answer for p in
                  ["확인할 수 없", "약관에 없", "명시되지 않", "명시되어 있지 않",
                   "포함되지 않", "확인되지 않", "찾을 수 없"])
    if trap or qtype == "답없음":
        return {"pass": said_no, "note": "거부함" if said_no else "환각 의심(답을 지어냄)"}
    ok = has_cite and not said_no
    note = []
    if not has_cite:
        note.append("출처 미표기")
    if said_no:
        note.append("과잉 거부")
    return {"pass": ok, "note": "; ".join(note) or "ok"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gpt-4.1")
    ap.add_argument("--questions", default="llm_questions.json")
    args = ap.parse_args()

    from langchain_core.messages import HumanMessage, SystemMessage
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    print("검색 모듈 준비 (rag_config)...")
    rows = []

    for name in args.models.split(","):
        name = name.strip()
        print(f"\n===== 모델: {name}")
        llm = build_llm(name)
        for q in questions:
            t0 = time.time()
            coll_used, chunks = retrieve(q["query"])
            resp = llm.invoke([SystemMessage(content=SYSTEM),
                               HumanMessage(content=make_prompt(q["query"], chunks))])
            sec = time.time() - t0
            ans = resp.content if isinstance(resp.content, str) else str(resp.content)
            chk = auto_check(q["type"], ans, chunks, trap=q.get("trap", False))
            mark = "O" if chk["pass"] else "X"
            print(f"  [{mark}] {q['id']} {q['type']:<4} ({coll_used}, {sec:.1f}s) {chk['note']}")
            rows.append({"model": name, "qid": q["id"], "type": q["type"],
                         "coll": coll_used, "auto_pass": int(chk["pass"]),
                         "note": chk["note"], "sec": round(sec, 1),
                         "answer": ans[:500],
                         "expected": q.get("expected_answer", "")})

    out = "out\\llm_eval_results.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장: {out} — answer/expected 컬럼을 사람이 최종 검토하세요.")


if __name__ == "__main__":
    main()