#!/usr/bin/env bash
# 发布 Phase 4（作品集轴 = 波 2 第一刀）票据到 GitHub Issues。
# 前置：gh auth login 已有效。
# 用法：bash .scratch/safepass-phase4-tickets/publish.sh
#
# 已发布映射（勿重复 create）：
#   01 A4  -> #27
#   02 N2a -> #28
#   03 N2b -> #26  blocked_by #28
# 本脚本默认只校验三张票存在并打印映射。传 --force-create 才会再 create（会重复开票，禁止随手用）。
set -euo pipefail
cd "$(dirname "$0")"

REPO=$(git remote get-url origin | sed -E 's#.*github\.com[:/](.+)\.git#\1#' | sed 's#^git@github.com:##')
echo "repo = $REPO"

if [[ "${1:-}" == "--force-create" ]]; then
  echo "ERROR: 票已在 #27/#28/#26。禁止重复 create。改正文请 gh issue edit --body-file issues/NN-*.md" >&2
  exit 1
fi

echo "01 A4  -> #27  $(gh issue view 27 --repo "$REPO" --json title --jq .title)"
echo "02 N2a -> #28  $(gh issue view 28 --repo "$REPO" --json title --jq .title)"
echo "03 N2b -> #26  $(gh issue view 26 --repo "$REPO" --json title --jq .title)  blocked_by=#28"
echo "ALL DONE (already published)."
