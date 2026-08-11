"""Regression guards for non-PostgreSQL readiness and admin UI behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.obs import readiness
from app.obs.readiness import _required_sqlite_tables


def test_sqlite_readiness_requires_auth_and_ops_tables():
    settings = SimpleNamespace(
        SQLITE_LEGACY_ENABLED=True,
        AUTH_PERSISTENCE="sqlite",
        OPS_PERSISTENCE="sqlite",
    )

    assert set(_required_sqlite_tables(settings)) == {
        "users",
        "face_credentials",
        "run_events",
        "knowledge_gaps",
    }


def test_disabled_sqlite_still_reports_active_sqlite_paths():
    settings = SimpleNamespace(
        SQLITE_LEGACY_ENABLED=False,
        AUTH_PERSISTENCE="sqlite",
        OPS_PERSISTENCE="sqlite",
    )

    assert set(_required_sqlite_tables(settings)) == {
        "users",
        "face_credentials",
        "run_events",
        "knowledge_gaps",
    }


def test_disabled_sqlite_with_postgres_paths_requires_no_sqlite_tables():
    settings = SimpleNamespace(
        SQLITE_LEGACY_ENABLED=False,
        AUTH_PERSISTENCE="postgres",
        OPS_PERSISTENCE="postgres",
    )

    assert _required_sqlite_tables(settings) == ()


def test_readiness_explains_disabled_sqlite_configuration(monkeypatch, tmp_path):
    from app import composition
    from app.adapters import demo_submission_store
    from app.core import candidate_fact_registry

    settings = SimpleNamespace(
        SQLITE_LEGACY_ENABLED=False,
        AUTH_PERSISTENCE="sqlite",
        OPS_PERSISTENCE="sqlite",
        VECTOR_DIR=tmp_path,
        PRECHECK_PERSISTENCE="off",
        OUTCOME_PERSISTENCE="file",
        AGENT_API_ENABLED=False,
    )
    monkeypatch.setattr(readiness, "get_settings", lambda: settings)
    monkeypatch.setattr(
        readiness,
        "_clause_index_state",
        lambda: {"ready": True, "checked": True},
    )
    monkeypatch.setattr(composition, "_clause_store_kind", lambda: "file")
    monkeypatch.setattr(
        candidate_fact_registry,
        "check_candidate_fact_sources",
        lambda: {"ready": True},
    )
    monkeypatch.setattr(demo_submission_store, "backend_name", lambda: "file")

    result = readiness.check_readiness()

    assert result["ready"] is False
    assert result["db_tables_ready"] is False
    assert set(result["missing_tables"]) == {
        "users",
        "face_credentials",
        "run_events",
        "knowledge_gaps",
    }
    assert "SQLITE_LEGACY_ENABLED=true" in result["hint"]


def test_admin_ui_preserves_api_error_and_shows_remaining_outcomes():
    js = Path("app/static/admin.js").read_text(encoding="utf-8")

    assert 'typeof body.message === "string"' in js
    assert 'formatLoadFailure("코호트", cohortResult.reason)' in js
    assert 'showError(failures.join(" · "))' in js
    assert "total - approved - denied" in js
    assert "일부지급·처리중" in js
