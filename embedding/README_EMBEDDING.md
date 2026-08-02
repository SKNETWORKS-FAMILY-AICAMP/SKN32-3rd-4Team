# 임베딩 모델 선정 · 색인 — 인수인계

작성: 2026-08-02. 전처리 완료본(chunks_main/terms)을 입력으로,
임베딩 모델 6종을 비교 선정하고 전체 벡터DB 색인까지 완료한 단계의 기록.

---

## 1. 한 줄 요약

**multilingual-e5-large 선정** (hit@5 92%, hit@1 74%, MRR 0.811로 6모델 중
전 지표 1위). 전체 231,270 본문청크 + 4,146 용어청크를 Chroma 2컬렉션
(policy_e5 / terms_e5)에 색인 완료. GPU(RTX 3060 Ti) 기준 색인 약 50분.

확정 설정과 검색 함수는 **`rag_config.py` 한 파일에만** 존재한다.
모델명·경로·접두사를 다른 코드에 하드코딩하지 말고 이 모듈을 import할 것.

---

## 2. 공유 폴더 구조

```
embed-share\
├─ rag_config.py              ★ 확정 설정 + 검색 모듈 (단일 출처)
├─ README_EMBEDDING.md        ← 이 문서
├─ requirements.txt
├─ 1_data_prep\
│   └─ prep_new.py            (dedup + cid제거 + 512분할) — rag_config 참조
├─ 2_model_select\
│   ├─ sample_chunks.py       (평가 샘플 추출)
│   ├─ gen_questions.py       (평가 문항 자동 생성)
│   ├─ embed_eval.py          (6모델 비교 실행기 — 모델 자유 등록형)
│   ├─ analyze_results.py     (hit@1/5, MRR 집계)
│   └─ eval_questions_v4.json (80문항 평가셋)
├─ 3_index\
│   └─ build_index.py         (2컬렉션 색인, 이어하기 지원) — rag_config 참조
└─ results\
    └─ results_*.csv          (6모델 × 80문항 결과 원본)
```

- **구조 원칙**: 모델 선정은 `2_model_select`(어떤 모델이든 등록해 비교),
  선정 결과 확정은 `rag_config.py`(한 곳), 나머지는 전부 그걸 참조.
  모델이 바뀌면 rag_config 상단 한 줄만 수정하면 전체 반영된다.
- **실행 규칙**: 모든 스크립트는 embed-share **루트에서** 실행
  (`python 3_index\build_index.py` 형식). 스크립트에 경로 보정이 들어있어
  하위 폴더에서 실행해도 동작은 하지만, 루트 실행을 표준으로 한다.
- 벡터DB 본체(`chroma_full`, 약 2GB)는 zip에 미포함 — 드라이브로 별도 전달.
  받으면 embed-share 루트에 두면 되고, 색인 50분을 생략하고 바로 검색 가능.
- venv / data(원본 jsonl) / __pycache__ 는 공유 대상 아님.
  환경은 requirements.txt로 각자 재현.

---

## 3. 모델 비교 결과 (80문항, 동일 샘플 1,433청크)

| 순위 | 모델 | hit@5 | hit@1 | MRR | 비고 |
|---|---|---|---|---|---|
| 1 | **e5-large** | **92%** | **74%** | **0.811** | 선정. MIT 라이선스, 무료 |
| 2 | bge-m3 | 90% | 71% | 0.778 | GPU 필수급 (CPU 40배 느림) |
| 3 | kure-v1 | 86% | 65% | 0.737 | 한국어 검색 특화 |
| 4 | ko-sroberta | 85% | 64% | 0.717 | 최경량(440MB), CPU 가능 |
| 5 | qwen3-embed-0.6b | 82% | 51% | 0.633 | |
| 6 | openai-3-small | 85% | 44% | 0.582 | 유일한 유료. hit@1 최하위 |

- 문항 5유형: 조항지정 / 구어체 / 표숫자 / 필터교차 / 필터교차2중(보험사×세대)
- 지표: hit@5(top-5 내 정답), hit@1(top-1이 정답), MRR(평균역순위 — 정답을
  얼마나 위에 올리는가)
- 원본 CSV: `results\` 폴더. 지표 재계산: `analyze_results.py`
- **소표본 주의**: 8→12→18문항까지는 선두가 계속 바뀜(bge→kure→e5).
  80문항에서야 순위 안정화. 소표본으로 결론 내리지 말 것.

---

## 4. 선정 근거 (요약)

1. **3지표 전부 1위.** 특히 hit@1(top-1 정확도) 격차가 큼 — top-3만 LLM에
   넘기는 실서비스 구성에서 hit@1이 실질 품질을 좌우.
2. **무료 오픈소스(MIT) + 로컬 실행** = 비용 0, 민감정보(의료·보험) 외부
   전송 없음.
3. **openai-3-small(유료 API)이 hit@1 44%로 최하위** — hit@5는 85%인데
   hit@1이 낮음 = "정답을 찾긴 하나 1등으로 못 올림". "유료 API가 당연히
   낫다"는 가정이 실측으로 반박됨. 직접 테스트의 가치.

---

## 5. rag_config.py — 확정 설정 · 검색 모듈

이 파일이 프로젝트의 공식 설정이다. 주요 내용:

```python
EMBED_MODEL = "intfloat/multilingual-e5-large"   # 확정 임베딩 모델
QUERY_PREFIX = "query: "        # e5 필수 접두사 (검색)
PASSAGE_PREFIX = "passage: "    # e5 필수 접두사 (색인)
DB_PATH = <embed-share 루트>/chroma_full          # 절대경로 자동 계산
COLL_MAIN = "policy_e5"         # 본문+표 컬렉션
COLL_TERMS = "terms_e5"         # 용어 정의 컬렉션
```

제공 함수:

```python
from rag_config import search, search_terms

# 본문 검색 — 보험사/세대 메타필터는 인자로 (내부에서 $and 자동 처리)
hits = search("통원 공제금액은?", insurer="삼성화재", generation="4세대")
for h in hits:
    print(h["insurer"], h["generation"], h["citation"], h["text"][:80])

# 용어 정의 검색 ("~란?", "~의 정의" 류 질문)
hits = search_terms("진단계약이란?")
```

내장된 실수 방지 장치 (신규 코드 작성 시 직접 구현하지 말 것):
- query/passage 접두사 자동 부착
- 다중 메타필터의 Chroma `$and` 문법 자동 처리
- 동일 (내용, 보험사, 세대) 중복 결과 자동 접기

동작 확인(자가 테스트): 루트에서 `python rag_config.py`
→ 삼성 검색 3건 + 용어 2건이 출력되면 정상.

---

## 6. e5-large 사용 시 반드시 지킬 것

- **접두사 필수**: 문서 임베딩엔 `passage: `, 질문엔 `query: `.
  빼먹으면 에러 없이 성능만 조용히 떨어짐. rag_config의 search 함수를
  쓰면 자동 처리되므로 **직접 encode 하지 말고 rag_config를 쓸 것**.
- **512토큰 입력 제한**: 초과분은 무시(절단)됨. 색인 전 분할 필요 →
  prep_new.py가 자동 처리.
- 모델 크기 약 2.2GB, 첫 실행 시 Hugging Face에서 자동 다운로드.
- 색인은 GPU 권장 (실측: 1,433청크 기준 GPU 38초 vs CPU 25분 — 약 40배 차).
  검색(질의) 시점엔 질문 1개만 임베딩하므로 CPU로도 충분.

---

## 7. 데이터 정제 파이프라인 (1_data_prep\prep_new.py)

전처리 산출물(chunks_main/terms.jsonl)에 색인 전 처리를 적용:

| 처리 | 이유 | 규모(현 4개사 데이터) |
|---|---|---|
| 중복 제거 + ID충돌 해시분리 | chunk_id 유일성 확보 (벡터DB 덮어쓰기·top-k 도배 방지) | 중복 9,990 제거, 5,275 ID변경 |
| (cid:) 깨진 청크 제거 | 폰트 손상 PDF 잔재 — 검색 무의미, LLM 오염 | 252 제거 |
| 512토큰 초과 분할 | e5 입력 한도. 표는 헤더 행 복제 후 분할 | 5,505 분할 |
| 쓰레기 조각 제거 | 페이지번호(`3 / 154`)·기호 조각(`)`, `】`) | 1,466 제거 |

데이터 흐름: 원본 238,028 → 최종 231,270 (main).
**새 데이터가 오면 같은 스크립트를 그대로 재실행하면 됨.**

---

## 8. 색인 구조 (chroma_full)

- **policy_e5**: 본문+표 231,270청크.
  메타: insurer / generation / content_type / citation / doc_name
- **terms_e5**: 용어정의 4,146청크 (용어 1개당 1청크).
  메타에 `term` 필드 — "~란?", "~의 정의" 류 질문 라우팅용
- 검색 시 **insurer/generation 메타필터 필수** (설계 결정: 보험사·세대 간
  격리 — 동일 제목 조항도 회사·세대별 숫자가 다름)
- build_index.py는 **이어하기 지원** — 중단돼도 재실행하면 이미 색인된
  청크는 스킵. 진행 확인: `python 3_index\build_index.py --status`

---

## 9. 재현 방법

```powershell
# 0. 환경 (컴퓨터마다 각자 생성 — venv는 공유되지 않음)
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# GPU 사용 시 torch 재설치 (requirements.txt 주석 참조):
#   pip uninstall torch -y
#   pip install torch --index-url https://download.pytorch.org/whl/cu126

# 1. 데이터 준비: data\ 폴더를 만들어 chunks_main.jsonl, chunks_terms.jsonl 배치
python 1_data_prep\prep_new.py

# 2. 색인 (GPU 권장, 약 50분. chroma_full 폴더를 전달받았다면 생략)
python 3_index\build_index.py
python rag_config.py               # 검증 (자가 테스트)

# (선택) 모델 비교를 재현하려면 2_model_select\ 를 순서대로:
python 2_model_select\sample_chunks.py
python 2_model_select\gen_questions.py
python 2_model_select\embed_eval.py --models e5-large --questions eval_questions_v4.json
python 2_model_select\analyze_results.py
```

---

## 10. requirements.txt

```
# 임베딩 파이프라인 공통 (필수)
torch                   # GPU면 별도 설치 — 아래 주석 참조
sentence-transformers   # e5-large 실행
transformers            # prep_new.py 토크나이저 (512토큰 검사·분할)
chromadb                # 벡터DB

# 모델 비교 재현 시에만 필요 (선택)
openai                  # openai-3-small 비교용 (API 키 필요)

# [GPU 설치 안내] pip install torch 는 CPU 버전이 설치됨.
# NVIDIA GPU 사용 시 아래로 별도 설치 (requirements 설치 후 실행):
#   pip uninstall torch -y
#   pip install torch --index-url https://download.pytorch.org/whl/cu126
```

---

## 11. 알려진 이슈 / 다음 단계

1. **새 전체 데이터(PDF 1,858건, 약 2배) 입고** → 전처리 후 재색인 예정.
   모델(e5)은 유지하되, 신규 보험사 포함이므로 2_model_select 재실행으로
   선정 재검증 권장 (자동화돼 있어 반나절 소요).
2. **terms에 없는 용어 질문 시 유사 용어가 오답으로 검색됨** (예: "면책기간"
   질문 → "보험기간" 정의 반환). LLM 단계의 근거-질문 불일치 거부로 방어
   확인됨 (GPT-4.1, Qwen3 모두 함정 문항 통과).
3. **"긍정형 질문 ↔ 면책 조항" 매칭 약함** ("비만도 보장되나요?" → 보상하지
   않는 사항 조항을 못 찾음). LLM 단계에서 질문 재작성(query rewriting) 검토.
4. **LLM 선정 테스트 진행 중** — GPT-4.1 vs Qwen3 8B. 6문항 기준선: 두 모델
   동일 O/X 패턴(품질 대등, Qwen 3~8배 느림). 정식 30문항 평가 예정.
5. 판본 중복 40개 doc_id (같은 상품 총페이지 다른 두 파일) — 크롤 목록 대조
   후 구판 제외 여부 팀 결정 필요.

---

## 12. 환경 주의사항

- Windows + PowerShell + PyCharm 기준.
- 대용량 jsonl은 한 줄 스트리밍 처리 (전체 메모리 로드 금지).
- 코드 전달은 채팅 코드블록 → PyCharm 새 파일에 붙여넣기 (터미널 붙여넣기
  금지 — 파일 깨짐 사고 이력 있음). 붙여넣은 후 줄 수·문법 검증.
- zip 파일명·내부 파일명은 영문만 (한글 파일명 zip은 Windows에서 안 풀림).
- venv·chroma_full·data 는 zip에 넣지 말 것 (2절 참조).
- GPU 사용 전 확인: `python -c "import torch; print(torch.cuda.is_available())"`
  → False면 CUDA 버전 PyTorch 재설치 필요 (10절 주석 명령).
- 폴더명이 숫자로 시작하므로(1_data_prep 등) 파이썬 패키지 import는 불가 —
  `__init__.py` 를 넣지 말 것. 공통 코드는 루트의 rag_config.py 만 사용.[.gitignore](../.gitignore)