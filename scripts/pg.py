"""userspace PostgreSQL+pgvector 라이프사이클 (Phase 3, Docker 없이).

conda env `pgv`(postgresql 16.14 + pgvector 0.8.3)의 바이너리를 **최소 clean 환경**으로 기동한다.
Windows에서 큰 PATH로 띄우면 쿼리 백엔드가 0xC0000142(DLL init 실패)로 죽으므로, env를 최소화한다.

사용:
    python -m scripts.pg start    # 클러스터 initdb(최초) + 서버 기동(포트 5433)
    python -m scripts.pg stop
    python -m scripts.pg status
    python -m scripts.pg setup     # DB/확장/스키마 생성 + corpus 적재(psycopg, TCP)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_PGDATA = _PROJECT / "data" / "pgdata"
_ENV = Path(os.environ.get("PGV_ENV", r"C:/Users/playdata2/anaconda3/envs/pgv"))
_BIN = _ENV / "Library" / "bin"
_PORT = "5433"
_DBNAME = "mall_vec"


def _clean_env() -> dict:
    """0xC0000142 회피: 최소 PATH만 담은 환경(자식 백엔드 DLL init 정상화)."""
    system32 = r"C:\Windows\System32"
    windows = r"C:\Windows"
    return {
        "SYSTEMROOT": windows,
        "PATH": f"{_BIN};{system32};{windows}",
    }


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=_clean_env(), capture_output=True, text=True)


def cmd_start() -> None:
    if not (_PGDATA / "postgresql.conf").exists():
        _PGDATA.mkdir(parents=True, exist_ok=True)
        r = _run([str(_BIN / "initdb.exe"), "-D", str(_PGDATA), "-U", "postgres",
                  "--auth-local=trust", "--auth-host=trust", "--encoding=UTF8"])
        print("[initdb]", "OK" if r.returncode == 0 else r.stderr[-300:])
    # postgres 를 백그라운드로(detached), 로그는 server.log
    logf = open(_PGDATA / "server.log", "ab")
    subprocess.Popen(
        [str(_BIN / "postgres.exe"), "-D", str(_PGDATA), "-p", _PORT],
        env=_clean_env(), stdout=logf, stderr=logf,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    print(f"[start] postgres 기동 시도(port {_PORT}). status로 확인하세요.")


def cmd_stop() -> None:
    r = _run([str(_BIN / "pg_ctl.exe"), "-D", str(_PGDATA), "stop", "-m", "fast"])
    print("[stop]", "OK" if r.returncode == 0 else r.stderr[-300:])


def cmd_status() -> None:
    import psycopg

    from app.core.config import get_settings

    try:
        psycopg.connect(get_settings().PGVECTOR_DSN, connect_timeout=3).close()
        print("[status] 연결 OK: PG 기동 중")
    except Exception as exc:  # noqa: BLE001
        print(f"[status] 연결 실패(PG 미기동?): {exc}")
        sys.exit(1)


def cmd_setup() -> None:
    from app.adapters.pgvector_index import ensure_schema, get_conn, ingest_corpus

    conn = get_conn()
    ensure_schema(conn)
    res = ingest_corpus(conn)
    conn.close()
    print(f"[setup] 스키마 + 적재 완료: {res}")


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="userspace pgvector 관리")
    p.add_argument("command", choices=["start", "stop", "status", "setup"])
    args = p.parse_args(argv)
    {"start": cmd_start, "stop": cmd_stop, "status": cmd_status, "setup": cmd_setup}[args.command]()


if __name__ == "__main__":
    main()
