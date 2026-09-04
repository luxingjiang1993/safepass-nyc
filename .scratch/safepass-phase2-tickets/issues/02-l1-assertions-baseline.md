# 02 — L1 断言进 pytest 基线

**What to build:** 金标的 L1 期望经唯一接缝 `execute_query(查询文本, 会话画像, 会话状态)` 参数化进 `tests/` 现有 pytest 基线：评级、可信度、越界标记、结构化字段全部代码断言，LLM 路径走 cassette/fixture 离线回放。

**Blocked by:** 01 — 金标 v1：50 条基准查询落盘

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M1 eval 套件（spec v2）

- [ ] 50 条金标的 L1 断言参数化执行且全绿
- [ ] 335 条老测试不破（唯一判定 `pytest tests/ -q` 全绿）
- [ ] 测试离线可跑（新增 LLM 调用已录 cassette）
