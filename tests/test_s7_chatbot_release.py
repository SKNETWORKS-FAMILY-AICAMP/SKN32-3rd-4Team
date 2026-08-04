from __future__ import annotations

import json

import pytest

from app.adapters import file_glossary_source as source
from app.core.errors import InfraError


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _configure(monkeypatch, tmp_path):
    release = tmp_path / "accepted.json"
    release.write_text('{"supplemental_facts":"accepted_s7.json"}', encoding="utf-8")
    monkeypatch.setattr(source, "_ACCEPTED_RELEASE", release)
    monkeypatch.setattr(source, "_PASSAGES", tmp_path / "missing-passages.jsonl")
    monkeypatch.setattr(source, "_META", tmp_path / "missing-meta.json")
    monkeypatch.setenv("S7_FACT_ROOT", str(tmp_path / "s7"))
    source._reset_for_tests()
    return tmp_path / "s7"


def test_partial_s7_bundle_fails_closed(monkeypatch, tmp_path):
    root = _configure(monkeypatch, tmp_path)
    root.mkdir()
    _jsonl(root / "approved_facts.jsonl", [])
    with pytest.raises(InfraError, match="일부만 배포"):
        source._load()


def test_only_approved_s7_facts_reach_chatbot(monkeypatch, tmp_path):
    root = _configure(monkeypatch, tmp_path)
    root.mkdir()
    approved = {"content_hash": "approved", "serving_eligible": True, "citation_eligible": True,
                "document_sha12": "a" * 12, "service": ["외래"], "plan": "표준형"}
    quarantined = {"content_hash": "quarantined", "serving_eligible": False, "citation_eligible": False}
    _jsonl(root / "approved_facts.jsonl", [approved, quarantined])
    _jsonl(root / "chunks.jsonl", [
        {"content_hash": "approved", "text": "검수 승인 자기부담금 표 사실"},
        {"content_hash": "quarantined", "text": "격리 후보"},
    ])
    _jsonl(root / "occurrences.jsonl", [
        {"content_hash": "approved", "insurer": "test", "page_from": 7},
        {"content_hash": "quarantined", "insurer": "test", "page_from": 8},
    ])
    rows = source._load()
    assert [row.content_hash for row in rows] == ["approved"]
    assert source.meta()["s7_approved_fact_passages"] == 1
