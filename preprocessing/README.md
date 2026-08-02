# 실손보험 약관 전처리 파이프라인 — 실행 가이드

RAG QA 시스템용 전처리 코드. 약관 PDF에서 **조(條)/항(①)/호(1., 가.)** 계층을
살려 청킹하고, 표와 용어 정의까지 추출해 임베딩 입력 2개 파일을 만든다:
**`chunks_main.jsonl`(본문+표) / `chunks_terms.jsonl`(용어 정의)**.

---

## 1. 파일 구성과 용도

### 파이프라인 코드 (5개 — 반드시 같은 폴더에)

| 파일 | 용도 |
|---|---|
| `clause_detector.py` | **조항 헤더 검출기.** `제N조(제목)` 표준형 + DB 번호점형(`38. (제목)`) + NH 대괄호형(`제N조【제목】`) + 제목 줄바꿈 인식. 항(①)/호(1./가./1)) 계층 파싱, DB의 PUA 특수글리프(󰊱→①) 정규화, 법령 인용 오탐 필터, 사업방법서(비약관) 판별, 겹침-글리프 중복 정제. 다른 모듈이 전부 이걸 import 함 |
| `doc_processor.py` | **문서 1건 처리기.** PDF 텍스트를 2가지 모드(스트림/좌표정렬)로 뽑아 조항이 잘 살아나는 쪽 자동선택 → 클리닝(페이지번호·목차 제거) → 조 경계로 자르고 **항 단위 청킹**(1,500자 초과 시 호 경계 분할) → 조/항/호 메타데이터 부착 → 문서별 품질지표 산출. 요약서·팁박스 같은 비조항 텍스트가 조에 섞이는 것 차단 |
| `batch_runner.py` | **일괄 실행기(메인 진입점).** documents.csv에서 처리대상(main+coverage_rider)을 골라 전체 문서를 처리. 삼성 분권(file1/2/3)을 상품코드로 묶어 병합, 품질 리포트·실패 목록 생성 |
| `table_extract.py` | **표 추출기.** pdfplumber로 선(격자) 기반 표를 뽑아 마크다운으로 직렬화, 같은 페이지의 조항에 연결(`제N조(...) [표]`). `--tables` 옵션을 줄 때만 동작 |
| `clean_chunks.py` | **정제 (v2).** ① 인코딩 깨진 문서(삼성 95683)·비약관(동양 사업방법서) 제외 ② 초미세 조각(조 제목 줄바꿈 꼬리, 20자 미만) 제거 ③ 부분 깨진 표(폰트 CID 미해석 `(cid:...)`) 제거 → `chunks_clean.jsonl` |
| `make_term_chunks.py` | **용어 분해 (v2).** 용어정의표를 **용어 1개당 1청크**(content_type=`term`)로 분해. 문서 내 중복 제거, 숫자 노이즈 필터, `term_key`(공백 제거 정규화)·`term_quality` 필드 부여 → `chunks_final.jsonl` |
| `split_terms.py` | **파일 분리.** 본문+표(`chunks_main.jsonl`)와 용어(`chunks_terms.jsonl`)로 분리 — 벡터DB에 별도 컬렉션으로 적재하기 위함 |
| `check_quality.py` | **품질 감사.** 최종 산출물 전수 검사(chunk_id 중복, 빈/미세 청크, 인코딩, 표 상태). 마지막에 실행해 `chunk_id 중복: 0` 확인용 |
| `fix_ids.py` | **(일회성 교정)** 구버전 batch_runner로 만든 기존 chunks_all의 chunk_id 충돌을 재부여. **처음부터 새로 돌리는 사람은 필요 없음** (batch_runner에 수정 반영됨) |

### 입력으로 필요한 것 (기존 팀 산출물)

- `documents.csv` — `identify_documents.py`(기존 코드)가 매니페스트에서 생성.
  필요 컬럼: file(파일명)/insurer/product_code/product_name/generation/category
- 약관 PDF 폴더 — 예: `raw\insurance_terms\` (하위 dbins/samsungfire/... 자동 탐색)

---

## 2. 사전 준비

```powershell
pip install pymupdf pdfplumber
```

파이썬 3.10+ 권장. 코드 5개는 같은 폴더에 두고, 그 폴더에서 실행한다.
(폴더 이름은 무관. 단 `clean_chunks.py`는 `out\` 폴더가 보이는 위치에서 실행)

---

## 3. 실행 순서

### ① documents.csv 준비 (이미 있으면 생략)

```powershell
python identify_documents.py <매니페스트 경로>    # 기존 팀 코드
```

### ② 빠른 검증 — 본문만 3건 (약 1분)

경로·컬럼이 맞는지 먼저 확인:

```powershell
python batch_runner.py --csv documents.csv --pdfdir <PDF루트> --out out --limit 3
```

`처리대상 N건 → 병합 후 M문서 (파일없음 K건)` 로그 확인.
파일없음이 많으면 documents.csv의 파일명과 실제 PDF가 안 맞는 것 → `out\missing_files.csv` 확인.

### ③ 전체 실행 — 표 포함 (약 1시간)

```powershell
python batch_runner.py --csv documents.csv --pdfdir <PDF루트> --out out --tables
```

- `--tables` 빼면 본문만 몇 분 만에 끝남(표 청크 없음)
- 실행 중 `Cannot set non-stroke color...` 경고는 무해함(일부 PDF의 색상 정의 문제, 결과 무관)

### ④ 정제 — 깨진 문서 제외 (몇 초)

```powershell
python clean_chunks.py
```

### ⑤ 용어정의표 분해 (몇 초)

```powershell
python make_term_chunks.py
```

붙임/별표의 용어정의표를 용어별 청크로 분해 (`[용어] 진단계약: ...` 형태,
citation="용어의 정의 - 진단계약").

### ⑥ 본문/용어 파일 분리 (몇 초)

```powershell
python split_terms.py
```

→ **`out\chunks_main.jsonl` + `out\chunks_terms.jsonl` 이 임베딩 단계 입력 최종본**

### ⑦ 품질 감사 (1분 내)

```powershell
python check_quality.py
```

`chunk_id 중복: 0` 이면 통과. "인코딩 의심" 수백 건은 본문에 소비자포털 URL이
포함된 정상 청크(오탐)이므로 무시. 정상 완료 기준 수치:
**main 228,841 (본문 221,513 + 표 7,328) / terms 4,146**

### 이미 전처리를 돌려놓은 경우 (재생성 — 배치 재실행 불필요, 몇 분)

구버전 코드로 `out\chunks_all.jsonl`까지 만들어 둔 상태라면, 최신 코드로
교체한 뒤 아래만 순서대로 실행:

```powershell
python fix_ids.py            # chunk_id 충돌 재부여 (일회성)
python clean_chunks.py
python make_term_chunks.py
python split_terms.py
python check_quality.py
```

### ⑧ 결과 확인

```powershell
# 문서별 요약
Import-Csv out\quality_report.csv | Format-Table doc_name,style,n_clauses,n_paragraphs,n_tables,coverage_pct,status

# 실패 목록 (비약관·소형특약·인코딩 문제)
Import-Csv out\failures.csv | Format-Table doc_name,insurer,fail_reason

# 청크 유형 집계
python -c "import json; c=[json.loads(l) for l in open('out/chunks_clean.jsonl',encoding='utf-8')]; from collections import Counter; print(Counter(x['content_type'] for x in c))"
```

---

## 4. 출력물

| 파일 | 내용 |
|---|---|
| `out\chunks_main.jsonl` | **최종 — 본문+표 청크 228,841개(임베딩 입력).** 1줄=1청크 JSON |
| `out\chunks_terms.jsonl` | **최종 — 용어 정의 청크 4,146개(v2: term_key 정규화·중복 제거·노이즈 필터, 별도 컬렉션 권장)** |
| `out\chunks_all / chunks_clean / chunks_final.jsonl` | 중간 산출물(임베딩에 쓰지 말 것) |
| `out\quality_report.csv` | 문서별 품질지표 |
| `out\failures.csv` | 임계 미달/비약관 문서 (청크는 chunks_all에 포함돼 있음 — 배제 아님, 검토 표시) |
| `out\errors.csv`, `out\missing_files.csv` | 처리 에러 / 파일 못 찾은 목록 |

### 청크 메타 스키마 (1청크)

```json
{
  "insurer": "삼성화재", "generation": "4세대", "doc_name": "...",
  "article_no": 4, "article_title": "보상하지 않는 사항",
  "paragraph_no": 1, "item_no": null, "item_list": "1;2;3;4;5;6;7",
  "citation": "제4조(보상하지 않는 사항) 제1항",
  "section": "본문", "content_type": "clause",
  "page": 12, "chunk_id": "ZPB293020#00042::제4조...", "text": "..."
}
```

- `citation` → 답변에 출처 표시용. `article_no`+`paragraph_no`+`item_no` → 조·항·호 정밀 필터
- `content_type` → `clause`(본문) / `table`(표, 마크다운) / `term`(용어 정의)
- term 청크는 `term` 필드 추가: `{"term": "진단계약", "citation": "용어의 정의 - 진단계약",
  "text": "[용어] 진단계약: 계약을 체결하기 위하여 ..."}` — "~란?" 류 질문 라우팅용
- 검색 시 `insurer`/`generation` 메타필터로 보험사·세대 간 혼선 방지 (설계 원칙)

### 품질 리포트 주요 컬럼

`style`(jo=제N조형/num=DB번호점형), `n_clauses`(조 수), `n_paragraphs`(항 수),
`n_items`(호 수), `n_tables`(표 청크), `coverage_pct`(본문 커버리지),
`front_matter_pct`(서문·목차 비중), `status`/`fail_reason`

---

## 5. 옵션 정리 (batch_runner.py)

| 옵션 | 설명 |
|---|---|
| `--csv` | documents.csv 경로 |
| `--pdfdir` | PDF 루트 폴더(하위 폴더 자동 탐색) |
| `--out` | 출력 폴더 (기본 `out`) |
| `--limit N` | 앞 N건만 처리 (디버그) |
| `--tables` | 표 추출 포함 (느림) |

※ `--extradir`(수동 다운로드 PDF 추가) 옵션도 코드에 있으나, 현재는 크롤 데이터만
쓰기로 결정해 사용하지 않음.

---

## 6. 알려진 이슈 / 열린 판단사항 (피드백 요청)

1. **DB 중지·재개 특약 9건이 FAIL 라벨** — 조항 4개짜리 정상 특약인데
   임계(main은 조항 ≥5)에 걸림. category를 coverage_rider로 재분류할지,
   임계를 낮출지 결정 필요. 청크 자체는 정상 생성돼 있음.
2. **삼성 95683(1301.1) 인코딩 깨짐** — 폰트 손상으로 텍스트가 모지바케.
   OCR로 살릴지 제외 유지할지. (현재 clean_chunks에서 제외)
3. **목(目) 단위**(`가)`, `(1)`)는 메타 분리 없이 텍스트로만 보존 — 필요성 검토.
4. DB손보는 항 마커가 문장 중간 인라인인 경우가 있어 일부 항 분리가 덜 정밀.
5. 표 추출은 선(격자) 있는 표만 — 선 없는 표는 미지원(text-strategy는 속도 문제로 제외).