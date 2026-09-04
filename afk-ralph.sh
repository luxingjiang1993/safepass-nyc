#!/bin/bash
# afk-ralph.sh — Matt Pocock 版 Ralph 自治循环
# 用法: ./afk-ralph.sh "<任务描述>" [max_iterations]
# 默认迭代上限 10；收到 <promise>COMPLETE</promise> 即退出；
# 超限未达标 = 优雅失败（停止烧 token，交回人工，状态已留在 progress.txt / RALPH.md）。

set -e

PROMPT="$1"
MAX_ITERATIONS="${2:-10}"

if [ -z "$PROMPT" ]; then
  echo "Usage: ./afk-ralph.sh \"<任务描述>\" [max_iterations]" >&2
  exit 1
fi

ITERATION=0

# 可选预算熔断：token-budget.json 存在则读取 max_iterations 覆盖
if [ -f token-budget.json ]; then
  BUDGET_MAX=$(grep -o '"max_iterations"[^,}]*' token-budget.json | grep -o '[0-9]*' | head -1)
  if [ -n "$BUDGET_MAX" ] && [ "$BUDGET_MAX" -lt "$MAX_ITERATIONS" ]; then
    MAX_ITERATIONS="$BUDGET_MAX"
    echo "Budget fuse: iteration cap lowered to $MAX_ITERATIONS (token-budget.json)"
  fi
fi

while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
  echo ""
  echo "############ AFK-RALPH ITERATION $((ITERATION + 1)) / $MAX_ITERATIONS ############"
  OUTPUT=$(./ralph-once.sh "$PROMPT" || true)

  if echo "$OUTPUT" | grep -q "COMPLETE: promise sigil received"; then
    echo ""
    echo "AFK Ralph finished after $((ITERATION + 1)) iterations."
    exit 0
  fi

  ITERATION=$((ITERATION + 1))
done

echo ""
echo "############ ELEGANT FAILURE ############"
echo "Did not complete after $MAX_ITERATIONS iterations."
echo "State preserved in progress.txt — resume manually with ./ralph-once.sh, or investigate before re-running."
exit 1
