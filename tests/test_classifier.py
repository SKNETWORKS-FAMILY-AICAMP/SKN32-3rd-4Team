"""분류·정확도·혼동쌍 테스트 (결정론, mock chat_complete)."""

import pytest

from app.core.errors import ValidationErr
from app.prompts.classifier import (
    UNCLASSIFIED,
    classify_one,
    confusion_pairs,
    load_cs_dataset,
    measure_accuracy,
    normalize_category,
    suggest_fewshot_candidates,
)


def test_normalize_exactly_one():
    assert normalize_category("결제") == "결제"
    assert normalize_category("이건 결제 문의입니다") == "결제"


def test_normalize_zero_or_multiple_is_unclassified():
    assert normalize_category("잘 모르겠어요") == UNCLASSIFIED
    assert normalize_category("결제 아니면 환불") == UNCLASSIFIED  # 2개


def test_classify_one_with_mock():
    assert classify_one("카드 이중청구", chat_complete=lambda p: "결제") == "결제"


def test_classify_one_empty_raises():
    with pytest.raises(ValidationErr):
        classify_one("   ", chat_complete=lambda p: "결제")


def test_measure_accuracy():
    preds = ["결제", "환불", "배송"]
    labels = ["결제", "교환", "배송"]
    r = measure_accuracy(preds, labels)
    assert r["total"] == 3
    assert r["correct"] == 2
    assert r["accuracy"] == round(2 / 3, 4)
    assert r["wrong"] == [(1, "교환", "환불")]


def test_confusion_pairs_and_candidates():
    preds = ["환불", "환불", "배송"]
    labels = ["교환", "교환", "배송"]
    pairs = confusion_pairs(preds, labels)
    assert pairs == {("교환", "환불"): 2}
    cand = suggest_fewshot_candidates(preds, labels, top_n=1)
    assert cand[0]["true_label"] == "교환"
    assert cand[0]["predicted"] == "환불"
    assert cand[0]["count"] == 2


def test_confusion_pairs_length_mismatch_raises():
    with pytest.raises(ValidationErr):
        confusion_pairs(["결제"], ["결제", "환불"])


@pytest.mark.legacy_data
def test_load_cs_dataset():
    """CS 문의 데이터셋 로드.

    ★`data/cs_inquiries.csv` 는 커머스 실습 자료라 **레거시로 압축 격리했다**
      (`legacy/v3_commerce.zip` 안에 있다). 되살리면 레거시 의존성이 생긴다.
      그래서 마커로 빼되 **왜 빠졌는지 여기 적어 둔다** — 조용한 스킵이 아니다.
      분류기 자체(`normalize_category`·`classify_one`)는 이 파일의 다른 테스트가 계속 지킨다.
    """
    texts, labels = load_cs_dataset()
    assert len(texts) == 60
    assert len(labels) == 60
    assert "결제" in set(labels)


def test_improvement_report_before_after():
    """few-shot 보강 전/후 정확도 비교 루프 (mock: augmented가 '교환'을 맞춤)."""
    from app.prompts.classifier import improvement_report

    texts = ["사이즈가 안 맞아 바꾸고 싶어요", "환불해주세요"]
    labels = ["교환", "환불"]

    def chat(prompt):
        examples_section = prompt.split("[분류 대상]")[0]
        target_section = prompt.split("[분류 대상]")[1]
        has_exchange_example = "교환" in examples_section.split("[예시]")[-1]
        if "바꾸고" in target_section:  # 교환 문의
            return "교환" if has_exchange_example else "환불"  # 예시 없으면 오분류
        return "환불"  # 환불 문의는 항상 정답

    base = [("환불해주세요", "환불")]
    augmented = base + [("옷을 다른 색으로 바꾸고 싶어요", "교환")]
    r = improvement_report(texts, labels, base, augmented, chat_complete=chat)
    assert r["before_accuracy"] == 0.5  # 교환을 환불로 오분류
    assert r["after_accuracy"] == 1.0  # 교환 예시 보강 후 정답
    assert r["delta"] == 0.5
