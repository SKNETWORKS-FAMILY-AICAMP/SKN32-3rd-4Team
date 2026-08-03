"""s6 재선정 실행 — bench_embedders 를 그대로 쓰되 경로만 s6 로 격리한다.

    python -m scripts.eval.bench_s6 --model ... --device cuda
    python -m scripts.eval.bench_s6 --report --md

★원본 bench_embedders.py 를 건드리지 않는다(동결 v1 보호 + 다른 세션 충돌 회피).
★2라운드 추가(2026-08-03 밤): 대형 4종 접두어를 **모델카드 확인 후 정정**한다.
  - comsat: prompt_name="query" 필수(카드 명시) → @qwen 메커니즘 사용
  - llama-embed-nemotron-8b: "Instruct: ...\\nQuery: " 리터럴(카드 명시)
  v1 측정(무접두어/query: )은 카드와 달랐다 — §5-1 의 "남은 일"을 여기서 수행.
"""
from scripts.eval import bench_embedders as B

B._SET = B._ROOT / "data" / "eval" / "embed_bench_s6.json"
B._OUT = B._ROOT / "data" / "eval" / "embed_bench_results_s6"

#: (질의 접두어, 문서 접두어) — 카드 원문 기준. 문서는 둘 다 무접두어.
_FIX = {
    "sionic-ai/comsat-embed-ko-8b-preview": ("@qwen", ""),
    "nvidia/llama-embed-nemotron-8b": (
        "Instruct: Given a question, retrieve passages that answer the question\nQuery: ",
        ""),
}
B.CANDIDATES = [
    (m, gb, *_FIX.get(m, (qp, dp)), note)
    for (m, gb, qp, dp, note) in B.CANDIDATES
]

if __name__ == "__main__":
    raise SystemExit(B.main())