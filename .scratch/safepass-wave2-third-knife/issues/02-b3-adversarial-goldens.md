# 02 — B3 对抗金标五类每类十条

**What to build:** 偏见、武器、恐慌、越界编造、套话每类新建至少 10 条金标。与注入攻击集分表。放松对应防线时该类至少一条变红。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/37

- [ ] 五类 × ≥10 条新建用例；ID 与 N1、主金标零交集
- [ ] 期望形态为防线拒绝 / 诚实降级 / 紧急 / 合法安全结果之一，禁止半残契约
- [ ] 安全路径上安全评级仍只由确定性引擎写出
- [ ] 负向：放松对应防线 → 该类至少一条红
- [ ] 独立报表或矩阵可链到本夹具；不把用例并进 N1 文件；`python -m pytest tests/ -q` 全绿
