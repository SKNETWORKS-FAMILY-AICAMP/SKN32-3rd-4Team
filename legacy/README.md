# 레거시 보관소

이 저장소는 쇼핑몰 실습(`_unified_mall`)에서 출발해 **보험 보장 판정**으로 전환됐다.
여기는 그 과정에서 쓰이지 않게 된 것들을 **버전별 압축본**으로 모아 둔 자리다.

## ★압축해서 보관하는 이유

**현행 코드가 레거시를 참조하면 레거시를 지울 수 없게 된다.**

한 번 그런 일이 있었다 — 커머스 시딩 CSV 를 여기로 옮기고
`settings.LEGACY_DATA_DIR` 을 만들어 현행 코드가 그걸 읽게 했다.
그러면 "레거시"가 아니라 **그냥 다른 폴더에 있는 현행 코드**다.

그래서 **압축본으로만 둔다.** `import` 도, 파일 경로 참조도 불가능하다.
레거시 폴더를 통째로 지워도 현행 프로젝트는 그대로 돈다.

## 보관물

| 파일 | 내용 |
|---|---|
| `v3_commerce.zip` | 쇼핑몰 실습(`_unified_mall` ~ `_unified_mall_2`) 잔재 |
| `v4_extract.zip` | 전처리 v4 당시의 `to_page_json.py`·`to_clauses.py` |
| `v5_commerce_ui.zip` | 쇼핑·주문·MCP·화상상담 정적 화면 잔재 |
| `v6_rag_ui.zip` | 활성 static에서 제거한 커머스 RAG 화면 `rag.html`·`rag.js` |
| `v7_lab_experiments.zip` | 보험 제품 경로와 분리된 프롬프트·프로토콜 Lab API와 단위 테스트 |
| `v8_mall_db.zip` | `data/mall.db` 빈 SQLite 파일의 제거 직전 스냅샷(원래 상대 경로 보존) |
| `v9_commerce_seed_cli.zip` | 활성 트리에서 제거한 커머스 CSV 시더와 제거 직전 관리 CLI |
| `v10_publish_github.zip` | `scripts/publish_github.sh` **수정 직전 스냅샷**(2026-08-05). 아래 참조 |

### `v10_publish_github.zip` — 왜 여기 있나

★**이건 폐기물이 아니다.** 원본은 `scripts/publish_github.sh` 에 **그대로 살아 있고**,
이 압축본은 손대기 전 상태를 남긴 것이다(RULE.md §4 "대체/삭제하기 직전").

sha256 `7dee55daddc7f49b5169…` · 원본과 바이트 단위 일치 확인.

**남긴 이유** — 이 스크립트에는 재현할 때 쓸 것이 들어 있다.

- 민감파일 게이트(`.env`·`프로젝트설명`·`RULE.md` 발견 시 **중단**)
- `Co-Authored-By` 제거 **잔여 0 검증** — 실패하면 푸시하지 않음
- `--dry-run` · 미커밋 변경 경고(subtree split 은 커밋된 것만 가져간다)

**고칠 부분** — 팀 레포에 쓰면 안 되는 것 둘.

- `git push --force HEAD:main` — 공유 브랜치 강제 푸시
- `filter-branch` 로 작성자명 `Your Name` → `roroblack` 치환.
  실제 작성자가 아니면 **저자 정보 위조**이고 공유된 이력의 해시를 바꾼다.

상수 3개도 옛 개인 레포(`roroblack/unified_mall_2`)를 가리킨다.
2026-08-05 팀 레포 푸시에 실제로 쓴 방법은 **force push 가 아니라**
`subtree split → 원격 tip 과 tree 동일 지점 확인 → cherry-pick → fast-forward` 였다.

### `v3_commerce.zip` 안에 든 것

```
app/routers/     products · orders · payments · agent · nlp · mcp · a2a
app/tools/       commerce_tools.py
app/application/ commerce.py
app/adapters/    sql_order_repo · sql_catalog
app/services/    payment · order · catalog
app/schemas/     commerce.py       ← 인증 DTO 만 app/schemas/auth.py 로 분리해 남김
app/ml/          recommend.py
app/agent/       lc_agent · lc_tools · react
app/mcp/         server.py
app/a2a_old/     ★이름만 A2A 인 커머스 잔재. 표준 A2A 가 아니다
static/          shop · orders · index · mcp 화면
data/            mall.db · products.csv · orders.csv · inventory.csv · cs_inquiries.csv
tests/           커머스 테스트 17개
```

## 되살리려면

```bash
cd legacy && unzip v3_commerce.zip
```

그리고 필요한 것을 `app/` 아래로 옮긴 뒤 `app/main.py` 에서 `include_router` 한다.
**다만 되살리기 전에 왜 뺐는지 먼저 읽으라.**

`v6_rag_ui.zip`은 내부에 원본 프로젝트 경로
`_unified_mall/app/static/rag.html`·`rag.js`를 그대로 보존한다. 현행 코드는 이 압축본을
import하거나 파일 경로로 읽지 않는다.

`v7_lab_experiments.zip`은 `app/lab/`, `app/routers/lab.py`, `tests/test_lab.py`의
저장소 상대 경로를 그대로 보존한다. 격리 전 기준선은 10개 테스트 전부 통과였다.

`v8_mall_db.zip`은 `data/mall.db`를 원래 상대 경로 그대로 담는다. 보관 당시 파일은
0바이트였으며 데이터나 SQLite 스키마가 들어 있지 않았다. 복원이 필요하면 실행 중인 앱을
먼저 종료한 뒤 저장소 루트에서 아래 명령을 실행한다.

```powershell
Expand-Archive -LiteralPath legacy\v8_mall_db.zip -DestinationPath . -Force
```

현재 기본 설정은 `data/db/insurance.sqlite3`를 가리킨다. 이 과거 파일을 복원해 사용하려면
`DATABASE_URL`을 명시적으로 `sqlite:///./data/mall.db`로 지정해야 한다.

`v9_commerce_seed_cli.zip`은 `app/db/seed.py`와 제거 직전 `scripts/manage.py`를 원래 상대
경로로 보존한다. 현행 보험 애플리케이션은 `products.csv`·`inventory.csv`를 요구하지 않으며,
활성 `scripts.manage`에는 커머스 `seed` 명령이 없다. 과거 커머스 데모를 복원할 때만
`v3_commerce.zip`의 CSV와 함께 별도 작업 트리에 푼다.

## 남겨 둔 것 (옮기지 않음)

`app/db/models.py` 에는 아직 커머스 테이블이 있지만 인증·감사 등 현행 코드가 같은 파일을 쓴다.
분리는 백엔드 담당이 보험 DB 스키마를 새로 짤 때 함께 한다.
