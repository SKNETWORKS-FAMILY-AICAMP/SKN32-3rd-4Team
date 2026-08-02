"""샘플 청크에서 역방향으로 평가 문항 자동 생성 v2
- 정답 chunk_id 기록 (채점: 키워드 포함이 아니라 '그 조항을 찾았는가')
- 2키워드 조합 조건으로 정답 집합을 좁혀 변별력 확보
- 정답 25개 초과 문항은 자동 제외"""
import json
import random
from collections import Counter

SAMPLE = r"out\eval_sample.jsonl"
OUTPUT = "eval_questions_v5.json"
MIN_CHUNKS = 3
MAX_ANSWERS = 25
MAX_TOTAL = 80
random.seed(42)

# (키워드 2개 조합, 구어체 질문)
COLLOQUIAL2 = [
    (("통원", "공제"), "외래 진료받으면 얼마를 공제하고 주나요?"),
    (("통원", "한도"), "통원 치료는 최대 얼마까지 보상되나요?"),
    (("입원", "한도"), "입원비는 한도가 어떻게 되나요?"),
    (("입원", "수술"), "입원해서 수술받은 비용도 보상되나요?"),
    (("처방", "공제"), "처방받은 약값에서 공제되는 금액이 있나요?"),
    (("상급병실", "공제"), "1인실 병실료 차액은 어떻게 계산해서 주나요?"),
    (("도수", "한도"), "도수치료는 몇 회까지 보장되나요?"),
    (("자기공명", "비급여"), "MRI 비급여 비용도 보상 대상인가요?"),
    (("치과", "보상하지"), "치과 치료는 보상 안 해주나요?"),
    (("한방", "보상하지"), "한방 치료가 보상 제외라던데 맞나요?"),
    (("해지", "환급"), "중간에 해지하면 돈을 돌려받을 수 있나요?"),
    (("갱신", "보험료"), "갱신할 때 보험료가 달라지나요?"),
    (("청구", "서류"), "보험금 청구할 때 서류는 뭘 내나요?"),
    (("면책", "보장개시"), "가입 직후에는 보장이 안 되는 기간이 있나요?"),
    (("자기부담", "비급여"), "비급여 항목의 자기부담 비율은 얼마인가요?"),
    (("통원", "횟수"), "통원은 1년에 몇 번까지 인정되나요?"),
    (("입원", "365"), "입원 보상 기간에 제한이 있나요?"),
    (("주사", "비급여"), "비급여 주사 치료도 청구 가능한가요?"),
    (("보상하지", "고의"), "일부러 다친 경우에도 보험금이 나오나요?"),
    (("청약", "철회"), "가입하고 나서 마음이 바뀌면 취소할 수 있나요?"),
    (("납입", "연체"), "보험료를 늦게 내면 어떻게 되나요?"),
    (("알릴", "의무"), "가입할 때 뭘 알려야 하나요?"),
    (("비급여", "주사료"), "비급여 주사료 항목은 어떻게 처리되나요?"),
    (("급여", "본인부담"), "급여 항목의 본인부담금은 어떻게 되나요?"),
]

# 필터교차용 키워드 조합
CROSS_KW = [("통원", "공제"), ("입원", "한도"), ("공제", "금액"),
            ("한도", "보상"), ("부담", "비율")]

chunks = [json.loads(l) for l in open(SAMPLE, encoding="utf-8")]
questions = []
qn = 0


def find_ids(where=None, kws=None, ctype=None, cite_kw=None):
    """조건(메타 where + 키워드 전부 포함 + 타입 + citation)을 만족하는 chunk_id 목록"""
    ids = []
    for c in chunks:
        if where and any(c.get(k) != v for k, v in where.items()):
            continue
        if kws and not all(k in c["text"] for k in kws):
            continue
        if ctype and c["content_type"] != ctype:
            continue
        if cite_kw and cite_kw not in (c.get("citation") or ""):
            continue
        ids.append(c["chunk_id"])
    return ids


def add(qtype, query, where, answer_ids):
    global qn
    if not (MIN_CHUNKS <= len(answer_ids) <= MAX_ANSWERS):
        return
    qn += 1
    questions.append({"id": f"a{qn:02d}", "type": qtype, "query": query,
                      "where": where, "answer_ids": answer_ids})


# ---- 1) 조항지정: 자주 나오는 조항 제목 ----
titles = Counter(c.get("article_title") for c in chunks
                 if c.get("article_title") and len(c["article_title"]) >= 4)
for title, freq in titles.most_common(20):
    ids = find_ids(cite_kw=title)
    form = random.choice([f"{title}에 대한 조항 내용을 알려주세요",
                          f"약관에서 {title} 부분이 궁금해요"])
    add("조항지정", form, None, ids)

# ---- 2) 구어체 (2키워드 조합) ----
for kws, form in COLLOQUIAL2:
    add("구어체", form, None, find_ids(kws=kws))

# ---- 3) 표숫자 (표 타입 + 1키워드) ----
for kw in ["공제", "한도", "통원", "입원", "보험가입금액", "자기부담"]:
    ids = find_ids(kws=(kw,), ctype="table")
    add("표숫자", f"{kw} 관련 정확한 금액 기준을 알려주세요", None, ids)

# ---- 4) 필터교차 (보험사/세대 메타필터 + 2키워드) ----
insurers = sorted({c["insurer"] for c in chunks})
gens = sorted({c["generation"] for c in chunks if c["generation"] != "unknown"})

for ins in insurers:
    picked = 0
    for kws in CROSS_KW:
        before = qn
        add("필터교차", f"{kws[0]}·{kws[1]} 관련 내용을 알려주세요",
            {"insurer": ins}, find_ids(where={"insurer": ins}, kws=kws))
        if qn > before:
            picked += 1
            if picked >= 2:
                break

for g in gens:
    picked = 0
    for kws in CROSS_KW:
        before = qn
        add("필터교차", f"{kws[0]}·{kws[1]} 기준이 어떻게 되나요?",
            {"generation": g}, find_ids(where={"generation": g}, kws=kws))
        if qn > before:
            picked += 1
            if picked >= 2:
                break

for ins in insurers:
    for g in gens:
        w = {"insurer": ins, "generation": g}
        for kws in CROSS_KW:
            before = qn
            add("필터교차2중", f"{kws[0]}·{kws[1]}이 어떻게 되는지 알려주세요",
                w, find_ids(where=w, kws=kws))
            if qn > before:
                break

questions = questions[:MAX_TOTAL]
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(questions, f, ensure_ascii=False, indent=1)

sizes = sorted(len(q["answer_ids"]) for q in questions)
print(f"생성 문항: {len(questions)}개 -> {OUTPUT}")
print("유형 분포:", dict(Counter(q["type"] for q in questions)))
print(f"정답 청크 수: 중앙값 {sizes[len(sizes) // 2]}, 최소 {sizes[0]}, 최대 {sizes[-1]}")