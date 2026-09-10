# 13 — F2 Guardrail 覆盖矩阵

**What to build:** 一张表：输入类型 → 紧急 / 防线拒绝 / 诚实降级 / 覆盖内安全，并链到测试或金标 ID，同时链接 N1 报表与 B3 夹具。

**Blocked by:** 02 — B3 对抗金标五类每类十条

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/48 （原生 blocked by #37）

- [ ] 矩阵覆盖紧急、防线、越界降级、安全主路径
- [ ] 链到真实测试或金标 ID（含 B3 五类与 N1 报表链接）
- [ ] 不把 N1 与 B3 夹具合并成一份
- [ ] `python -m pytest tests/ -q` 全绿
