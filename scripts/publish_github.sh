#!/usr/bin/env bash
# _unified_mall_2 를 전용 GitHub 레포로 배포한다.
#
# 이 프로젝트는 여러 실습이 함께 있는 모노레포(llm_workspace) 안에 살지만, 공개 레포는
# 이 폴더만 담는다. 그래서 배포는 매번 세 단계를 거쳐야 하는데 손으로 하면 빠뜨리기 쉽다.
#   1) subtree split — _unified_mall_2 만의 커밋 이력을 별도 브랜치로 추출(이력 보존)
#   2) 커밋 메시지에서 Claude 공동저자 표기 제거 + 작성자명 통일
#   3) 원격 main 으로 푸시
#
# 왜 임시 클론에서 필터링하나: git filter-branch 는 깨끗한 작업트리를 요구한다. 모노레포에는
# 다른 프로젝트의 미커밋 변경이 늘 있어서 그 자리에서 돌리면 거부된다. 그래서 커밋된 ref만
# 복제해 가는 임시 클론에서 이력을 고친다 — 원본 작업트리는 건드리지 않는다.
#
# 사용법:
#   bash scripts/publish_github.sh            # 배포
#   bash scripts/publish_github.sh --dry-run  # 무엇이 올라갈지만 확인(푸시 안 함)
#
# 주의: 표기 제거로 커밋 해시가 모노레포와 달라지므로 원격에는 force push 한다.
#       이 레포는 이 스크립트로만 갱신한다는 전제다(원격에서 직접 커밋하지 말 것).

set -euo pipefail

PREFIX="_unified_mall_2"
BRANCH="unified-mall-2"
REMOTE_URL="https://github.com/roroblack/unified_mall_2.git"
AUTHOR_NAME="roroblack"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# 모노레포 루트로 이동(이 스크립트는 _unified_mall_2/scripts 안에 있다)
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
echo "[1/4] 모노레포 루트: $ROOT"

if [ ! -d "$PREFIX" ]; then
  echo "오류: $PREFIX 를 찾을 수 없습니다. 모노레포 루트에서 실행되는지 확인하세요." >&2
  exit 1
fi

# 미커밋 변경이 있으면 배포에 포함되지 않는다는 걸 알려준다(조용히 넘어가지 않음).
UNCOMMITTED="$(git status --porcelain -- "$PREFIX" | wc -l | tr -d ' ')"
if [ "$UNCOMMITTED" != "0" ]; then
  echo "경고: $PREFIX 에 커밋되지 않은 변경 $UNCOMMITTED 건이 있습니다."
  echo "      subtree split 은 **커밋된 것만** 가져가므로 이 변경은 배포에 포함되지 않습니다."
fi

echo "[2/4] subtree split — $PREFIX 이력을 $BRANCH 로 추출"
git branch -D "$BRANCH" >/dev/null 2>&1 || true
git subtree split --prefix="$PREFIX" -b "$BRANCH" >/dev/null
SPLIT_COMMITS="$(git rev-list --count "$BRANCH")"
echo "      커밋 $SPLIT_COMMITS 개"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null || true' EXIT

echo "[3/4] 임시 클론에서 공동저자 표기 제거 + 작성자명 통일"
git clone --quiet --no-local --branch "$BRANCH" --single-branch "$ROOT" "$TMP/repo"
cd "$TMP/repo"
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --msg-filter 'sed "/^Co-Authored-By: Claude/d"' \
  --env-filter "
    if [ \"\$GIT_AUTHOR_NAME\" = 'Your Name' ]; then export GIT_AUTHOR_NAME='$AUTHOR_NAME'; fi
    if [ \"\$GIT_COMMITTER_NAME\" = 'Your Name' ]; then export GIT_COMMITTER_NAME='$AUTHOR_NAME'; fi
  " -- --all >/dev/null 2>&1

LEFT="$(git log --format='%B' | grep -c '^Co-Authored-By: Claude' || true)"
if [ "$LEFT" != "0" ]; then
  echo "오류: 공동저자 표기가 $LEFT 건 남아 있습니다. 푸시를 중단합니다." >&2
  exit 1
fi
echo "      표기 제거 확인(잔여 0) · 작성자: $(git log -1 --format='%an')"

# 민감 파일이 섞여 들어가지 않았는지 확인한다(무폴백: 발견되면 중단).
BAD="$(git ls-tree -r --name-only HEAD | grep -E '(^|/)\.env$|프로젝트설명|(^|/)RULE\.md$' || true)"
if [ -n "$BAD" ]; then
  echo "오류: 공개하면 안 되는 파일이 포함돼 있습니다:" >&2
  echo "$BAD" >&2
  exit 1
fi
echo "      민감 파일 없음(.env / 프로젝트설명 / RULE.md)"

if [ "$DRY_RUN" = "1" ]; then
  echo "[4/4] --dry-run 이므로 푸시하지 않습니다."
  echo "      올라갈 최신 커밋:"
  git log --oneline -5 | sed 's/^/        /'
  exit 0
fi

echo "[4/4] 원격 push → $REMOTE_URL (main)"
git push --force --quiet "$REMOTE_URL" HEAD:main
echo "      완료: $(git rev-parse --short HEAD)"
echo
echo "확인: https://github.com/roroblack/unified_mall_2"
