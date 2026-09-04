#!/bin/bash
# ralph-once.sh — Matt Pocock 版 Ralph：人工在环单次迭代
# 用法: ./ralph-once.sh "<任务描述>"
# 任务源通常是当前 Phase 的 PRD.md 路径或一段任务描述。
# 跨迭代记忆 = progress.txt；完成信号 = 输出中的 <promise>COMPLETE</promise>

set -e

PROMPT="$*"

# Git Bash on Windows: resolve claude CLI（可用 CLAUDE_BIN 覆盖）
if [ -n "$CLAUDE_BIN" ]; then
  CLAUDE="$CLAUDE_BIN"
elif command -v claude >/dev/null 2>&1; then
  CLAUDE="claude"
elif command -v claude.cmd >/dev/null 2>&1; then
  CLAUDE="claude.cmd"
else
  echo "ERROR: claude CLI not found in PATH (tried claude, claude.cmd)." >&2
  echo "Set CLAUDE_BIN=/path/to/claude and retry." >&2
  exit 1
fi

# 追加跨迭代记忆
if [ -f progress.txt ]; then
  PROMPT="$PROMPT

<progress>
$(cat progress.txt)
</progress>"
fi

echo "=== Ralph iteration: invoking claude ==="
# headless -p 无人值守：文件编辑默认会被权限弹窗拒绝（无人可批），
# 故用 acceptEdits 自动批准编辑类权限；可用 PERM_MODE 覆盖。
OUTPUT=$("$CLAUDE" -p --permission-mode "${PERM_MODE:-acceptEdits}" "$PROMPT" </dev/null)
echo "$OUTPUT"

# 提取 promise：sigil 必须独占一行，防止匹配到散文/代码块里的字面量
PROMISE=$(echo "$OUTPUT" | grep -oE '^<promise>[^<]*</promise>[[:space:]]*$' | sed 's/<\/\?promise>//g' | head -1 || true)

if [ "$PROMISE" = "COMPLETE" ]; then
  echo ""
  echo "=== COMPLETE: promise sigil received ==="
  exit 0
fi

# 未达标：把承诺写回 progress.txt，作为下一轮输入
if [ -n "$PROMISE" ]; then
  echo "$PROMISE" > progress.txt
  echo ""
  echo "=== Iteration done. Promise recorded to progress.txt ==="
  echo "Re-run ./ralph-once.sh to continue."
else
  echo ""
  echo "=== WARNING: no <promise>...</promise> in output; progress.txt untouched ===" >&2
fi
