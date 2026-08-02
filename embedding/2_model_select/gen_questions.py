"""샘플 청크에서 역방향으로 평가 문항 자동 생성 (정답 존재 보장)
유형: 조항지정 / 구어체 / 표숫자 / 필터교차"""
import json
import random
from collections import Counter, defaultdict

SAMPLE = r"out\eval_sample.jsonl"
OUTPUT = "eval_questions_v4.json"
MIN_CHUNKS = 3          # 이 개수 이상 정답 후보가 있어야 문항 채택
MAX_TOTAL = 80
random.seed(42)

# 키워드 -> 구어체 질문 변형 (키워드를 직접 쓰지 않는 표현 포함)
COLLOQUIAL = {
    "공제":   ["병원비에서 얼마를 빼고 보험금을 주나요?", "공제되는 금액 기준이 궁금해요"],
    "한도":   ["보상받을 수 있는 최대 금액이 있나요?", "한도가 어떻게 되나요?"],
    "자기부담": ["제가 직접 부담해야 하는 비율이 있나요?", "자기부담금 기준을 알려주세요"],
    "통원":   ["병원에 다니면서 치료받으면 보장되나요?", "외래로 진료받은 비용은요?"],
    "입원":   ["입원하면 어디까지 보상해주나요?", "병원에 누워있는 동안 비용은요?"],
    "수술":   ["수술받으면 보험금 나오나요?", "수술비 보장 기준이 궁금해요"],
    "약제":   ["약값도 보상이 되나요?", "처방받은 약 비용은요?"],
    "갱신":   ["계약을 연장할 때 조건이 있나요?", "갱신은 어떻게 되나요?"],
    "해지":   ["계약을 그만두면 어떻게 되나요?", "중간에 해지하면요?"],
    "청구":   ["보험금을 받으려면 뭘 해야 하나요?", "청구 절차가 궁금해요"],
    "면책":   ["보장이 안 되는 기간이 있나요?", "면책 조건을 알려주세요"],
    "간호":   ["간병 관련 비용도 보상되나요?", "간호 비용은요?"],
    "도수":   ["도수치료 받은 것도 청구 가능한가요?", "도수치료 보장 여부가 궁금해요"],
    "자기공명": ["MRI 촬영 비용도 보장되나요?", "MRI 찍은 거 청구할 수 있나요?"],
    "주사":   ["주사 치료 비용은 보상해주나요?", "주사료도 포함인가요?"],
    "치과":   ["치과 치료도 보장 대상인가요?", "이빨 치료받은 비용은요?"],
    "한방":   ["한의원 다닌 것도 보상되나요?", "한방 치료 비용은요?"],
    "상급병실": ["1인실 쓰면 병실료 차액도 주나요?", "상급병실 비용은 어떻게 되나요?"],
}

chunks = [json.loads(l) for l in open(SAMPLE, encoding="utf-8")]
questions = []
qn = 0


def add(qtype, query, where, expect):
    global qn
    qn += 1
    questions.append({"id": f"a{qn:02d}", "type": qtype,
                      "query": query, "where": where, "expect": expect})


def count_match(where, text_kw=None, ctype=None, cite_kw=None):
    n = 0
    for c in chunks:
        if where and any(c.get(k) != v for k, v in where.items()):
            continue
        if text_kw and text_kw not in c["text"]:
            continue
        if ctype and c["content_type"] != ctype:
            continue
        if cite_kw and cite_kw not in (c.get("citation") or ""):
            continue
        n += 1
    return n

# ---- 1) 조항지정: 자주 나오는 조항 제목에서 생성 (최대 15문항) ----
titles = Counter(c.get("article_title") for c in chunks
                 if c.get("article_title") and len(c["article_title"]) >= 4)
for title, freq in titles.most_common(15):
    if count_match(None, cite_kw=title) >= MIN_CHUNKS:
        form = random.choice([f"{title}에 대한 조항 내용을 알려주세요",
                              f"약관에서 {title} 부분이 궁금해요"])
        add("조항지정", form, None, {"citation_contains": title})

# ---- 2) 구어체: 키워드 존재 확인 후 변형 질문 (키워드당 최대 2문항) ----
for kw, forms in COLLOQUIAL.items():
    if count_match(None, text_kw=kw) >= MIN_CHUNKS:
        for form in forms:
            add("구어체", form, None, {"text_contains": kw})

# ---- 3) 표숫자: 표 청크에 존재하는 키워드로 생성 ----
for kw in ["공제", "한도", "통원", "입원", "보험가입금액", "보장금액"]:
    if count_match(None, text_kw=kw, ctype="table") >= MIN_CHUNKS:
        add("표숫자", f"{kw} 관련 구체적인 금액 기준을 알려주세요", None,
            {"content_type": "table", "text_contains": kw})

# ---- 4) 필터교차: (보험사|세대) x 키워드, 해당 부분집합에 정답 존재 시 ----
insurers = sorted({c["insurer"] for c in chunks})
gens = sorted({c["generation"] for c in chunks if c["generation"] != "unknown"})
cross_kw = ["통원", "입원", "공제", "한도", "부담"]
for ins in insurers:
    picked = 0
    for kw in cross_kw:
        w = {"insurer": ins}
        if count_match(w, text_kw=kw) >= MIN_CHUNKS:
            add("필터교차", f"{kw} 관련 내용을 알려주세요", w,
                {"insurer": ins, "text_contains": kw})
            picked += 1
            if picked >= 2:
                break
for g in gens:
    picked = 0
    for kw in cross_kw:
        w = {"generation": g}
        if count_match(w, text_kw=kw) >= MIN_CHUNKS:
            add("필터교차", f"{kw} 기준이 어떻게 되나요?", w,
                {"generation": g, "text_contains": kw})
            picked += 1
            if picked >= 2:
                break
# 보험사 x 세대 2중 필터 (가장 어려운 유형)
for ins in insurers:
    for g in gens:
        w = {"insurer": ins, "generation": g}
        for kw in cross_kw:
            if count_match(w, text_kw=kw) >= MIN_CHUNKS:
                add("필터교차2중", f"{kw}이(가) 어떻게 되는지 알려주세요", w,
                    {"insurer": ins, "generation": g, "text_contains": kw})
                break

questions = questions[:MAX_TOTAL]
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(questions, f, ensure_ascii=False, indent=1)

print(f"생성 문항: {len(questions)}개 -> {OUTPUT}")
print("유형 분포:", dict(Counter(q["type"] for q in questions)))