"""TEST-SEC-VERIFY-001 — 보안 10케이스 매핑 정적 검증(Phase 10).

`security_cases.yaml`에 적힌 pytest node id가 실제로 pytest 수집기로 collect되고
skip/xfail이 아님을 `test_requirements_matrix.py`와 **같은(더 강한) 검증 로직**을
재사용해 확인한다(로직 중복 금지 — 한쪽만 강화되고 다른 쪽이 뒤처지는 것을 방지).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from tests.test_requirements_matrix import _is_collected, _parse_node, _skip_or_xfail_marks

_CASES_PATH = pathlib.Path(__file__).resolve().parent / "security_cases.yaml"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_cases() -> list[dict]:
    data = yaml.safe_load(_CASES_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def _iter_sec_entries():
    for case in _load_cases():
        for t in case["tests"]:
            yield case["id"], t["node"], t.get("basis")


@pytest.mark.parametrize(
    "case_id,node,basis", list(_iter_sec_entries()), ids=lambda v: str(v)[:40]
)
def test_security_case_node_is_actually_collectible_and_not_skipped(case_id, node, basis):
    rel_path, func_name = _parse_node(node)  # 형식 오류는 여기서 바로 실패
    file_path = _REPO_ROOT / rel_path
    assert file_path.exists(), f"[{case_id}] 파일이 없습니다: {rel_path}"

    assert _is_collected(node), f"[{case_id}] pytest가 실제로 collect하지 못했습니다: {node}"

    mark_names = _skip_or_xfail_marks(rel_path, func_name)
    assert "skip" not in mark_names, f"[{case_id}] {node}가 skip 처리돼 있습니다."
    assert "xfail" not in mark_names, f"[{case_id}] {node}가 xfail입니다."

    assert isinstance(basis, str) and basis.strip(), f"[{case_id}] {node}에 basis가 비어 있습니다."


def test_all_ten_security_cases_present_and_done():
    cases = _load_cases()
    ids = [c["id"] for c in cases]
    assert ids == [f"TEST-SEC-{i:03d}" for i in range(1, 11)], f"보안 10케이스 목록 불일치: {ids}"
    for c in cases:
        assert c["status"] == "DONE", f"{c['id']}가 DONE이 아닙니다."
        assert c["tests"], f"{c['id']}에 매핑된 테스트가 없습니다."
        assert c["threat_model"].strip(), f"{c['id']}에 위협모델 설명이 없습니다."
