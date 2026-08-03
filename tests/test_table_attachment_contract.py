from scripts.extract.table_signals import attachment_verdict


def _row(value: str = "1만원") -> dict:
    return {"no": 1, "cols": {"1": "의원", "2": value}}


def test_line_table_without_new_signal_is_backward_compatible():
    ok, why = attachment_verdict({"method": "선", "records": [_row()]})
    assert ok is True
    assert why == []


def test_page_gate_rejection_is_not_attachable():
    ok, why = attachment_verdict(
        {"method": "선", "is_table": False, "reject_why": ["T8"], "records": [_row()]}
    )
    assert ok is False
    assert "T8" in why


def test_prose_shaped_line_grid_is_not_attachable():
    long_sentence = "회사는 보험금을 지급하지 않습니다. " * 8
    ok, why = attachment_verdict({"method": "선", "records": [_row(long_sentence)]})
    assert ok is False
    assert why


def test_unverified_two_column_method_is_not_attachable():
    ok, why = attachment_verdict({"method": "2열짝짓기", "records": [_row()]})
    assert ok is False
    assert any("미검증 방식" in reason for reason in why)


def test_missing_t6_has_explicit_unmeasured_reason():
    from scripts.extract.table_signals import verdict

    ok, why = verdict({"T1_corridor": 0.0})
    assert ok is False
    assert "T6 본문 지문을 재지 못함" in why
