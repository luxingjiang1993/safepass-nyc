# 06 — 成本三件套：熔断 + 限流 + 成本上报

**What to build:** 日预算熔断器挂在 `LLMClient` 协议注入点（包装器模式）：日预算从 `token-budget.json` 读（生产 $5/日），超限后当日剩余请求走无 LLM 降级——结构化数据照出、建议降级为模板文本、响应必须明示降级不静默。配套请求级限流（窗口参数进 config）与文件级成本上报（JSONL 落盘）。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M2 数据 + 成本（spec v2）

- [x] 熔断包装器就位；fake client 测试断言：超限后 LLM 调用数停增、降级响应带明示标记、结构化数据照出 —— `safepass/cost_control.py` BudgetFusedClient + `tests/test_cost_control.py`（预熔断/中途熔断/限流/对比与降级形态标记全覆盖）
- [x] 限流行为有测试；窗口/阈值字面量在 config，不在代码 —— config `cost_control.rate_limit` 节；限流窗口/上限经 factory 从集中配置读取
- [x] 成本 JSONL 上报落盘，字段含模型/调用数/估算成本 —— config `cost_control.report_path`；JSONL 行含模型/调用数/估算输入输出 token/估算成本/当日累计（文件即当日累计事实源）
- [x] `token-budget.json` 的 `daily_cost_budget_usd` 设为 5
- [x] 老测试不破 —— contracts 三形态加 llm_degraded/degradation_notice 两字段（默认值 False/None，老测试零改动全过）；基线随票 06 交付时 429 绿
- 回填注记（验收审计 2026-09-07）：补齐管线侧 OSError 兜底（容器 /app/logs 缺失的 PermissionError 降级不 500，c191fb4）；Dockerfile runtime 预建上报目录并 chown 非 root 用户
