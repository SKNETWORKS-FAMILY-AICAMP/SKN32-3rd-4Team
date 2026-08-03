"""s6 재선정 실행 — bench_embedders 를 그대로 쓰되 경로만 s6 로 격리한다.

    python -m scripts.eval.bench_s6 --model dragonkue/snowflake-arctic-embed-l-v2.0-ko
    python -m scripts.eval.bench_s6 --report --md
    python -m scripts.eval.bench_s6 --compare Snowflake/snowflake-arctic-embed-l-v2.0 --task title

★원본 bench_embedders.py 를 건드리지 않는다(동결 v1 보호 + 다른 세션 충돌 회피).
  평가셋 embed_bench_s6.json, 결과 embed_bench_results_s6/ 로만 읽고 쓴다.
  bench_embedders 의 모든 인자(--model/--report/--compare/--task/--dtype 등)가 그대로 통한다.
"""
from scripts.eval import bench_embedders as B

B._SET = B._ROOT / "data" / "eval" / "embed_bench_s6.json"
B._OUT = B._ROOT / "data" / "eval" / "embed_bench_results_s6"

if __name__ == "__main__":
    raise SystemExit(B.main())