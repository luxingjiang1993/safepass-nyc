#!/usr/bin/env bash
# 发布 Phase 3 波 1 票据到 GitHub Issues（依赖序 = 文件编号序，blockers 先建）
# 前置：gh auth login 已有效。用法：bash .scratch/safepass-phase3-tickets/publish.sh
set -euo pipefail
cd "$(dirname "$0")"

REPO=$(git remote get-url origin | sed -E 's#.*github\.com[:/](.+)\.git#\1#')
echo "repo = $REPO"

declare -A NUM   # NN -> issue number
declare -A DBID  # NN -> database id

# 1) 逐票建 issue（编号序 = 依赖序）
for f in issues/[0-9][0-9]-*.md; do
  nn=$(basename "$f" | cut -c1-2)
  title=$(head -1 "$f" | sed 's/^# [0-9]* — //')
  out=$(gh issue create --repo "$REPO" --title "[Phase3] $title" \
        --body-file "$f" --label "ready-for-agent")
  num=${out##*/}
  NUM[$nn]=$num
  DBID[$nn]=$(gh api "repos/$REPO/issues/$num" --jq .id)
  echo "created #$num ($nn) [ready-for-agent]"
done

# 2) 原生阻塞边：blocked_by 需要 blocker 的 database id（不是 #number）
edge() { # $1 = blocker NN, $2 = dependent NN
  gh api --method POST "repos/$REPO/issues/${NUM[$2]}/dependencies/blocked_by" \
    -F issue_id="${DBID[$1]}" >/dev/null && echo "edge: $1 -> $2"
}
edge 01 02  # A1 -> A2
edge 01 04  # A1 -> B1
edge 02 04  # A2 -> B1
edge 02 09  # A2 -> N1
edge 01 08  # A1 -> E1
edge 04 05  # B1 -> B2

echo "ALL DONE. issue numbers: ${NUM[*]}"
