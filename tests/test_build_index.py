"""인덱스 빌드 경계 테스트 (임베딩 불필요 → CI 경로 유지).

Phase 8: 레거시 `app/rag/qa.py` 삭제로 `test_qa.py`가 없어지면서, qa와 무관한 build_index
검사를 여기로 이관했다. `test_rag.py`는 ml 마커(실 임베딩)라 CI에서 제외되므로 그쪽에 두면
CI 커버리지를 잃는다 — 그래서 마커 없는 별도 파일로 둔다.
"""

from __future__ import annotations

import pytest

from app.core.errors import InfraError


def test_pdf_parse_failure_raises_infra_error(tmp_path):
    """PDF 파싱 실패는 TXT로 조용히 대체하지 않고 InfraError로 명시 실패(무폴백)."""
    from app.rag.build_index import _load_docs

    (tmp_path / "broken.pdf").write_text("이건 진짜 PDF가 아니라 그냥 텍스트입니다", encoding="utf-8")
    with pytest.raises(InfraError):
        _load_docs(tmp_path)


def test_ingest_only_collects_allowed_extensions(tmp_path):
    """TEST-SEC-007: .txt/.pdf가 아닌 파일(.py/.env 등)은 수집하지 않는다.

    위협모델(정직하게 기록): docs_dir은 CLI 운영자가 지정하는 값이라 원격 공격자가 통제할
    수 없다 — 이 테스트는 "원격 공격 방어 증명"이 아니라 **확장자 허용목록 불변식 고정**이다.
    """
    from app.rag.build_index import _load_docs

    (tmp_path / "policy.txt").write_text("정책 내용", encoding="utf-8")
    (tmp_path / "secret.env").write_text("API_KEY=leak", encoding="utf-8")
    (tmp_path / "script.py").write_text("print('no')", encoding="utf-8")

    docs = _load_docs(tmp_path)
    sources = {d.metadata["source"] for d in docs}
    assert sources == {"policy.txt"}
    assert "secret.env" not in sources and "script.py" not in sources


def test_ingest_does_not_recurse_into_subdirectories(tmp_path):
    """TEST-SEC-007: 하위 폴더(경로 이동으로 배치된 파일 포함)는 수집하지 않는다(비재귀 glob).

    같은 정직한 한계: 이 도구가 향후 사용자 업로드 API로 확장되면 그때는 경로 정규화를
    반드시 재검토해야 한다(잔여위험, §6 참조 — 플랜 문서에 명시).
    """
    from app.rag.build_index import _load_docs

    (tmp_path / "top.txt").write_text("최상위 문서", encoding="utf-8")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "escaped.txt").write_text("하위 폴더 문서(수집되면 안 됨)", encoding="utf-8")

    docs = _load_docs(tmp_path)
    sources = {d.metadata["source"] for d in docs}
    assert sources == {"top.txt"}
