# 18 — B5 Judge 人工校准

**What to build:** 从 L2 覆盖子集抽 15–20 条，由人标 0/1，仓库留下一致率与分歧列表。本票不改 judge 提示词。

**Blocked by:** 17 — L2 重录 cassette

**Status:** ready-for-human

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/53 （原生 blocked by #52）

- [ ] 15–20 条人工 0/1 进仓库（作者勾选，禁止模型代标）
- [ ] 一致率可算；分歧案例列表存在
- [ ] 未改 judge 提示词、未因本票再改口径
- [ ] 对账测试只校验表结构与计算，不发明标签
- [ ] 默认行为基线不依赖「必须高一致率才绿」
