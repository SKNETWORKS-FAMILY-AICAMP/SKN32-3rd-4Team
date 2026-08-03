"""
목적: 실손보험 청구사례 가상 샘플 데이터 50건을 생성한다.
     전부 가상 데이터이며 실제 개인정보/실제 청구 사례를 포함하지 않는다.

이 데이터는 "청구 승인율 조회 / 유사사례 검색" 기능 개발용이고,
insurance_rag(Index A: 약관)와는 완전히 분리된 영역(Index B: 청구사례)이다.
"""

import random
import csv
import json
from datetime import date, timedelta

random.seed(42)  # 실행할 때마다 같은 결과가 나오게 고정

INSURERS = [
    "삼성화재", "DB손해보험", "현대해상", "KB손해보험", "메리츠화재",
    "흥국화재", "롯데손해보험", "NH농협손해보험", "삼성생명", "동양생명",
]
GENERATIONS = ["1세대", "2세대", "3세대", "4세대", "5세대"]

# (질병코드, 질병명, 입원 성향이 높은 편인가)
DISEASES = [
    ("J00", "감기", False),
    ("J10", "독감", False),
    ("J20", "급성 기관지염", False),
    ("J18", "폐렴", True),
    ("K29", "위염", False),
    ("K35", "맹장염", True),
    ("M54", "허리통증", False),
    ("M51", "디스크", True),
    ("S82", "골절", True),
    ("S63", "손목 염좌", False),
    ("F32", "우울증", False),
    ("F41", "불안장애", False),
    ("J03", "편도염", False),
    ("H10", "결막염", False),
    ("B02", "대상포진", True),
]

DENIAL_REASONS = [
    "면책기간", "약관상 보장 제외", "보장 한도 초과", "자기부담금 적용",
    "자기부담금 이하", "비급여 치료", "미용 목적 치료", "서류 미비",
    "보험기간 외 사고", "보장 대상 아님",
]

TOTAL = 50
TARGET_INPATIENT = 20  # 40%
TARGET_OUTPATIENT = 30  # 60%


def random_date(start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


def build_base_records() -> list[dict]:
    """질병/보험사/세대/입원유형(질병 성향 기반)까지 채운 기본 레코드를 만든다."""
    records = []
    for i in range(TOTAL):
        insurer = random.choice(INSURERS)
        generation = random.choice(GENERATIONS)
        disease_code, disease_name, inpatient_prone = random.choice(DISEASES)

        # 질병 성향에 따라 입원/통원을 확률적으로 우선 배정 (나중에 전체 비율을 맞춰 보정한다)
        if inpatient_prone:
            admission_type = random.choices(["입원", "통원"], weights=[70, 30])[0]
        else:
            admission_type = random.choices(["입원", "통원"], weights=[20, 80])[0]

        enrollment_dt = random_date(date(2015, 1, 1), date(2023, 12, 31))
        claim_dt = random_date(enrollment_dt + timedelta(days=180), date(2026, 7, 31))

        records.append({
            "claim_id": f"CLM{i + 1:04d}",
            "insurer": insurer,
            "generation": generation,
            "product_name": f"{insurer} 실손의료보험 {generation}",
            "disease_code": disease_code,
            "disease_name": disease_name,
            "admission_type": admission_type,
            "enrollment_date": enrollment_dt.isoformat(),
            "claim_date": claim_dt.isoformat(),
        })
    return records


def fix_admission_type_ratio(records: list[dict]) -> None:
    """전체 입원/통원 개수가 정확히 20/30이 되도록 초과분을 다른 쪽으로 뒤집는다."""
    inpatient = [r for r in records if r["admission_type"] == "입원"]
    outpatient = [r for r in records if r["admission_type"] == "통원"]

    while len(inpatient) > TARGET_INPATIENT:
        r = inpatient.pop()
        r["admission_type"] = "통원"
        outpatient.append(r)

    while len(outpatient) > TARGET_OUTPATIENT:
        r = outpatient.pop()
        r["admission_type"] = "입원"
        inpatient.append(r)


def assign_claim_result(records: list[dict]) -> None:
    """전체 50건에 승인 30 / 부분승인 10 / 거절 10을 배정하고, 그에 맞춰 금액을 채운다."""
    results = ["승인"] * 30 + ["부분승인"] * 10 + ["거절"] * 10
    random.shuffle(results)

    for record, result in zip(records, results):
        if record["admission_type"] == "통원":
            claim_amount = random.randint(3, 50) * 10000  # 3만~50만원
        else:
            claim_amount = random.randint(30, 800) * 10000  # 30만~800만원

        if result == "승인":
            paid_amount = int(claim_amount * random.uniform(0.85, 1.0))
            denial_reason = None
        elif result == "부분승인":
            paid_amount = int(claim_amount * random.uniform(0.3, 0.8))
            denial_reason = random.choice(DENIAL_REASONS)
        else:  # 거절
            paid_amount = 0
            denial_reason = random.choice(DENIAL_REASONS)

        record["claim_amount"] = claim_amount
        record["paid_amount"] = paid_amount
        record["result"] = result
        record["denial_reason"] = denial_reason


COLUMN_ORDER = [
    "claim_id", "insurer", "generation", "product_name", "disease_code", "disease_name",
    "admission_type", "enrollment_date", "claim_date", "claim_amount", "paid_amount",
    "result", "denial_reason",
]


def save_csv(records: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMN_ORDER)
        writer.writeheader()
        writer.writerows(records)


def save_json(records: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    records = build_base_records()
    fix_admission_type_ratio(records)
    assign_claim_result(records)

    save_csv(records, "claim_samples.csv")
    save_json(records, "claim_samples.json")

    # 분포 확인 출력
    result_counts = {}
    admission_counts = {}
    for r in records:
        result_counts[r["result"]] = result_counts.get(r["result"], 0) + 1
        admission_counts[r["admission_type"]] = admission_counts.get(r["admission_type"], 0) + 1

    print("총 건수:", len(records))
    print("결과 분포:", result_counts)
    print("입원/통원 분포:", admission_counts)
