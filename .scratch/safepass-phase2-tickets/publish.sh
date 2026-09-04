#!/usr/bin/env bash
# 发布 Phase 2 票据到 GitHub Issues（依赖序 = 文件编号序，blockers 先建）
# 前置：gh auth login 已有效。用法：bash .scratch/safepass-phase2-tickets/publish.sh
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
  label="ready-for-agent"
  grep -q "ready-for-human" "$f" && label="ready-for-human"
  out=$(gh issue create --repo "$REPO" --title "[Phase2] $title" \
        --body-file "$f" --label "$label")
  num=${out##*/}
  NUM[$nn]=$num
  DBID[$nn]=$(gh api "repos/$REPO/issues/$num" --jq .id)
  echo "created #$num ($nn) [$label]"
done

# 2) 原生阻塞边：blocked_by 需要 blocker 的 database id（不是 #number）
edge() { # $1 = blocker NN, $2 = dependent NN
  gh api --method POST "repos/$REPO/issues/${NUM[$2]}/dependencies/blocked_by" \
    -F issue_id="${DBID[$1]}" >/dev/null && echo "edge: $1 -> $2"
}
edge 01 02; edge 01 03; edge 02 04; edge 03 04
edge 05 07
edge 08 11; edge 10 11
edge 06 12
edge 12 14; edge 13 14
edge 14 15; edge 07 15; edge 08 15

echo "ALL DONE. issue numbers: ${NUM[*]}"
