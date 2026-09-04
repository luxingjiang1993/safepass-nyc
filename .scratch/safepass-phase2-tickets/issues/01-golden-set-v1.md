# 01 — 金标 v1：50 条基准查询落盘

**What to build:** 50 条人工标注的基准查询（金标）落 fixture，按 3 维覆盖矩阵分布：查询形态（新查询/对比追问/细节追问/越界，越界恰占 20%）× 5 核心警区（19/109/5/90/84）× 数据场景（正常/低样本 ⚪/画像敏感，后两者合占 30%）。每条金标带 L1 期望断言数据（评级/可信度/越界标记/结构化字段）与 L2 期望标签（must_mention / must_not_claim）。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M1 eval 套件（spec v2）

- [ ] 50 条金标落盘 fixture，矩阵覆盖逐项可核对（越界恰 20%；低样本 ⚪ + 画像敏感恰 30%；5 警区均有分布）
- [ ] 每条带 L1 期望断言数据与 L2 期望标签
- [ ] fixture 自检测试进 pytest 基线且全绿（沿用既有 fixture 自检模式）
- [ ] 无 `config/app.yaml` 之外的新阈值/档位字面量
