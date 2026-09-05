# 03 — L2 judge 套件（独立 eval 目录）

**What to build:** 生成质量评估层：建议质量/检索相关性/幻觉走 LLM-as-judge，独立 `tests/eval/` 目录（不进默认基线，单独 marker/命令跑）。evaluator 改写自参考代码 `可用来参考的代码案例/CASE-openevals使用`（逐组件标注来源路径）；judge = dev 模型（DashScope Qwen，考官考生同源），judge 调用走 cassette 离线回放；judge 模型名 + 提示词模板版本锁定进 config。

**Blocked by:** 01 — 金标 v1：50 条基准查询落盘

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M1 eval 套件（spec v2）

- [x] `tests/eval/` 套件可独立运行，groundedness / 幻觉 / 建议相关性三类 evaluator 就位（改写来源逐组件标注）— commit `a83d270`：safepass/evaluators.py + tests/eval/（14 测），改写自 CASE-openevals使用
- [x] judge 走 cassette 离线回放；judge 模型 + 提示词版本锁定进 config — config/app.yaml `eval:`（qwen-turbo / 三模板 v4 / pass_threshold）；回放 FailIfCalled 守零真实调用
- [x] 50 条金标 L2 标签逐条产出判定结果 — tests/cassettes/l2_judge.json（150 交互）+ fixtures/eval/l2_results_v1.json；首录 groundedness_mean=0.925 / relevance_mean=0.992 / hallucination_rate=0.04
- [x] 人工前置：录制 cassette 需一次性真实 DashScope key（测试回放不需要）— scripts/record_l2_cassette.py 已跑通；回放零 key
