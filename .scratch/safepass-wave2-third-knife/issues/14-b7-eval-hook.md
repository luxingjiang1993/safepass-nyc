# 14 — B7 建议变更回归门壳

**What to build:** 改建议提示词或 Skill 时，文档写明必须跑 L2 子集的命令。本票只做壳，不要求故意改坏提示词必红。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/49

- [ ] 文档有强制命令（eval 标记或等价）
- [ ] 写清默认行为基线仍然不收集 L2
- [ ] 不做「故意改坏 prompt → 红」满门闩
- [ ] `python -m pytest tests/ -q` 全绿
