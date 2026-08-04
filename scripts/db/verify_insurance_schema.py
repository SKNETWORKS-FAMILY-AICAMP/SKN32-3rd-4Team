# -*- coding: utf-8 -*-
"""Fresh PostgreSQL DB에서 core/app/ops migration과 핵심 불변식을 검증한다.

기존 DB는 사용하지 않는다. ``insurance_schema_verify_<uuid>`` DB를 생성하고
검증 후 즉시 삭제한다. 관리자 DSN은 ``--admin-dsn`` 또는 ``PG_DSN``으로 받는다.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.db import apply as migration_apply

_PREFIX = "insurance_schema_verify_"


def _expect_error(conn: psycopg.Connection, statement: str, params=()) -> str:
    conn.execute("SAVEPOINT expected_failure")
    try:
        conn.execute(statement, params)
    except psycopg.Error as exc:
        code = exc.sqlstate or "unknown"
        conn.execute("ROLLBACK TO SAVEPOINT expected_failure")
        conn.execute("RELEASE SAVEPOINT expected_failure")
        return code
    conn.execute("RELEASE SAVEPOINT expected_failure")
    raise AssertionError("무결성 위반 SQL이 성공했다")


def _apply(target_dsn: str) -> None:
    old_argv = sys.argv[:]
    old_dsn = os.environ.get("PG_DSN")
    try:
        os.environ["PG_DSN"] = target_dsn
        sys.argv = ["apply", "--track", "core"]
        if migration_apply.main() != 0:
            raise RuntimeError("migration apply 실패")
    finally:
        sys.argv = old_argv
        if old_dsn is None:
            os.environ.pop("PG_DSN", None)
        else:
            os.environ["PG_DSN"] = old_dsn


def _seed_and_verify(conn: psycopg.Connection) -> dict[str, object]:
    admin = conn.execute(
        "INSERT INTO ops.admin_user(login, role) "
        "VALUES ('schema-test-admin','reviewer') RETURNING id"
    ).fetchone()[0]
    insurer = conn.execute(
        "INSERT INTO core.insurer(slug,legal_name,display_name,kind) "
        "VALUES ('schema-test','Schema Test Insurance','Schema Test','general') "
        "RETURNING id"
    ).fetchone()[0]
    document = conn.execute(
        "INSERT INTO core.confirmed_policy_document("
        "sha256,source_url,fetched_at,insurer_id,identified_by,identified_at) "
        "VALUES (%s,'https://example.invalid/policy.pdf',now(),%s,%s,now()) "
        "RETURNING id",
        ("a" * 64, insurer, admin),
    ).fetchone()[0]
    extraction = conn.execute(
        "INSERT INTO core.document_extraction("
        "confirmed_document_id,extractor,schema_version,parse_status,extracted_at) "
        "VALUES (%s,'schema-test',1,'ok',now()) RETURNING id",
        (document,),
    ).fetchone()[0]
    product = conn.execute(
        "INSERT INTO core.product(insurer_id,product_code,name) "
        "VALUES (%s,'SCHEMA-T1','Schema Test Product') RETURNING id",
        (insurer,),
    ).fetchone()[0]
    version1 = conn.execute(
        "INSERT INTO core.policy_version("
        "confirmed_document_id,product_id,version_label,date_confidence,generation) "
        "VALUES (%s,%s,'v1','exact',1) RETURNING id",
        (document, product),
    ).fetchone()[0]
    version2 = conn.execute(
        "INSERT INTO core.policy_version("
        "confirmed_document_id,product_id,version_label,date_confidence,generation) "
        "VALUES (%s,%s,'v2','exact',2) RETURNING id",
        (document, product),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO core.clause_content("
        "content_hash,hash_version,title,body,char_length) VALUES "
        "(%s,'v1','ground','body1',5),(%s,'v1','other','body2',5)",
        ("b" * 64, "c" * 64),
    )
    clause1 = conn.execute(
        "INSERT INTO core.policy_clause("
        "confirmed_document_id,document_extraction_id,policy_version_id,ordinal,"
        "content_hash,citeable,locator) VALUES (%s,%s,%s,0,%s,true,'{}') "
        "RETURNING id",
        (document, extraction, version1, "b" * 64),
    ).fetchone()[0]
    clause2 = conn.execute(
        "INSERT INTO core.policy_clause("
        "confirmed_document_id,document_extraction_id,policy_version_id,ordinal,"
        "content_hash,citeable,locator) VALUES (%s,%s,%s,1,%s,true,'{}') "
        "RETURNING id",
        (document, extraction, version2, "c" * 64),
    ).fetchone()[0]
    kcd_version = conn.execute(
        "INSERT INTO core.kcd_version(label) VALUES ('KCD-test') RETURNING id"
    ).fetchone()[0]
    kcd_code = conn.execute(
        "INSERT INTO core.kcd_code(kcd_version_id,code,name_ko) "
        "VALUES (%s,'S72.0','test') RETURNING id",
        (kcd_version,),
    ).fetchone()[0]

    subject = conn.execute(
        "INSERT INTO app.subject(age_band) VALUES ('30s') RETURNING id"
    ).fetchone()[0]
    holding = conn.execute(
        "INSERT INTO app.policy_holding("
        "subject_id,product_id,policy_version_id,enrolled_on) "
        "VALUES (%s,%s,%s,'2024-01-01') RETURNING id",
        (subject, product, version1),
    ).fetchone()[0]
    review1 = conn.execute(
        "INSERT INTO app.coverage_review("
        "subject_id,policy_holding_id,incident_on,channel) "
        "VALUES (%s,%s,'2025-01-01','api') RETURNING id",
        (subject, holding),
    ).fetchone()[0]
    review2 = conn.execute(
        "INSERT INTO app.coverage_review("
        "subject_id,policy_holding_id,incident_on,channel) "
        "VALUES (%s,%s,'2025-01-02','api') RETURNING id",
        (subject, holding),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO app.case_diagnosis(case_id,kcd_code_id) VALUES (%s,%s)",
        (review1, kcd_code),
    )
    assessment1 = conn.execute(
        "INSERT INTO app.assessment("
        "case_id,policy_version_id,verdict,rule_engine_version) "
        "VALUES (%s,%s,'likely_covered','schema-test-v1') RETURNING id",
        (review1, version1),
    ).fetchone()[0]
    assessment2 = conn.execute(
        "INSERT INTO app.assessment("
        "case_id,policy_version_id,verdict,rule_engine_version) "
        "VALUES (%s,%s,'needs_expert','schema-test-v1') RETURNING id",
        (review2, version1),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO app.assessment_clause_citation("
        "assessment_id,policy_clause_id,citeable,role,content_hash,quote,locator,"
        "policy_version_id) VALUES (%s,%s,true,'ground',%s,'body1','{}',%s)",
        (assessment1, clause1, "b" * 64, version1),
    )

    cross_version = _expect_error(
        conn,
        "INSERT INTO app.assessment_clause_citation("
        "assessment_id,policy_clause_id,citeable,role,content_hash,quote,locator,"
        "policy_version_id) VALUES (%s,%s,true,'ground',%s,'body2','{}',%s)",
        (assessment1, clause2, "c" * 64, version2),
    )
    wrong_review = _expect_error(
        conn,
        "INSERT INTO app.claim(case_id,assessment_id,claimed_on,claimed_amount) "
        "VALUES (%s,%s,'2025-01-03',1000)",
        (review1, assessment2),
    )

    claim = conn.execute(
        "INSERT INTO app.claim(case_id,assessment_id,claimed_on,claimed_amount) "
        "VALUES (%s,%s,'2025-01-03',1000) RETURNING id",
        (review1, assessment1),
    ).fetchone()[0]
    outcome = conn.execute(
        "INSERT INTO app.outcome(claim_id,decision,paid_amount,decided_on) "
        "VALUES (%s,'approved',800,'2025-02-01') RETURNING id",
        (claim,),
    ).fetchone()[0]
    evidence = conn.execute(
        "INSERT INTO app.evidence(outcome_id,doc_type,sha256_hash,stored_ref) "
        "VALUES (%s,'decision_notice',%s,'object://schema-test') RETURNING id",
        (outcome, "d" * 64),
    ).fetchone()[0]

    baseline = conn.execute(
        "SELECT coalesce(sum(n),0) FROM app.cohort_stats"
    ).fetchone()[0]
    verify_too_early = _expect_error(
        conn,
        "SELECT app.record_evidence_verification("
        "%s,'verified','admin_review',%s,NULL)",
        (evidence, admin),
    )

    conn.execute("SET ROLE insurance_app")
    consistency = conn.execute(
        "SELECT app.record_evidence_consistency(%s,true,%s::jsonb)",
        (evidence, '{"amount_matches":true}'),
    ).fetchone()[0]
    conn.execute("RESET ROLE")
    after_consistency = conn.execute(
        "SELECT coalesce(sum(n),0) FROM app.cohort_stats"
    ).fetchone()[0]

    conn.execute("SET ROLE insurance_app")
    verification1 = conn.execute(
        "SELECT app.record_evidence_verification("
        "%s,'verified','admin_review',%s,'schema test')",
        (evidence, admin),
    ).fetchone()[0]
    verification2 = conn.execute(
        "SELECT app.record_evidence_verification("
        "%s,'verified','admin_review',%s,'schema test')",
        (evidence, admin),
    ).fetchone()[0]
    direct_mutation = _expect_error(
        conn,
        "UPDATE app.evidence_verification SET reason='tamper' WHERE id=%s",
        (verification1,),
    )
    conn.execute("RESET ROLE")

    after_verification = conn.execute(
        "SELECT coalesce(sum(n),0) FROM app.cohort_stats"
    ).fetchone()[0]
    assert (int(baseline), int(after_consistency), int(after_verification)) == (0, 0, 1)
    assert verification1 == verification2
    assert consistency["status"] == "consistent"

    noncompliant_owners = conn.execute(
        "SELECT n.nspname,c.relname,r.rolname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_roles r ON r.oid=c.relowner "
        "WHERE n.nspname IN ('app','core','ops') "
        "AND c.relkind IN ('r','v') AND r.rolname<>'insurance_owner'"
    ).fetchall()
    assert noncompliant_owners == []
    assert conn.execute(
        "SELECT to_regclass('app.coverage_review') IS NOT NULL, "
        "to_regclass('app.\"case\"') IS NULL"
    ).fetchone() == (True, True)
    assert conn.execute(
        "SELECT has_table_privilege("
        "'insurance_app','app.evidence_verification','UPDATE')"
    ).fetchone()[0] is False

    return {
        "cross_version": cross_version,
        "wrong_review": wrong_review,
        "verify_too_early": verify_too_early,
        "direct_mutation": direct_mutation,
        "cohort": [int(baseline), int(after_consistency), int(after_verification)],
        "verification_idempotent": verification1 == verification2,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn", default=os.environ.get("PG_DSN", ""))
    args = parser.parse_args(argv)
    if not args.admin_dsn:
        parser.error("--admin-dsn 또는 PG_DSN이 필요합니다")

    base = conninfo_to_dict(args.admin_dsn)
    database = _PREFIX + uuid.uuid4().hex[:12]
    admin_dsn = make_conninfo(**{**base, "dbname": "postgres"})
    target_dsn = make_conninfo(**{**base, "dbname": database})
    created = False
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            if conn.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                raise RuntimeError(f"임시 DB가 이미 존재합니다: {database}")
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            created = True

        _apply(target_dsn)
        with psycopg.connect(target_dsn) as conn:
            result = _seed_and_verify(conn)
            conn.commit()
        print(f"[verify-insurance-schema] PASS {result}")
        return 0
    finally:
        if created:
            if not database.startswith(_PREFIX):
                raise RuntimeError(f"임시 DB 이름 안전검사 실패: {database}")
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()",
                    (database,),
                )
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            print(f"[verify-insurance-schema] dropped temporary DB {database}")


if __name__ == "__main__":
    raise SystemExit(main())
