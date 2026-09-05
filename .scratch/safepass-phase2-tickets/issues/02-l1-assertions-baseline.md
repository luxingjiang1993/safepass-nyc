# 02 — L1 断言进 pytest 基线

**What to build:** 金标的 L1 期望经唯一接缝 `execute_query(查询文本, 会话画像, 会话状态)` 参数化进 `tests/` 现有 pytest 基线：评级、可信度、越界标记、结构化字段全部代码断言，LLM 路径走 cassette/fixture 离线回放。

**Blocked by:** 01 — 金标 v1：50 条基准查询落盘

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M1 eval 套件（spec v2）

- [x] 50 条金标的 L1 断言参数化执行且全绿 — 随票 01 commit `5028038` 落地：24 新查询 safety + 6 detail 追问 + 10 对比 + 10 越界 = 50/50 全覆盖（tests/test_golden_set.py 第 4 节），58 条金标测试全绿
- [x] 335 条老测试不破（唯一判定 `pytest tests/ -q` 全绿）— 393 passed 全绿
- [x] 测试离线可跑（新增 LLM 调用已录 cassette）— 无新增 LLM 调用：新查询/越界走无客户端确定性 fallback，追问轮注入固定路由 stub（spec v2 Testing Decisions：L1 只碰返回契约），全程零网络
