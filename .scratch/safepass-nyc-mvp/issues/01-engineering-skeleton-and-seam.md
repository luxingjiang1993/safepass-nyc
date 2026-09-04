# 01 — 工程骨架与接缝空壳

**What to build:** 可测试的工程地基：仓库/测试目录布局、集中配置加载（阈值系数、样本量档位、覆盖警区清单、全市均值全部读配置，代码零散落字面量）、LLM 客户端可注入点与录制回放（cassette）基建、唯一接缝 `execute_query(查询文本, 会话画像, 会话状态) → 结构化响应契约` 的空壳实现（当前调用即抛出明确失败）。此后每个切片都能通过该接缝先写红测试。

**Track:** Ralph（机器可验证：pytest 可跑、grep 无散落字面量、接缝空壳存在；prefactor，先于此线一切任务）

**Blocked by:** None — can start immediately.

**Status:** done (2026-09-04, Ralph iteration 1)

- [x] pytest 布局就绪，`pytest tests/ -q` 可空跑通过
- [x] 集中配置文件承载 0.7/1.3 阈值、样本量四档、覆盖警区清单 19/109/5/90/84、全市均值；全库 grep 无这些字面量散落在代码中（配置文件除外）
- [x] LLM 调用经可注入参数传入接缝，测试可注入 fake/stub 与 cassette 回放
- [x] `execute_query` 空壳存在，调用抛出明确的"未实现"错误而非静默返回

**完成证据（iteration 1）**：`pytest tests/ -q` 11 passed（tests/test_skeleton.py：配置加载/校验 3、零散落字面量 grep 审查 2、cassette 录制回放/确定性/严格失败 3、接缝签名与空壳 2、模块布局 1）；`safepass/config_loader.py` 全量实现（阈值/四档样本量/覆盖与排除警区/全市均值/重试上界，含区间无缝衔接等不变量校验，违规抛 ConfigError）；`safepass/llm_client.py` 新增（LLMClient 协议 + chat_with_cassette 严格回放：指纹匹配、耗尽/失配明确失败）；`safepass/pipeline.py` execute_query 空壳（签名冻结、llm_client 注入点、调用即抛 NotImplementedError）。项目源码（safepass/scripts/frontend/fixtures）grep 0.7/1.3/109 为零命中。遗留：city_mean_per_100k 待 T0 fixture 生成后回填（当前 None 为合法状态，评级引擎 T2 要求非空）。
