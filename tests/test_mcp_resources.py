"""app/mcp_server/resources.py -- support-manifest, precheck-v1 스키마."""

from app.core.ports.precheck import PolicyVersionRow
from app.mcp_server import resources as res


def test_precheck_schema_v1은_verdict_4단을_명시한다():
    schema = res.precheck_schema_v1()
    assert set(schema["properties"]["verdict"]["enum"]) == {
        "likely_covered", "unlikely", "needs_documents", "needs_expert",
    }


def test_support_manifest_약관_0건이면_경고를_붙인다(monkeypatch):
    def fake_build_precheck():
        class _P:
            def load_versions(self):
                return []
        return {"policies": _P()}

    monkeypatch.setattr("app.composition.build_precheck", fake_build_precheck)
    manifest = res.support_manifest()

    assert manifest["total_policy_versions"] == 0
    assert any("0건" in n for n in manifest["notes"])
    assert set(manifest["tools"]) == {
        "insurance_precheck", "policy_clause_search", "submit_case_observation",
    }


def test_support_manifest_보험사별로_집계한다(monkeypatch):
    versions = [
        PolicyVersionRow(
            insurer="삼성화재", product_name="실손A", sale_start="20170401",
            sale_end="20210630", generation=3, generation_label="3세대",
            product_line="standard", sha256="a" * 64,
            date_confidence="exact", generation_confidence="exact",
        ),
        PolicyVersionRow(
            insurer="삼성화재", product_name="실손B", sale_start="20210701",
            sale_end="", generation=4, generation_label="4세대",
            product_line="standard", sha256="b" * 64,
            date_confidence="exact", generation_confidence="exact",
        ),
    ]

    def fake_build_precheck():
        class _P:
            def load_versions(self):
                return versions
        return {"policies": _P()}

    monkeypatch.setattr("app.composition.build_precheck", fake_build_precheck)
    manifest = res.support_manifest()

    assert manifest["total_policy_versions"] == 2
    assert manifest["insurers"]["삼성화재"]["versions"] == 2
    assert manifest["insurers"]["삼성화재"]["generations"] == [3, 4]
